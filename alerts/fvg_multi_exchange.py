"""Shared multi-exchange polling for confirmed FVG and BTC-only pre-FVG."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from alerts.fvg_detector import FvgDetector, aggregate_current_15m
from alerts.fvg_models import FvgEvent, event_id
from alerts.fvg_service import floor_time
from exchanges.funding import normalize_exchange
from exchanges.fvg_candles import PublicCandleClient, is_bitcoin_symbol


UTC = timezone.utc


class MultiExchangeFvgPoller:
    def __init__(self, candle_client=None, detector=None):
        self.candle_client = candle_client or PublicCandleClient()
        self.detector = detector or FvgDetector()

    @staticmethod
    def _with_exchange(event: FvgEvent | None, exchange: str) -> FvgEvent | None:
        if event is None:
            return None
        exchange = normalize_exchange(exchange)
        return replace(
            event,
            exchange=exchange,
            event_id=event_id(
                event.symbol,
                event.timeframe,
                event.direction,
                event.candle_c_open_time,
                event.event_type,
                exchange,
            ),
        )

    def confirmed(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        now: datetime | None = None,
    ) -> list[FvgEvent]:
        if timeframe != "15m" and not is_bitcoin_symbol(symbol):
            return []
        now = (now or datetime.now(UTC)).astimezone(UTC)
        candles = self.candle_client.load(
            exchange,
            symbol,
            timeframe,
            limit=3,
            now=now,
        )
        if len(candles) != 3:
            return []
        event = self.detector.detect_confirmed(candles, now)
        event = self._with_exchange(event, exchange)
        return [event] if event is not None else []

    def preliminary(
        self,
        exchange: str,
        symbol: str,
        now: datetime | None = None,
    ) -> list[FvgEvent]:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        if not is_bitcoin_symbol(symbol):
            return []
        interval_open = floor_time(now, 15)
        control_start = interval_open + timedelta(minutes=12)
        if not (control_start <= now < control_start + timedelta(minutes=1)):
            return []

        previous = self.candle_client.load(
            exchange,
            symbol,
            "15m",
            limit=3,
            now=now,
        )
        previous = [item for item in previous if item.open_time < interval_open]
        minutes = self.candle_client.load(
            exchange,
            symbol,
            "1m",
            limit=20,
            now=now,
        )
        current = aggregate_current_15m(
            symbol,
            minutes,
            interval_open,
            now,
        )
        if current is None or len(previous) < 2:
            return []
        event = self.detector.detect_pre(previous[-2], previous[-1], current, now)
        event = self._with_exchange(event, exchange)
        return [event] if event is not None else []


__all__ = ["MultiExchangeFvgPoller"]