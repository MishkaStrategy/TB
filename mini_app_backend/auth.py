"""Telegram Mini App initData validation.

The implementation follows Telegram's documented HMAC-SHA-256 validation
scheme. Only the raw, verified initData string is accepted as an identity
source; values supplied by the request body are never trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import parse_qsl


class TelegramInitDataError(ValueError):
    """Raised when Telegram Mini App initData is absent, stale or invalid."""

    def __init__(self, message: str, *, code: str = "INVALID_INIT_DATA"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None

    @property
    def display_name(self) -> str:
        return " ".join(filter(None, (self.first_name, self.last_name))).strip() or str(self.id)


def _timestamp(value: datetime | int | float | None) -> int:
    if value is None:
        return int(datetime.now(timezone.utc).timestamp())
    if isinstance(value, datetime):
        return int(value.astimezone(timezone.utc).timestamp())
    return int(value)


def _single_value(pairs: list[tuple[str, str]], key: str) -> str:
    values = [value for item_key, value in pairs if item_key == key]
    if len(values) != 1:
        raise TelegramInitDataError(
            f"Telegram initData must contain exactly one {key} field.",
            code=f"INVALID_{key.upper()}",
        )
    return values[0]


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 3600,
    max_future_skew_seconds: int = 30,
    now: datetime | int | float | None = None,
    digest_factory: Callable = hashlib.sha256,
) -> TelegramUser:
    """Validate raw Telegram WebApp initData and return the verified user.

    Telegram specifies ``secret_key = HMAC_SHA256(bot_token, "WebAppData")``
    where ``WebAppData`` is the HMAC key and the bot token is the message.
    The received hash is then compared with an HMAC of the alphabetically
    sorted data-check-string using that secret key.
    """

    if not isinstance(init_data, str) or not init_data.strip():
        raise TelegramInitDataError(
            "Telegram initData is required.", code="MISSING_INIT_DATA"
        )
    if not isinstance(bot_token, str) or not bot_token:
        raise RuntimeError("TELEGRAM_TOKEN is required for Mini App authentication")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    if max_future_skew_seconds < 0:
        raise ValueError("max_future_skew_seconds must be non-negative")

    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=32,
        )
    except ValueError as error:
        raise TelegramInitDataError(
            "Telegram initData is malformed.", code="MALFORMED_INIT_DATA"
        ) from error

    if not pairs:
        raise TelegramInitDataError(
            "Telegram initData is empty.", code="MISSING_INIT_DATA"
        )

    received_hash = _single_value(pairs, "hash")
    if len(received_hash) != 64:
        raise TelegramInitDataError(
            "Telegram initData hash has an invalid format.", code="INVALID_HASH"
        )

    data_pairs = [(key, value) for key, value in pairs if key != "hash"]
    if len({key for key, _ in data_pairs}) != len(data_pairs):
        raise TelegramInitDataError(
            "Telegram initData contains duplicate fields.", code="DUPLICATE_FIELDS"
        )
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data_pairs)
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), digest_factory
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), digest_factory
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash.lower()):
        raise TelegramInitDataError(
            "Telegram initData signature is invalid.", code="INVALID_SIGNATURE"
        )

    auth_date_text = _single_value(pairs, "auth_date")
    try:
        auth_date = int(auth_date_text)
    except (TypeError, ValueError) as error:
        raise TelegramInitDataError(
            "Telegram auth_date is invalid.", code="INVALID_AUTH_DATE"
        ) from error

    current_timestamp = _timestamp(now)
    age = current_timestamp - auth_date
    if age < -max_future_skew_seconds:
        raise TelegramInitDataError(
            "Telegram initData has a future auth_date.", code="FUTURE_INIT_DATA"
        )
    if age > max_age_seconds:
        raise TelegramInitDataError(
            "Telegram initData has expired.", code="EXPIRED_INIT_DATA"
        )

    user_text = _single_value(pairs, "user")
    try:
        user_data = json.loads(user_text)
    except (TypeError, json.JSONDecodeError) as error:
        raise TelegramInitDataError(
            "Telegram user data is invalid.", code="INVALID_USER"
        ) from error
    if not isinstance(user_data, dict):
        raise TelegramInitDataError(
            "Telegram user data must be an object.", code="INVALID_USER"
        )

    try:
        user_id = int(user_data["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise TelegramInitDataError(
            "Telegram user id is missing or invalid.", code="INVALID_USER_ID"
        ) from error
    if user_id <= 0:
        raise TelegramInitDataError(
            "Telegram user id is invalid.", code="INVALID_USER_ID"
        )

    first_name = str(user_data.get("first_name") or "").strip()
    if not first_name:
        first_name = str(user_id)

    def optional_text(key: str) -> str | None:
        value = user_data.get(key)
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    return TelegramUser(
        id=user_id,
        first_name=first_name,
        last_name=optional_text("last_name"),
        username=optional_text("username"),
        language_code=optional_text("language_code"),
        photo_url=optional_text("photo_url"),
    )
