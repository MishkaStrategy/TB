"""Production service refinements for stateful Mini App behavior."""

from __future__ import annotations

from typing import Any

from .diagnostics import (
    collect_admin_diagnostics,
    empty_admin_diagnostics,
    normalize_admin_diagnostics,
)
from .service import (
    MiniAppSettingsService as BaseMiniAppSettingsService,
    _normalize_settings_payload,
)


class MiniAppSettingsService(BaseMiniAppSettingsService):
    """Production adapter for funding state and administrative diagnostics."""

    def save_settings(self, user, settings_payload: Any) -> dict:
        """Save personal settings only.

        Administrative writes are intentionally excluded from the general PUT
        endpoint. Access mode, allowlist, backup and restart use dedicated
        one-time-confirmed endpoints in ``admin_actions``.
        """

        if not self.is_authorized(user.id):
            raise PermissionError("Доступ к Mini App не разрешён.")
        normalized = _normalize_settings_payload(
            settings_payload, max_symbols=self.max_symbols_per_user
        )

        current_general = self.preferences.ensure(user.id)
        if current_general["language"] != normalized["general"]["language"]:
            self.preferences.set_language(user.id, normalized["general"]["language"])
        if current_general["message_mode"] != normalized["general"]["message_mode"]:
            self.preferences.set_message_mode(
                user.id, normalized["general"]["message_mode"]
            )

        self._replace_fvg_user(user.id, normalized["fvg"])
        self._save_funding(user.id, normalized["funding"])
        self.activity_registry.touch(user)
        return self._envelope(user)

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

    def _default_diagnostics(self) -> dict:
        return collect_admin_diagnostics(
            funding_database_path=self.funding_settings.path
        )

    def _admin_settings(self, available: bool) -> dict:
        if not available:
            return {
                "available": False,
                "publicAccessEnabled": False,
                "allowedUsers": [],
                "diagnostics": empty_admin_diagnostics(),
            }
        return {
            "available": True,
            "publicAccessEnabled": self.public_access_enabled(),
            "allowedUsers": self._allowed_users(),
            "diagnostics": normalize_admin_diagnostics(
                self.diagnostics_provider()
            ),
        }
