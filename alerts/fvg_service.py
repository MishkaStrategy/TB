"""Application service for FVG detection, filtering and Telegram delivery."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from alerts.fvg_detector import FvgDetector, aggregate_current_15m
from alerts.fvg_models import Candle, FvgDirection, FvgEvent, FvgEventType
from alerts.fvg_store import FvgAlertSettings, FvgEventStore
from alerts.telegram_errors import TelegramErrorKind, classify_telegram_error
from config import (
    DELIVERY_STATUS_TRACKING_ENABLED,
    HEALTH_WRITE_INTERVAL_SECONDS,
    USER_BLOCK_STATUS_ENABLED,
)
from database.telegram_delivery import TelegramDeliveryRegistry
from exchanges.bitunix import BitunixClient


logger = logging.getLogger(__name__)
UTC = timezone.utc
INTERVALS = {"1m": timedelta(minutes=1), "15m": timedelta(minutes=15)}
OUTBOX_BATCH_SIZE = 200
OUTBOX_MAX_BATCHES_PER_PASS = 50


def floor_time(value: datetime, minutes: int) -> datetime:
    value = value.astimezone(UTC)
    return value.replace(
        second=0,
        microsecond=0,
        minute=value.minute - value.minute % minutes,
    )


def parse_rest_candle(raw: dict, symbol: str, timeframe: str, now: datetime) -> Candle:
    try:
        step = INTERVALS[timeframe]
        open_time = datetime.fromtimestamp(int(raw["time"]) / 1000, UTC)
        prices = {
            key: Decimal(str(raw[key]))
            for key in ("open", "high", "low", "close")
        }
    except (KeyError, TypeError, ValueError, InvalidOperation, OSError) as error:
        raise ValueError("Malformed Bitunix candle") from error

    if not all(value.is_finite() and value > 0 for value in prices.values()):
        raise ValueError("Bitunix candle contains non-finite or non-positive prices")

    close_time = open_time + step
    prices["high"] = max(prices["high"], prices["open"], prices["close"])
    prices["low"] = min(prices["low"], prices["open"], prices["close"])
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        is_closed=close_time <= now,
        is_complete=True,
        **prices,
    )


def parse_ws_candle(payload: dict, now: datetime) -> Candle:
    channel = payload["ch"]
    if channel.endswith("_1min"):
        timeframe = "1m"
        step_minutes = 1
    elif channel.endswith("_15min"):
        timeframe = "15m"
        step_minutes = 15
    else:
        raise ValueError(f"Unsupported Bitunix kline channel: {channel}")

    open_time = floor_time(
        datetime.fromtimestamp(int(payload["ts"]) / 1000, UTC),
        step_minutes,
    )
    data = payload["data"]
    raw = {
        "time": int(open_time.timestamp() * 1000),
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
    }
    return parse_rest_candle(raw, payload["symbol"], timeframe, now)


class CandleCache:
    def __init__(self, max_per_series: int = 400):
        self.max_per_series = max_per_series
        self._candles: dict[tuple[str, str], dict[datetime, Candle]] = defaultdict(dict)

    def put(self, candle: Candle) -> None:
        key = (candle.symbol, candle.timeframe)
        self._candles[key][candle.open_time] = candle
        for old_time in sorted(self._candles[key])[:-self.max_per_series]:
            del self._candles[key][old_time]

    def series(self, symbol: str, timeframe: str, now: datetime) -> list[Candle]:
        refreshed = []
        for candle in self._candles[(symbol, timeframe)].values():
            if not candle.is_closed and candle.close_time <= now:
                candle = Candle(**{**candle.__dict__, "is_closed": True})
                self._candles[(symbol, timeframe)][candle.open_time] = candle
            refreshed.append(candle)
        return sorted(refreshed, key=lambda item: item.open_time)


class FvgAlertService:
    def __init__(
        self,
        client=None,
        detector=None,
        settings=None,
        event_store=None,
        delivery_registry=None,
        suppress_unavailable_users=None,
    ):
        self.client = client or BitunixClient()
        self.detector = detector or FvgDetector()
        self.settings = settings or FvgAlertSettings()
        self.event_store = event_store or FvgEventStore()
        self.delivery_registry = delivery_registry
        if self.delivery_registry is None and (
            DELIVERY_STATUS_TRACKING_ENABLED or USER_BLOCK_STATUS_ENABLED
        ):
            self.delivery_registry = TelegramDeliveryRegistry(
                getattr(self.event_store, "path", None)
            )
        self.suppress_unavailable_users = (
            USER_BLOCK_STATUS_ENABLED
            if suppress_unavailable_users is None
            else bool(suppress_unavailable_users)
        )
        self.cache = CandleCache()
        self._delivery_lock = asyncio.Lock()
        self._last_ws_health_write = 0.0

    def _delivery_allowed(self, chat_id: int | str) -> bool:
        return (
            not self.suppress_unavailable_users
            or self.delivery_registry is None
            or self.delivery_registry.can_deliver(chat_id)
        )

    def _filter_recipients(self, recipients) -> list[int]:
        recipients = list(recipients)
        if self.delivery_registry is None or not self.suppress_unavailable_users:
            return recipients
        allowed = [chat_id for chat_id in recipients if self._delivery_allowed(chat_id)]
        suppressed = len(recipients) - len(allowed)
        if suppressed:
            self.event_store.increment_health(
                "delivery_suppressed_inactive_users",
                suppressed,
            )
        return allowed

    def _record_delivery_failure(self, chat_id, decision, error) -> None:
        if self.delivery_registry is not None:
            self.delivery_registry.record_failure(chat_id, decision, error)

    def _record_delivery_success(self, chat_id) -> None:
        if self.delivery_registry is not None:
            self.delivery_registry.record_success(chat_id)

    def recover(self, symbol: str, now: datetime | None = None) -> list[FvgEvent]:
        """Restore recent data and return only timely pre/current confirmed events."""
        now = (now or datetime.now(UTC)).astimezone(UTC)
        for timeframe, limit in (("15m", 20), ("1m", 25)):
            response = self.client.get_candles(symbol, timeframe, limit)
            for raw in response.get("data", []):
                try:
                    candle = parse_rest_candle(raw, symbol, timeframe, now)
                except (ValueError, KeyError, TypeError):
                    self.event_store.increment_health("invalid_candles")
                    continue
                self.cache.put(candle)
        self.event_store.update_health(
            last_rest_recovery=now.isoformat(),
            last_error=None,
        )
        return self.evaluate(symbol, now, recovery=True)

    def ingest_ws(self, payload: dict, now: datetime | None = None) -> list[FvgEvent]:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        candle = parse_ws_candle(payload, now)
        self.cache.put(candle)
        monotonic_now = time.monotonic()
        if monotonic_now - self._last_ws_health_write >= HEALTH_WRITE_INTERVAL_SECONDS:
            self.event_store.update_health(
                last_ws_message=now.isoformat(),
                last_error=None,
            )
            self._last_ws_health_write = monotonic_now
        return self.evaluate(candle.symbol, now)

    def evaluate(
        self,
        symbol: str,
        now: datetime,
        recovery: bool = False,
    ) -> list[FvgEvent]:
        events = []
        closed = [
            candle
            for candle in self.cache.series(symbol, "15m", now)
            if candle.is_closed and candle.is_complete
        ]
        if len(closed) >= 3:
            event = self.detector.detect_confirmed(closed[-3:], now)
            if event and (
                not recovery
                or now - event.candle_c_close_time <= timedelta(minutes=15)
            ):
                events.append(event)

        interval_open = floor_time(now, 15)
        if interval_open + timedelta(minutes=12) <= now < interval_open + timedelta(minutes=13):
            current = aggregate_current_15m(
                symbol,
                self.cache.series(symbol, "1m", now),
                interval_open,
                now,
            )
            previous = [candle for candle in closed if candle.open_time < interval_open]
            if current is not None and len(previous) >= 2:
                event = self.detector.detect_pre(
                    previous[-2],
                    previous[-1],
                    current,
                    now,
                )
                if event:
                    events.append(event)
        return events

    async def deliver(self, bot, events: list[FvgEvent]) -> None:
        """Persist recipients first, then drain due outbox pages."""
        async with self._delivery_lock:
            if not hasattr(self.event_store, "enqueue_deliveries"):
                await self._deliver_without_outbox(bot, events)
                return

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
                    logger.exception(
                        "Failed to evaluate FVG recipients event=%s",
                        event.event_id,
                    )
                    self.event_store.update_health(last_error=str(error))
                    self.event_store.increment_health("recipient_failures")
                    continue

                if not recipients and is_new_event:
                    self.event_store.increment_health("events_without_recipients")
                self.event_store.enqueue_deliveries(
                    event.event_id,
                    recipients,
                    format_fvg_message(event),
                )

            await self._drain_pending_locked(
                bot,
                batch_size=OUTBOX_BATCH_SIZE,
                max_batches=OUTBOX_MAX_BATCHES_PER_PASS,
            )

    async def retry_pending(self, bot, *, limit: int = 100) -> int:
        """Retry persisted Telegram deliveries, including after a restart."""
        if not hasattr(self.event_store, "due_deliveries"):
            return 0
        batch_size = max(1, min(int(limit), 1000))
        async with self._delivery_lock:
            return await self._drain_pending_locked(
                bot,
                batch_size=batch_size,
                max_batches=OUTBOX_MAX_BATCHES_PER_PASS,
            )

    async def _drain_pending_locked(
        self,
        bot,
        *,
        batch_size: int,
        max_batches: int,
    ) -> int:
        completed = 0
        for _ in range(max(1, int(max_batches))):
            items = self.event_store.due_deliveries(limit=batch_size)
            if not items:
                break
            completed += await self._process_pending_items_locked(bot, items)
            if len(items) < batch_size:
                break
        return completed

    async def _process_pending_items_locked(self, bot, items: list[dict]) -> int:
        completed = 0
        for item in items:
            chat_id = item["chat_id"]
            event_id = item["event_id"]
            attempts = int(item.get("attempts", 0))

            if not self._delivery_allowed(chat_id):
                self.event_store.abandon_delivery(chat_id, event_id)
                self.event_store.increment_health(
                    "delivery_suppressed_inactive_users"
                )
                continue

            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=item["message_text"],
                )
            except Exception as error:
                decision = classify_telegram_error(error)
                log = getattr(logger, decision.log_level, logger.warning)
                log(
                    "Telegram delivery failed chat=%s event=%s code=%s attempt=%s: %s",
                    chat_id,
                    event_id,
                    decision.code,
                    attempts + 1,
                    error,
                )

                if decision.kind is TelegramErrorKind.IGNORABLE:
                    self._record_delivery_success(chat_id)
                    self.event_store.mark_delivered(chat_id, event_id)
                    self.event_store.increment_health("delivery_ignored")
                    completed += 1
                    continue

                self._record_delivery_failure(chat_id, decision, error)
                self.event_store.update_health(last_error=str(error))

                if not decision.retryable:
                    self.event_store.abandon_delivery(chat_id, event_id)
                    self.event_store.increment_health(
                        "delivery_permanent_failures"
                    )
                    continue

                delay = decision.retry_after_seconds
                if delay is None:
                    delay = min(300, 5 * (2 ** min(attempts, 6)))
                self.event_store.mark_delivery_failed(
                    chat_id,
                    event_id,
                    str(error),
                    retry_after_seconds=max(1, delay),
                )
                if decision.code == "rate_limited":
                    self.event_store.increment_health("delivery_rate_limited")
                else:
                    self.event_store.increment_health("delivery_failures")
                self.event_store.increment_health("delivery_retries")
            else:
                self._record_delivery_success(chat_id)
                self.event_store.mark_delivered(chat_id, event_id)
                self.event_store.increment_health("notifications_sent")
                completed += 1
        return completed

    async def _deliver_without_outbox(self, bot, events: list[FvgEvent]) -> None:
        """Compatibility path for injected legacy stores in older unit tests."""
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
                self.event_store.update_health(last_error=str(error))
                self.event_store.increment_health("recipient_failures")
                continue
            if not recipients and is_new_event:
                self.event_store.increment_health("events_without_recipients")
            for chat_id in recipients:
                if not self.event_store.delivery_needed(chat_id, event.event_id):
                    continue
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=format_fvg_message(event),
                    )
                except Exception as error:
                    decision = classify_telegram_error(error)
                    logger.warning(
                        "FVG delivery failed chat=%s event=%s code=%s: %s",
                        chat_id,
                        event.event_id,
                        decision.code,
                        error,
                    )
                    if decision.kind is TelegramErrorKind.IGNORABLE:
                        self._record_delivery_success(chat_id)
                        self.event_store.mark_delivered(chat_id, event.event_id)
                        self.event_store.increment_health("delivery_ignored")
                        continue
                    self._record_delivery_failure(chat_id, decision, error)
                    self.event_store.update_health(last_error=str(error))
                    self.event_store.increment_health("delivery_failures")
                    if not decision.retryable:
                        self.event_store.increment_health(
                            "delivery_permanent_failures"
                        )
                    continue
                self._record_delivery_success(chat_id)
                self.event_store.mark_delivered(chat_id, event.event_id)
                self.event_store.increment_health("notifications_sent")


def _price(value: Decimal) -> str:
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def format_fvg_message(event: FvgEvent) -> str:
    bullish = event.direction is FvgDirection.BULLISH
    icon = "🟢🐮" if bullish else "🔴🐻"
    direction = "Бычий" if bullish else "Медвежий"
    if event.event_type is FvgEventType.PRE_FVG:
        title = f"{icon} Возможный {direction.lower()} FVG"
        status = "Предварительный сигнал: свеча C ещё не закрыта"
    else:
        title = f"{icon} Подтверждённый {direction.lower()} FVG"
        status = "Подтверждён закрытием свечи C"
    time_text = event.candle_c_close_time.astimezone(UTC).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    return (
        f"{title}\n"
        f"Инструмент: {event.symbol}\n"
        f"Таймфрейм: {event.timeframe}\n"
        f"Направление: {direction}\n"
        f"Зона FVG: {_price(event.zone_low)} — {_price(event.zone_high)}\n"
        f"Размер зоны: {_price(event.zone_size)}\n"
        f"Цена сигнала: {_price(event.signal_price)}\n"
        f"Время C: {time_text}\n"
        f"Статус: {status}"
    )
