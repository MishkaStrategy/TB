"""Production service refinements for stateful funding alert behavior."""

from __future__ import annotations

from .service import MiniAppSettingsService as BaseMiniAppSettingsService


class MiniAppSettingsService(BaseMiniAppSettingsService):
    """Keep multi-exchange crossing state consistent with Telegram settings UI."""

    def _save_funding(self, telegram_id: int, desired: dict) -> None:
        current = self.funding_settings.user(telegram_id)
        selected = tuple(self.funding_exchanges.selected(telegram_id))
        clear_exchange_crossings = bool(
            current["notify_positive"] != desired["notify_positive"]
            or current["notify_negative"] != desired["notify_negative"]
            or current["threshold"] != desired["threshold"]
            or selected != tuple(desired["exchanges"])
            or (current["enabled"] and not desired["enabled"])
        )

        super()._save_funding(telegram_id, desired)

        # FundingAlertStore clears its legacy crossing table. Multi-exchange
        # alerts keep a separate table, which must be reset under the same
        # conditions to avoid stale threshold-crossing decisions.
        if clear_exchange_crossings:
            self.funding_exchanges.clear_crossings(telegram_id)
