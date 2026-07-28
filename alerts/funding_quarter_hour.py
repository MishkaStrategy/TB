"""Quarter-hour funding notification schedules with a safe legacy migration."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from alerts.funding_alerts import FundingAlertStore as LegacyFundingAlertStore
from alerts.funding_alerts import parse_threshold, utc_now

UTC = timezone.utc
INTERVAL_STEP_MINUTES = 15
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 48 * 60
DEFAULT_INTERVAL_MINUTES = 60

_MIGRATION_LOCKS: dict[str, threading.Lock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _quarter_floor(value: datetime) -> datetime:
    current = value.astimezone(UTC)
    return current.replace(
        minute=(current.minute // INTERVAL_STEP_MINUTES) * INTERVAL_STEP_MINUTES,
        second=0,
        microsecond=0,
    )


def next_quarter_hour(now: datetime | None = None) -> datetime:
    """Return the nearest future UTC control point at :00, :15, :30 or :45."""
    current = (now or utc_now()).astimezone(UTC)
    slot = _quarter_floor(current)
    if slot <= current:
        slot += timedelta(minutes=INTERVAL_STEP_MINUTES)
    return slot


def parse_interval_minutes(value) -> int:
    """Parse a duration and require a 15-minute step up to 48 hours."""
    text = str(value).strip().lower().replace(" ", "").replace(",", ".")
    multiplier = Decimal("1")
    for suffix in (
        "минут",
        "минуты",
        "мин",
        "minutes",
        "minute",
        "mins",
        "min",
        "m",
        "м",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    else:
        for suffix in (
            "часов",
            "часа",
            "час",
            "hours",
            "hour",
            "hrs",
            "hr",
            "h",
            "ч",
        ):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                multiplier = Decimal("60")
                break
    try:
        minutes_decimal = Decimal(text) * multiplier
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            "Частота должна быть от 15 минут до 48 часов с шагом 15 минут."
        ) from error
    if (
        not minutes_decimal.is_finite()
        or minutes_decimal != minutes_decimal.to_integral_value()
    ):
        raise ValueError(
            "Частота должна быть от 15 минут до 48 часов с шагом 15 минут."
        )
    minutes = int(minutes_decimal)
    if (
        minutes < MIN_INTERVAL_MINUTES
        or minutes > MAX_INTERVAL_MINUTES
        or minutes % INTERVAL_STEP_MINUTES != 0
    ):
        raise ValueError(
            "Частота должна быть от 15 минут до 48 часов с шагом 15 минут."
        )
    return minutes


class FundingAlertStore(LegacyFundingAlertStore):
    """Funding settings stored in minutes while preserving legacy hourly rows."""

    def __init__(self, path=None):
        super().__init__(path)
        resolved = str(self.path.resolve())
        with _MIGRATION_LOCKS_GUARD:
            lock = _MIGRATION_LOCKS.setdefault(resolved, threading.Lock())
        with lock:
            self._prepare_interval_minutes()

    def _prepare_interval_minutes(self) -> None:
        with self._connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(funding_alert_settings)"
                ).fetchall()
            }
            if "interval_minutes" not in columns:
                connection.execute(
                    "ALTER TABLE funding_alert_settings "
                    "ADD COLUMN interval_minutes INTEGER NOT NULL DEFAULT 60"
                )
            migrated = connection.execute(
                "SELECT value FROM metadata "
                "WHERE key = 'funding_interval_minutes_migrated'"
            ).fetchone()
            if not migrated:
                connection.execute(
                    """
                    UPDATE funding_alert_settings
                    SET interval_minutes = CASE
                        WHEN interval_hours BETWEEN 1 AND 48 THEN interval_hours * 60
                        ELSE 60
                    END,
                    next_check_at = CASE WHEN enabled = 1 THEN NULL ELSE next_check_at END
                    """
                )
                connection.execute(
                    """
                    INSERT INTO metadata(key, value)
                    VALUES ('funding_interval_minutes_migrated', '1')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """
                )
            connection.execute(
                """
                INSERT INTO metadata(key, value)
                VALUES ('funding_schedule_schema_version', '2')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )

    @staticmethod
    def _row_to_settings(row: sqlite3.Row) -> dict:
        minutes = parse_interval_minutes(row["interval_minutes"])
        return {
            "chat_id": int(row["chat_id"]),
            "enabled": bool(row["enabled"]),
            "interval_minutes": minutes,
            "interval_hours": max(1, (minutes + 59) // 60),
            "threshold": parse_threshold(row["threshold"]),
            "notify_positive": bool(row["notify_positive"]),
            "notify_negative": bool(row["notify_negative"]),
            "next_check_at": _parse_datetime(row["next_check_at"]),
            "updated_at": _parse_datetime(row["updated_at"]),
        }

    def user(self, chat_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM funding_alert_settings WHERE chat_id = ?",
                (str(chat_id),),
            ).fetchone()
        if row:
            return self._row_to_settings(row)
        return {
            "chat_id": int(chat_id),
            "enabled": False,
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "interval_hours": 1,
            "threshold": Decimal("0.1"),
            "notify_positive": True,
            "notify_negative": True,
            "next_check_at": None,
            "updated_at": None,
        }

    def _save(
        self,
        chat_id: int,
        *,
        enabled: bool,
        interval_minutes: int,
        threshold,
        notify_positive: bool,
        notify_negative: bool,
        next_check_at: datetime | None,
        now: datetime,
    ) -> None:
        if not notify_positive and not notify_negative:
            raise ValueError("Нужно выбрать хотя бы одно направление фандинга.")
        minutes = parse_interval_minutes(interval_minutes)
        compatibility_hours = max(1, min(48, (minutes + 59) // 60))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO funding_alert_settings(
                    chat_id, enabled, interval_hours, interval_minutes, threshold,
                    notify_positive, notify_negative, next_check_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_hours = excluded.interval_hours,
                    interval_minutes = excluded.interval_minutes,
                    threshold = excluded.threshold,
                    notify_positive = excluded.notify_positive,
                    notify_negative = excluded.notify_negative,
                    next_check_at = excluded.next_check_at,
                    updated_at = excluded.updated_at
                """,
                (
                    str(chat_id),
                    int(enabled),
                    compatibility_hours,
                    minutes,
                    str(parse_threshold(threshold)),
                    int(notify_positive),
                    int(notify_negative),
                    _iso(next_check_at) if next_check_at else None,
                    _iso(now),
                ),
            )

    def set_enabled(self, chat_id: int, enabled: bool, *, now=None) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._save(
            chat_id,
            enabled=bool(enabled),
            interval_minutes=current["interval_minutes"],
            threshold=current["threshold"],
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=next_quarter_hour(current_time) if enabled else None,
            now=current_time,
        )
        if not enabled:
            self.clear_crossings(chat_id)
        return self.user(chat_id)

    def set_interval(self, chat_id: int, interval_minutes: int, *, now=None) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._save(
            chat_id,
            enabled=current["enabled"],
            interval_minutes=parse_interval_minutes(interval_minutes),
            threshold=current["threshold"],
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=(
                next_quarter_hour(current_time) if current["enabled"] else None
            ),
            now=current_time,
        )
        return self.user(chat_id)

    def set_threshold(self, chat_id: int, threshold, *, now=None) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._save(
            chat_id,
            enabled=current["enabled"],
            interval_minutes=current["interval_minutes"],
            threshold=parse_threshold(threshold),
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=(
                next_quarter_hour(current_time) if current["enabled"] else None
            ),
            now=current_time,
        )
        self.clear_crossings(chat_id)
        return self.user(chat_id)

    def set_directions(
        self,
        chat_id: int,
        *,
        notify_positive: bool,
        notify_negative: bool,
        now=None,
    ) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._save(
            chat_id,
            enabled=current["enabled"],
            interval_minutes=current["interval_minutes"],
            threshold=current["threshold"],
            notify_positive=notify_positive,
            notify_negative=notify_negative,
            next_check_at=(
                next_quarter_hour(current_time) if current["enabled"] else None
            ),
            now=current_time,
        )
        self.clear_crossings(chat_id)
        return self.user(chat_id)

    def advance(self, chat_id: int, now=None) -> datetime:
        current_time = (now or utc_now()).astimezone(UTC)
        settings = self.user(chat_id)
        next_check = settings["next_check_at"] or _quarter_floor(current_time)
        step = timedelta(minutes=settings["interval_minutes"])
        while next_check <= current_time:
            next_check += step
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE funding_alert_settings
                SET next_check_at = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (_iso(next_check), _iso(current_time), str(chat_id)),
            )
        return next_check
