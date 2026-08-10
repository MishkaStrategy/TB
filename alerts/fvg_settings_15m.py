"""Compatibility facade: confirmed FVG only, with 15m as the sole market-data source."""

from __future__ import annotations

from alerts.fvg_store import FvgAlertSettings as BaseFvgAlertSettings
from config import MAX_ACTIVE_SYMBOLS
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES


class FvgAlertSettings(BaseFvgAlertSettings):
    """Preserve confirmed timeframe choices while retiring every pre-FVG switch."""

    def _read(self) -> dict:
        data = super()._read()
        for user in data.get("users", {}).values():
            user["notify_pre_fvg"] = False
            for config in user.get("symbols", {}).values():
                for filter_name in ("price_filter", "size_filter"):
                    filter_config = config.get(filter_name)
                    if isinstance(filter_config, dict):
                        filter_config["apply_to_pre_fvg"] = False
                        filter_config["apply_to_confirmed_fvg"] = True
        return data

    def active_markets(self) -> tuple[tuple[str, str, str], ...]:
        """Cap unique instruments, never individual timeframe rows."""
        timeframes_by_market: dict[tuple[str, str], set[str]] = {}
        for user in self._read().get("users", {}).values():
            if not user.get("enabled") or not user.get("notify_confirmed_fvg", True):
                continue
            for config in user.get("symbols", {}).values():
                if not config.get("enabled", True):
                    continue
                market = (config["exchange"], config["symbol"])
                selected = timeframes_by_market.setdefault(market, set())
                selected.update(config.get("timeframes", ("15m",)))

        active_instruments = sorted(timeframes_by_market)[:MAX_ACTIVE_SYMBOLS]
        return tuple(
            (exchange, symbol, timeframe)
            for exchange, symbol in active_instruments
            for timeframe in CONFIRMED_TIMEFRAMES
            if timeframe in timeframes_by_market[(exchange, symbol)]
        )

    def pre_enabled_chat_ids(self):
        return frozenset()

    def is_pre_enabled(self, chat_id):
        del chat_id
        return False

    def set_pre_enabled(self, chat_id, enabled):
        del enabled
        self.update_user(chat_id, notify_pre_fvg=False)

    def pre_active_markets(self):
        return ()


__all__ = ["FvgAlertSettings"]
