"""FVG service policy: non-BTC markets load only closed 15m candles."""

from __future__ import annotations

from datetime import datetime, timezone

from alerts.fvg_service import FvgAlertService as BaseFvgAlertService
from alerts.fvg_service import parse_rest_candle
from exchanges.fvg_candles import is_bitcoin_symbol


UTC = timezone.utc


class FvgAlertService(BaseFvgAlertService):
    """Keep BTC pre-FVG recovery while avoiding non-BTC minute downloads."""

    def recover(self, symbol: str, now: datetime | None = None):
        now = (now or datetime.now(UTC)).astimezone(UTC)
        series = (("15m", 20), ("1m", 25)) if is_bitcoin_symbol(symbol) else (("15m", 20),)
        for timeframe, limit in series:
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


__all__ = ["FvgAlertService"]