"""Classification of Telegram delivery failures into stable operational decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum


class TelegramErrorKind(str, Enum):
    """High-level outcome used by delivery workers."""

    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    IGNORABLE = "ignorable"


class TelegramDeliveryStatus(str, Enum):
    """Durable Telegram delivery state for a chat."""

    ACTIVE = "active"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    BLOCKED = "blocked"
    DEACTIVATED = "deactivated"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class TelegramErrorDecision:
    kind: TelegramErrorKind
    code: str
    retryable: bool
    delivery_status: TelegramDeliveryStatus | None = None
    retry_after_seconds: float | None = None
    ambiguous_delivery: bool = False
    notify_admin: bool = False
    log_level: str = "warning"


_BLOCKED_PATTERNS = (
    "bot was blocked by the user",
    "bot was blocked by user",
    "user blocked the bot",
    "bot is blocked by the user",
)
_DEACTIVATED_PATTERNS = (
    "user is deactivated",
    "user deactivated",
    "account was deleted",
    "deleted account",
)
_CHAT_MISSING_PATTERNS = (
    "chat not found",
    "user not found",
    "peer_id_invalid",
    "peer id invalid",
)
_RIGHTS_PATTERNS = (
    "bot was kicked",
    "bot is not a member",
    "not enough rights",
    "have no rights",
    "need administrator rights",
    "bot is not an administrator",
)
_MESSAGE_FINAL_PATTERNS = (
    "message to edit not found",
    "message can't be edited",
    "message can not be edited",
    "message identifier is not specified",
)
_IGNORABLE_PATTERNS = (
    "message is not modified",
    "query is too old",
    "message to delete not found",
)
_SERVER_PATTERNS = (
    "bad gateway",
    "gateway timeout",
    "service unavailable",
    "internal server error",
    "telegram server error",
)
_PRE_SEND_TIMEOUT_CAUSES = frozenset({"ConnectTimeout", "PoolTimeout"})


def _contains(message: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in message for pattern in patterns)


def _retry_after_seconds(error: BaseException) -> float | None:
    value = getattr(error, "retry_after", None)
    if isinstance(value, timedelta):
        value = value.total_seconds()
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return None


def _cause_class_name(error: BaseException) -> str | None:
    cause = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    return type(cause).__name__ if cause is not None else None


def classify_telegram_error(error: BaseException) -> TelegramErrorDecision:
    """Return retry, finalization and user-status policy for a Telegram error.

    Classification intentionally uses public exception class names instead of
    importing python-telegram-bot classes. This keeps the policy independently
    testable and also handles wrapped/subclassed Telegram exceptions.

    A read/write timeout can happen after Telegram accepted ``sendMessage`` but
    before the response reached the bot. Repeating that request can duplicate an
    alert, so such timeouts are explicitly marked as ambiguous. Connection-pool
    and connect timeouts are considered pre-send and remain safely retryable.
    """

    class_name = type(error).__name__
    message = str(error).strip().lower()

    if class_name == "RetryAfter" or getattr(error, "retry_after", None) is not None:
        return TelegramErrorDecision(
            kind=TelegramErrorKind.TEMPORARY,
            code="rate_limited",
            retryable=True,
            delivery_status=TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE,
            retry_after_seconds=_retry_after_seconds(error),
            log_level="info",
        )

    if _contains(message, _IGNORABLE_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.IGNORABLE,
            code="message_not_actionable",
            retryable=False,
            log_level="info",
        )

    if _contains(message, _BLOCKED_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="bot_blocked_by_user",
            retryable=False,
            delivery_status=TelegramDeliveryStatus.BLOCKED,
        )

    if _contains(message, _DEACTIVATED_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="user_deactivated",
            retryable=False,
            delivery_status=TelegramDeliveryStatus.DEACTIVATED,
        )

    if _contains(message, _CHAT_MISSING_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="chat_unavailable",
            retryable=False,
            delivery_status=TelegramDeliveryStatus.DEACTIVATED,
        )

    if _contains(message, _RIGHTS_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="insufficient_chat_rights",
            retryable=False,
            delivery_status=TelegramDeliveryStatus.SUSPENDED,
            notify_admin=True,
            log_level="error",
        )

    if _contains(message, _MESSAGE_FINAL_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="message_unavailable",
            retryable=False,
        )

    if class_name in {"TimedOut", "TimeoutError"}:
        pre_send = _cause_class_name(error) in _PRE_SEND_TIMEOUT_CAUSES
        return TelegramErrorDecision(
            kind=TelegramErrorKind.TEMPORARY,
            code="timeout_before_send" if pre_send else "timeout",
            retryable=pre_send,
            delivery_status=TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE,
            ambiguous_delivery=not pre_send,
        )

    if class_name in {"NetworkError", "ConnectError", "ReadError", "WriteError"}:
        ambiguous = class_name in {"ReadError", "WriteError"}
        return TelegramErrorDecision(
            kind=TelegramErrorKind.TEMPORARY,
            code="network_error",
            retryable=not ambiguous,
            delivery_status=TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE,
            ambiguous_delivery=ambiguous,
        )

    if _contains(message, _SERVER_PATTERNS):
        return TelegramErrorDecision(
            kind=TelegramErrorKind.TEMPORARY,
            code="telegram_server_error",
            retryable=True,
            delivery_status=TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE,
        )

    if class_name == "Forbidden":
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="telegram_forbidden",
            retryable=False,
            delivery_status=TelegramDeliveryStatus.SUSPENDED,
            notify_admin=True,
            log_level="error",
        )

    if class_name == "BadRequest":
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code="telegram_bad_request",
            retryable=False,
        )

    if class_name in {"InvalidToken", "Conflict", "EndPointNotFound"}:
        return TelegramErrorDecision(
            kind=TelegramErrorKind.PERMANENT,
            code=f"telegram_{class_name.lower()}",
            retryable=False,
            notify_admin=True,
            log_level="critical",
        )

    # Preserve a conservative temporary classification for unknown errors. The
    # explicit outbox worker still caps attempts and eventually dead-letters it.
    return TelegramErrorDecision(
        kind=TelegramErrorKind.TEMPORARY,
        code="unknown_temporary_error",
        retryable=True,
        delivery_status=TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE,
    )
