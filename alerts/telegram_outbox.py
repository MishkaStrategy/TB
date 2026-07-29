"""Async Telegram worker for the explicit SQLite outbox state machine."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from alerts.telegram_errors import TelegramErrorKind, classify_telegram_error
from database.outbox_compat import FvgOutboxCompatibility
from database.telegram_outbox import TelegramOutboxStore


LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass(frozen=True)
class OutboxRetryPolicy:
    max_attempts: int = 8
    base_delay_seconds: float = 5
    max_delay_seconds: float = 900
    jitter_ratio: float = 0.2
    lease_seconds: float = 120
    terminal_retention_days: int = 30

    def retry_delay(self, attempt: int, *, random_value: float | None = None) -> float:
        attempt = max(1, int(attempt))
        base = min(
            float(self.max_delay_seconds),
            float(self.base_delay_seconds) * (2 ** (attempt - 1)),
        )
        value = random.random() if random_value is None else float(random_value)
        value = min(1.0, max(0.0, value))
        factor = 1 - self.jitter_ratio + (2 * self.jitter_ratio * value)
        return max(1.0, min(float(self.max_delay_seconds), base * factor))


class TelegramOutboxWorker:
    def __init__(
        self,
        store: TelegramOutboxStore,
        *,
        delivery_registry=None,
        metrics=None,
        policy: OutboxRetryPolicy | None = None,
        compatibility=None,
        suppress_unavailable_users: bool = True,
    ):
        self.store = store
        self.delivery_registry = delivery_registry
        self.metrics = metrics
        self.policy = policy or OutboxRetryPolicy()
        self.compatibility = compatibility
        self.suppress_unavailable_users = bool(suppress_unavailable_users)
        if self.compatibility is None and metrics is not None:
            path = getattr(metrics, "path", None)
            if path is not None:
                self.compatibility = FvgOutboxCompatibility(path)
        self.worker_id = f"{os.getpid()}:{uuid.uuid4()}"
        self.last_claimed_count = 0
        self._lock = asyncio.Lock()

    def _increment(self, key: str, amount: int = 1) -> None:
        method = getattr(self.metrics, "increment_health", None)
        if callable(method):
            method(key, amount)

    async def _sync_domain_finalizations(
        self,
        *,
        limit: int = 500,
        now: datetime | None = None,
    ) -> int:
        if self.compatibility is None:
            return 0
        try:
            return await asyncio.to_thread(
                self.compatibility.sync_terminal,
                self.store,
                self.metrics,
                limit=limit,
                now=now,
            )
        except Exception:
            LOGGER.exception("Outbox domain finalization failed")
            self._increment("outbox_domain_finalization_failures")
            return 0

    async def drain(self, bot, *, limit: int = 100, now: datetime | None = None) -> int:
        async with self._lock:
            await self._sync_domain_finalizations(limit=max(limit, 500), now=now)
            await asyncio.to_thread(
                self.store.maintenance,
                terminal_retention_days=self.policy.terminal_retention_days,
                now=now,
            )
            await self._sync_domain_finalizations(limit=max(limit, 500), now=now)
            items = await asyncio.to_thread(
                self.store.claim_due,
                worker_id=self.worker_id,
                limit=limit,
                lease_seconds=self.policy.lease_seconds,
                now=now,
            )
            self.last_claimed_count = len(items)
            delivered = 0
            for item in items:
                delivered += await self._deliver_item(bot, item, now=now)
            await self._sync_domain_finalizations(limit=max(limit, 500), now=now)
            return delivered

    async def _deliver_item(self, bot, item: dict, *, now: datetime | None = None) -> int:
        chat_id = item["chat_id"]
        if (
            self.suppress_unavailable_users
            and self.delivery_registry is not None
            and not await asyncio.to_thread(
                self.delivery_registry.can_deliver,
                chat_id,
            )
        ):
            await asyncio.to_thread(
                self.store.mark_cancelled,
                item["id"],
                self.worker_id,
                error_code="delivery_suppressed_inactive_user",
                now=now,
            )
            self._increment("outbox_cancelled_inactive_user")
            return 0

        if item["operation"] != "send_message":
            await asyncio.to_thread(
                self.store.mark_permanent,
                item["id"],
                self.worker_id,
                error=RuntimeError(f"Unsupported operation: {item['operation']}"),
                error_code="unsupported_outbox_operation",
                now=now,
            )
            self._increment("outbox_permanent_failures")
            return 0

        payload = dict(item["payload"])
        payload["chat_id"] = int(chat_id)
        try:
            message = await bot.send_message(**payload)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            decision = classify_telegram_error(error)
            if self.delivery_registry is not None:
                if decision.kind is TelegramErrorKind.IGNORABLE:
                    await asyncio.to_thread(
                        self.delivery_registry.record_success,
                        chat_id,
                    )
                else:
                    await asyncio.to_thread(
                        self.delivery_registry.record_failure,
                        chat_id,
                        decision,
                        error,
                        discard_outbox=self.suppress_unavailable_users,
                    )

            if decision.kind is TelegramErrorKind.IGNORABLE:
                await asyncio.to_thread(
                    self.store.mark_delivered,
                    item["id"],
                    self.worker_id,
                    now=now,
                )
                self._increment("outbox_ignored")
                return 1

            if decision.ambiguous_delivery:
                await asyncio.to_thread(
                    self.store.mark_dead_letter,
                    item["id"],
                    self.worker_id,
                    error=error,
                    error_code="delivery_outcome_unknown",
                    now=now,
                )
                self._increment("outbox_ambiguous_dead_letter")
                return 0

            if not decision.retryable:
                await asyncio.to_thread(
                    self.store.mark_permanent,
                    item["id"],
                    self.worker_id,
                    error=error,
                    error_code=decision.code,
                    now=now,
                )
                self._increment("outbox_permanent_failures")
                return 0

            if item["attempts"] >= min(
                item["max_attempts"],
                self.policy.max_attempts,
            ):
                await asyncio.to_thread(
                    self.store.mark_dead_letter,
                    item["id"],
                    self.worker_id,
                    error=error,
                    error_code="max_attempts_exhausted",
                    now=now,
                )
                self._increment("outbox_dead_letter")
                return 0

            delay = decision.retry_after_seconds
            if delay is None:
                delay = self.policy.retry_delay(item["attempts"])
            retry_at = (now or datetime.now(UTC)).astimezone(UTC) + timedelta(
                seconds=delay
            )
            await asyncio.to_thread(
                self.store.schedule_retry,
                item["id"],
                self.worker_id,
                next_attempt_at=retry_at,
                error=error,
                error_code=decision.code,
                now=now,
            )
            self._increment("outbox_retries")
            return 0
        else:
            if self.delivery_registry is not None:
                await asyncio.to_thread(
                    self.delivery_registry.record_success,
                    chat_id,
                )
            await asyncio.to_thread(
                self.store.mark_delivered,
                item["id"],
                self.worker_id,
                telegram_message_id=getattr(message, "message_id", None),
                now=now,
            )
            self._increment("outbox_delivered")
            return 1
