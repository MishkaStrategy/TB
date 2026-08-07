"""Active FVG service policy: confirmed 15m candles only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alerts.fvg_service import FvgAlertService as BaseFvgAlertService
from alerts.fvg_service import parse_rest_candle
from alerts.fvg_settings_15m import FvgAlertSettings


UTC = timezone.utc


class FvgAlertService(BaseFvgAlertService):
    """Disable pre-FVG and keep every active FVG data path on closed 15m candles."""

    def __init__(
        self,
        client=None,
        detector=None,
        settings=None,
        event_store=None,
        delivery_registry=None,
        suppress_unavailable_users=None,
    ):
        super().__init__(
            client=client,
            detector=detector,
            settings=settings or FvgAlertSettings(),
            event_store=event_store,
            delivery_registry=delivery_registry,
            suppress_unavailable_users=suppress_unavailable_users,
        )

    def recover(self, symbol: str, now: datetime | None = None):
        now = (now or datetime.now(UTC)).astimezone(UTC)
        response = self.client.get_candles(symbol, "15m", 20)
        for raw in response.get("data", []):
            try:
                candle = parse_rest_candle(raw, symbol, "15m", now)
            except (ValueError, KeyError, TypeError):
                self.event_store.increment_health("invalid_candles")
                continue
            self.cache.put(candle)
        self.event_store.update_health(
            last_rest_recovery=now.isoformat(),
            last_error=None,
        )
        return self.evaluate(symbol, now, recovery=True)

    def ingest_ws(self, payload: dict, now: datetime | None = None):
        channel = str(payload.get("ch", ""))
        if not channel.endswith("_15min"):
            raise ValueError("Only Bitunix 15m FVG candles are supported")
        return super().ingest_ws(payload, now)

    def evaluate(
        self,
        symbol: str,
        now: datetime,
        recovery: bool = False,
    ):
        """Evaluate confirmed FVG only; preliminary events no longer exist."""
        closed = [
            candle
            for candle in self.cache.series(symbol, "15m", now)
            if candle.is_closed and candle.is_complete
        ]
        if len(closed) < 3:
            return []
        event = self.detector.detect_confirmed(closed[-3:], now)
        if event is None:
            return []
        if recovery and now - event.candle_c_close_time > timedelta(minutes=15):
            return []
        return [event]


__all__ = ["FvgAlertService"]
