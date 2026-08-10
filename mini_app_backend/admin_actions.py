"""Confirmed administrative actions for the Telegram Mini App.

The settings endpoint deliberately does not execute operational actions. Every
write in this module requires a short-lived, one-time confirmation bound to the
verified Telegram administrator, the exact action and its target.
"""

from __future__ import annotations

import inspect
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry

from .auth import TelegramUser

UTC = timezone.utc
_ALLOWED_ACTIONS = frozenset(
    {
        "allowlist.add",
        "allowlist.remove",
        "access.public",
        "access.private",
        "backup.create",
        "bot.restart",
    }
)


class AdminActionError(RuntimeError):
    """Structured operational error suitable for an API response."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int = 400,
        field: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status = int(status)
        self.field = field


@dataclass(frozen=True)
class _Confirmation:
    admin_id: int
    action: str
    target: str | None
    phrase: str
    expires_at: datetime


class AdminConfirmationStore:
    """In-memory one-time confirmation challenges with a bounded lifetime."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        now: Callable[[], datetime] | None = None,
        max_pending: int = 256,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.ttl_seconds = int(ttl_seconds)
        self.max_pending = int(max_pending)
        self.now = now or (lambda: datetime.now(UTC))
        self._items: dict[str, _Confirmation] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        admin_id: int,
        action: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        if action not in _ALLOWED_ACTIONS:
            raise AdminActionError(
                "Неизвестное административное действие.",
                code="UNKNOWN_ADMIN_ACTION",
                field="action",
            )
        phrase = self._phrase(action, target)
        expires_at = self.now().astimezone(UTC) + timedelta(seconds=self.ttl_seconds)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            if len(self._items) >= self.max_pending:
                oldest = min(self._items, key=lambda value: self._items[value].expires_at)
                self._items.pop(oldest, None)
            self._items[token] = _Confirmation(
                admin_id=int(admin_id),
                action=action,
                target=target,
                phrase=phrase,
                expires_at=expires_at,
            )
        return {
            "token": token,
            "action": action,
            "confirmationText": phrase,
            "expiresAt": expires_at.isoformat(),
        }

    def consume(
        self,
        *,
        token: Any,
        admin_id: int,
        action: str,
        target: str | None,
        confirmation_text: Any,
    ) -> None:
        if not isinstance(token, str) or not token:
            raise AdminActionError(
                "Требуется токен подтверждения.",
                code="CONFIRMATION_TOKEN_REQUIRED",
                field="confirmationToken",
            )
        with self._lock:
            item = self._items.pop(token, None)
        if item is None:
            raise AdminActionError(
                "Подтверждение не найдено или уже использовано.",
                code="CONFIRMATION_INVALID",
                status=409,
                field="confirmationToken",
            )
        if item.expires_at <= self.now().astimezone(UTC):
            raise AdminActionError(
                "Срок подтверждения истёк.",
                code="CONFIRMATION_EXPIRED",
                status=409,
                field="confirmationToken",
            )
        if (
            item.admin_id != int(admin_id)
            or item.action != action
            or item.target != target
        ):
            raise AdminActionError(
                "Подтверждение не соответствует действию или пользователю.",
                code="CONFIRMATION_MISMATCH",
                status=409,
                field="confirmationToken",
            )
        if confirmation_text != item.phrase:
            raise AdminActionError(
                "Текст подтверждения введён неверно.",
                code="CONFIRMATION_TEXT_MISMATCH",
                status=409,
                field="confirmationText",
            )

    def _prune_locked(self) -> None:
        current = self.now().astimezone(UTC)
        expired = [token for token, item in self._items.items() if item.expires_at <= current]
        for token in expired:
            self._items.pop(token, None)

    @staticmethod
    def _phrase(action: str, target: str | None) -> str:
        if action == "allowlist.add":
            return f"ALLOW {target}"
        if action == "allowlist.remove":
            return f"REMOVE {target}"
        if action == "access.public":
            return "PUBLIC ACCESS"
        if action == "access.private":
            return "PRIVATE ACCESS"
        if action == "backup.create":
            return "CREATE BACKUP"
        if action == "bot.restart":
            return "RESTART BOT"
        raise AdminActionError(
            "Неизвестное административное действие.",
            code="UNKNOWN_ADMIN_ACTION",
        )


class MiniAppAdminActions:
    """Execute confirmed admin writes through existing project stores/adapters."""

    def __init__(
        self,
        *,
        admin_checker: Callable[[int], bool],
        access_registry: AccessRegistry | None = None,
        activity_registry: UserActivityRegistry | None = None,
        runtime_settings: RuntimeSettings | None = None,
        env_allowed_ids=(),
        env_admin_ids=(),
        confirmation_store: AdminConfirmationStore | None = None,
        backup_callback: Callable[[TelegramUser], Any] | None = None,
        restart_callback: Callable[[TelegramUser], Any] | None = None,
    ):
        self.admin_checker = admin_checker
        self.access_registry = access_registry or AccessRegistry()
        self.activity_registry = activity_registry or UserActivityRegistry()
        self.runtime_settings = runtime_settings or RuntimeSettings()
        self.env_allowed_ids = frozenset(int(value) for value in env_allowed_ids)
        self.env_admin_ids = frozenset(int(value) for value in env_admin_ids)
        self.confirmations = confirmation_store or AdminConfirmationStore()
        self.backup_callback = backup_callback
        self.restart_callback = restart_callback

    @classmethod
    def from_settings_service(
        cls,
        service,
        *,
        backup_callback: Callable[[TelegramUser], Any] | None = None,
        restart_callback: Callable[[TelegramUser], Any] | None = None,
        confirmation_store: AdminConfirmationStore | None = None,
    ) -> "MiniAppAdminActions":
        return cls(
            admin_checker=getattr(service, "admin_checker", lambda _telegram_id: False),
            access_registry=getattr(service, "access_registry", None),
            activity_registry=getattr(service, "activity_registry", None),
            runtime_settings=getattr(service, "runtime_settings", None),
            env_allowed_ids=getattr(service, "env_allowed_ids", ()),
            env_admin_ids=getattr(service, "env_admin_ids", ()),
            confirmation_store=confirmation_store,
            backup_callback=backup_callback,
            restart_callback=restart_callback,
        )

    def capabilities(self, user: TelegramUser) -> dict[str, bool]:
        if not self.admin_checker(user.id):
            return {
                "accessWrite": False,
                "allowlistWrite": False,
                "backup": False,
                "restart": False,
            }
        return {
            "accessWrite": True,
            "allowlistWrite": True,
            "backup": self.backup_callback is not None,
            "restart": self.restart_callback is not None,
        }

    def create_confirmation(
        self,
        user: TelegramUser,
        *,
        action: Any,
        target_telegram_id: Any = None,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        if not isinstance(action, str):
            raise AdminActionError(
                "Поле action должно быть строкой.",
                code="INVALID_ADMIN_ACTION",
                field="action",
            )
        target = None
        if action in {"allowlist.add", "allowlist.remove"}:
            target = str(self._telegram_id(target_telegram_id))
        return self.confirmations.issue(
            admin_id=user.id,
            action=action,
            target=target,
        )

    def set_public_access(
        self,
        user: TelegramUser,
        *,
        public_access_enabled: Any,
        confirmation_token: Any,
        confirmation_text: Any,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        if not isinstance(public_access_enabled, bool):
            raise AdminActionError(
                "Значение publicAccessEnabled должно быть true или false.",
                code="INVALID_PUBLIC_ACCESS",
                field="publicAccessEnabled",
            )
        action = "access.public" if public_access_enabled else "access.private"
        self.confirmations.consume(
            token=confirmation_token,
            admin_id=user.id,
            action=action,
            target=None,
            confirmation_text=confirmation_text,
        )
        self.runtime_settings.set_public_access_enabled(public_access_enabled)
        return {"publicAccessEnabled": public_access_enabled}

    def add_allowlist(
        self,
        user: TelegramUser,
        *,
        target_telegram_id: Any,
        name: Any = None,
        username: Any = None,
        confirmation_token: Any,
        confirmation_text: Any,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        target_id = self._telegram_id(target_telegram_id)
        self.confirmations.consume(
            token=confirmation_token,
            admin_id=user.id,
            action="allowlist.add",
            target=str(target_id),
            confirmation_text=confirmation_text,
        )
        tracked = self.activity_registry.users().get(str(target_id), {})
        resolved_name = self._optional_text(name, "name", 128) or tracked.get("name")
        resolved_username = (
            self._optional_text(username, "username", 64, strip_at=True)
            or tracked.get("username")
        )
        record = self.access_registry.allow(
            target_id,
            name=resolved_name,
            username=resolved_username,
        )
        return {
            "telegramId": target_id,
            "name": record.get("name") or "Без имени",
            **(
                {"username": record.get("username")}
                if record.get("username")
                else {}
            ),
            "source": "runtime",
        }

    def remove_allowlist(
        self,
        user: TelegramUser,
        *,
        target_telegram_id: Any,
        confirmation_token: Any,
        confirmation_text: Any,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        target_id = self._telegram_id(target_telegram_id)
        if (
            target_id in self.env_allowed_ids
            or target_id in self.env_admin_ids
            or self.admin_checker(target_id)
        ):
            raise AdminActionError(
                "Нельзя удалить env-пользователя или администратора через Mini App.",
                code="PROTECTED_ACCESS_RECORD",
                status=409,
                field="telegramId",
            )
        self.confirmations.consume(
            token=confirmation_token,
            admin_id=user.id,
            action="allowlist.remove",
            target=str(target_id),
            confirmation_text=confirmation_text,
        )
        if not self.access_registry.remove(target_id):
            raise AdminActionError(
                "Runtime-запись allowlist не найдена.",
                code="ALLOWLIST_RECORD_NOT_FOUND",
                status=404,
                field="telegramId",
            )
        return {"telegramId": target_id, "removed": True}

    async def create_backup(
        self,
        user: TelegramUser,
        *,
        confirmation_token: Any,
        confirmation_text: Any,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        self.confirmations.consume(
            token=confirmation_token,
            admin_id=user.id,
            action="backup.create",
            target=None,
            confirmation_text=confirmation_text,
        )
        return await self._invoke_optional(
            self.backup_callback,
            user,
            unavailable_code="BACKUP_ACTION_UNAVAILABLE",
            unavailable_message=(
                "Ручной backup не подключён к production-адаптеру. "
                "Endpoint остаётся безопасно выключенным."
            ),
        )

    async def restart_bot(
        self,
        user: TelegramUser,
        *,
        confirmation_token: Any,
        confirmation_text: Any,
    ) -> dict[str, Any]:
        self._ensure_admin(user)
        self.confirmations.consume(
            token=confirmation_token,
            admin_id=user.id,
            action="bot.restart",
            target=None,
            confirmation_text=confirmation_text,
        )
        return await self._invoke_optional(
            self.restart_callback,
            user,
            unavailable_code="RESTART_ACTION_UNAVAILABLE",
            unavailable_message=(
                "Перезапуск не подключён к production restart-guard. "
                "Endpoint остаётся безопасно выключенным."
            ),
        )

    def _ensure_admin(self, user: TelegramUser) -> None:
        if not self.admin_checker(user.id):
            raise AdminActionError(
                "Административные права не подтверждены.",
                code="ADMIN_REQUIRED",
                status=403,
            )

    @staticmethod
    def _telegram_id(value: Any) -> int:
        if isinstance(value, bool):
            raise AdminActionError(
                "Telegram ID должен быть положительным целым числом.",
                code="INVALID_TELEGRAM_ID",
                field="telegramId",
            )
        try:
            telegram_id = int(value)
        except (TypeError, ValueError) as error:
            raise AdminActionError(
                "Telegram ID должен быть положительным целым числом.",
                code="INVALID_TELEGRAM_ID",
                field="telegramId",
            ) from error
        if telegram_id <= 0:
            raise AdminActionError(
                "Telegram ID должен быть положительным целым числом.",
                code="INVALID_TELEGRAM_ID",
                field="telegramId",
            )
        return telegram_id

    @staticmethod
    def _optional_text(
        value: Any,
        field: str,
        max_length: int,
        *,
        strip_at: bool = False,
    ) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise AdminActionError(
                f"Поле {field} должно быть строкой.",
                code="INVALID_ADMIN_FIELD",
                field=field,
            )
        normalized = value.strip()
        if strip_at:
            normalized = normalized.lstrip("@")
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise AdminActionError(
                f"Поле {field} слишком длинное.",
                code="ADMIN_FIELD_TOO_LONG",
                field=field,
            )
        return normalized

    @staticmethod
    async def _invoke_optional(
        callback: Callable[[TelegramUser], Any] | None,
        user: TelegramUser,
        *,
        unavailable_code: str,
        unavailable_message: str,
    ) -> dict[str, Any]:
        if callback is None:
            raise AdminActionError(
                unavailable_message,
                code=unavailable_code,
                status=409,
            )
        result = callback(user)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return {"accepted": True}
        if isinstance(result, dict):
            return result
        return {"accepted": bool(result)}
