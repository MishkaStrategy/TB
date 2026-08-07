"""15-minute-only compatibility facade for persisted FVG preferences."""

from __future__ import annotations

from alerts.fvg_store import FvgAlertSettings as BaseFvgAlertSettings


class FvgAlertSettings(BaseFvgAlertSettings):
    """Interpret all existing subscriptions as confirmed 15m subscriptions."""

    def _read(self) -> dict:
        data = super()._read()
        for user in data.get("users", {}).values():
            user["notify_pre_fvg"] = False
            for config in user.get("symbols", {}).values():
                config["timeframes"] = ["15m"]
                for filter_name in ("price_filter", "size_filter"):
                    filter_config = config.get(filter_name)
                    if isinstance(filter_config, dict):
                        filter_config["apply_to_pre_fvg"] = False
                        filter_config["apply_to_confirmed_fvg"] = True
        return data

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
