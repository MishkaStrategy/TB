"""Shared multi-exchange polling for confirmed 15m FVG only."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from alerts.fvg_detector import FvgDetector
from alerts.fvg_models import FvgEvent, event_id
from exchanges.funding import normalize_exchange
from exchanges.fvg_candles import PublicCandleClient


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
        timeframe: str = "15m",
        now: datetime | None = None,
    ) -> list[FvgEvent]:
        """Load exactly three closed 15m candles and evaluate one confirmed FVG."""
        if timeframe != "15m":
            return []
        now = (now or datetime.now(UTC)).astimezone(UTC)
        candles = self.candle_client.load(
            exchange,
            symbol,
            "15m",
            limit=3,
            now=now,
        )
        if len(candles) != 3:
            return []
        event = self.detector.detect_confirmed(candles, now)
        event = self._with_exchange(event, exchange)
        return [event] if event is not None else []


__all__ = ["MultiExchangeFvgPoller"]
