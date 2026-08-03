"""Feature-flagged FVG delivery through the explicit Telegram Outbox V2."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from alerts.fvg_models import FvgEvent, FvgEventType
from alerts.fvg_service import (
    OUTBOX_BATCH_SIZE,
    OUTBOX_MAX_BATCHES_PER_PASS,
    format_fvg_message,
)
from alerts.fvg_limited_service import FvgAlertService
from alerts.telegram_outbox import OutboxRetryPolicy, TelegramOutboxWorker
from config import (
    OUTBOX_BASE_BACKOFF_SECONDS,
    OUTBOX_DEFAULT_TTL_SECONDS,
    OUTBOX_EXPIRATION_ENABLED,
    OUTBOX_JITTER_RATIO,
    OUTBOX_MAX_ATTEMPTS,
    OUTBOX_MAX_BACKOFF_SECONDS,
    OUTBOX_PROCESSING_LEASE_SECONDS,
    OUTBOX_TERMINAL_RETENTION_DAYS,
)
from database.outbox_compat import FvgOutboxCompatibility
from database.telegram_delivery import TelegramDeliveryRegistry
from database.telegram_outbox import TelegramOutboxStore


LOGGER = logging.getLogger(__name__)


class OutboxV2FvgAlertService(FvgAlertService):
    """Keep detection/filtering unchanged and replace only delivery persistence."""

    def __init__(
        self,
        *args,
        outbox_store=None,
        outbox_worker=None,
        outbox_compatibility=None,
        expiration_enabled=None,
        default_ttl_seconds=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        database_path = getattr(self.event_store, "path", None)
        self.outbox_store = outbox_store or TelegramOutboxStore(database_path)
        self.outbox_compatibility = (
            outbox_compatibility
            or FvgOutboxCompatibility(self.outbox_store.path)
        )
        if self.delivery_registry is None:
            self.delivery_registry = TelegramDeliveryRegistry(
                self.outbox_store.path,
                discard_outbox_by_default=self.suppress_unavailable_users,
            )
        self.expiration_enabled = (
            OUTBOX_EXPIRATION_ENABLED
            if expiration_enabled is None
            else bool(expiration_enabled)
        )
        self.default_ttl_seconds = int(
            OUTBOX_DEFAULT_TTL_SECONDS
            if default_ttl_seconds is None
            else default_ttl_seconds
        )
        policy = OutboxRetryPolicy(
            max_attempts=OUTBOX_MAX_ATTEMPTS,
            base_delay_seconds=OUTBOX_BASE_BACKOFF_SECONDS,
            max_delay_seconds=OUTBOX_MAX_BACKOFF_SECONDS,
            jitter_ratio=OUTBOX_JITTER_RATIO,
            lease_seconds=OUTBOX_PROCESSING_LEASE_SECONDS,
            terminal_retention_days=OUTBOX_TERMINAL_RETENTION_DAYS,
        )
        self.outbox_worker = outbox_worker or TelegramOutboxWorker(
            self.outbox_store,
            delivery_registry=self.delivery_registry,
            metrics=self.event_store,
            policy=policy,
            compatibility=self.outbox_compatibility,
            suppress_unavailable_users=self.suppress_unavailable_users,
        )
        self._copy_legacy_backlog()

    def _copy_legacy_backlog(self) -> int:
        result = self.outbox_compatibility.copy_legacy_to_v2(
            self.outbox_store,
            default_ttl_seconds=(
                self.default_ttl_seconds
                if self.expiration_enabled
                else None
            ),
            max_attempts=OUTBOX_MAX_ATTEMPTS,
        )
        copied = int(result.get("copied") or 0)
        if copied:
            self.event_store.increment_health("outbox_v2_legacy_copied", copied)
        return copied

    def _expires_at(self, event: FvgEvent):
        if not self.expiration_enabled:
            return None
        if event.event_type is FvgEventType.PRE_FVG:
            return event.candle_c_close_time
        return event.detected_at + timedelta(seconds=self.default_ttl_seconds)

    def _enqueue_event(self, event: FvgEvent, recipients: list[int]) -> int:
        message = format_fvg_message(event)
        # Legacy rows are rollback mirrors. The V2 worker is the only consumer
        # while the feature flag is enabled and synchronizes terminal states.
        self.event_store.enqueue_deliveries(
            event.event_id,
            recipients,
            message,
        )
        inserted = 0
        for chat_id in recipients:
            if not self.event_store.delivery_needed(chat_id, event.event_id):
                continue
            item = self.outbox_store.enqueue(
                notification_type="fvg",
                event_type=event.event_type.value,
                event_id=event.event_id,
                chat_id=chat_id,
                payload={"text": message},
                idempotency_key=f"fvg:{event.event_id}:{chat_id}",
                expires_at=self._expires_at(event),
                max_attempts=OUTBOX_MAX_ATTEMPTS,
                now=event.detected_at,
            )
            inserted += int(item["inserted"])
        if inserted:
            self.event_store.increment_health("outbox_v2_enqueued", inserted)
        return inserted

    async def _drain_v2_locked(
        self,
        bot,
        *,
        batch_size: int,
        max_batches: int,
    ) -> int:
        completed = 0
        for _ in range(max(1, int(max_batches))):
            # Copying is idempotent and repairs a partial dual-write after a
            # process crash without evaluating the market event again.
            await asyncio.to_thread(self._copy_legacy_backlog)
            completed += await self.outbox_worker.drain(
                bot,
                limit=batch_size,
            )
            if self.outbox_worker.last_claimed_count < batch_size:
                break
        return completed

    async def deliver(self, bot, events: list[FvgEvent]) -> None:
        async with self._delivery_lock:
            for event in events:
                is_new_event = self.event_store.record_event(event)
                if is_new_event:
                    self.event_store.increment_health(
                        "pre_events"
                        if event.event_type is FvgEventType.PRE_FVG
                        else "confirmed_events"
                    )
                try:
                    recipients = self._filter_recipients(
                        self.settings.recipients(event)
                    )
                except Exception as error:
                    LOGGER.exception(
                        "Failed to evaluate FVG recipients event=%s",
                        event.event_id,
                    )
                    self.event_store.update_health(last_error=str(error))
                    self.event_store.increment_health("recipient_failures")
                    continue
                if not recipients and is_new_event:
                    self.event_store.increment_health("events_without_recipients")
                self._enqueue_event(event, recipients)

            await self._drain_v2_locked(
                bot,
                batch_size=OUTBOX_BATCH_SIZE,
                max_batches=OUTBOX_MAX_BATCHES_PER_PASS,
            )

    async def retry_pending(self, bot, *, limit: int = 100) -> int:
        batch_size = max(1, min(int(limit), 1000))
        async with self._delivery_lock:
            return await self._drain_v2_locked(
                bot,
                batch_size=batch_size,
                max_batches=OUTBOX_MAX_BATCHES_PER_PASS,
            )
