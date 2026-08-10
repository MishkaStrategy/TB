"""Persistent, bounded funding-rate notifications."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Awaitable, Callable


LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
DEFAULT_THRESHOLD = Decimal("0.1")
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 48
CROSSING_RETENTION_DAYS = 7
DISABLED_SETTINGS_RETENTION_DAYS = 180
CLEANUP_INTERVAL = timedelta(days=1)

_MIGRATION_LOCKS: dict[str, threading.Lock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> datetime:
    return datetime.now(UTC)


def next_hour_at_50(now: datetime | None = None) -> datetime:
    """Return the nearest future hourly control point at minute 50."""
    current = (now or utc_now()).astimezone(UTC)
    slot = current.replace(minute=50, second=0, microsecond=0)
    if slot <= current:
        slot += timedelta(hours=1)
    return slot


def parse_interval_hours(value) -> int:
    try:
        interval = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError("Частота должна быть целым числом от 1 до 48.") from error
    if not MIN_INTERVAL_HOURS <= interval <= MAX_INTERVAL_HOURS:
        raise ValueError("Частота должна быть целым числом от 1 до 48.")
    return interval


def parse_threshold(value) -> Decimal:
    normalized = str(value).strip().replace(",", ".").replace("%", "")
    try:
        threshold = Decimal(normalized)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Порог должен быть положительным числом, например 0,3.") from error
    if not threshold.is_finite() or threshold <= 0:
        raise ValueError("Порог должен быть положительным числом, например 0,3.")
    return threshold.normalize()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _default_settings(chat_id: int) -> dict:
    return {
        "chat_id": int(chat_id),
        "enabled": False,
        "interval_hours": 1,
        "threshold": DEFAULT_THRESHOLD,
        "notify_positive": True,
        "notify_negative": True,
        "next_check_at": None,
        "updated_at": None,
    }


class FundingAlertStore:
    """SQLite settings and crossing state with bounded retention."""

    DEFAULT_PATH = Path("data/funding_alerts.sqlite3")

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(self.path.resolve())
        with _MIGRATION_LOCKS_GUARD:
            lock = _MIGRATION_LOCKS.setdefault(resolved, threading.Lock())
        with lock:
            self._prepare_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare_database(self) -> None:
        is_new = not self.path.exists()
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            if is_new:
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS funding_alert_settings (
                    chat_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_hours INTEGER NOT NULL DEFAULT 1,
                    threshold TEXT NOT NULL DEFAULT '0.1',
                    notify_positive INTEGER NOT NULL DEFAULT 1,
                    notify_negative INTEGER NOT NULL DEFAULT 1,
                    next_check_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_funding_settings_due
                    ON funding_alert_settings(enabled, next_check_at);
                CREATE TABLE IF NOT EXISTS funding_alert_crossings (
                    chat_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    rate TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, symbol, direction),
                    FOREIGN KEY(chat_id) REFERENCES funding_alert_settings(chat_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_funding_crossings_seen
                    ON funding_alert_crossings(last_seen_at);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', '1')"
            )

    @staticmethod
    def _row_to_settings(row: sqlite3.Row) -> dict:
        return {
            "chat_id": int(row["chat_id"]),
            "enabled": bool(row["enabled"]),
            "interval_hours": int(row["interval_hours"]),
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
        return self._row_to_settings(row) if row else _default_settings(chat_id)

    def _upsert(
        self,
        chat_id: int,
        *,
        enabled: bool,
        interval_hours: int,
        threshold: Decimal,
        notify_positive: bool,
        notify_negative: bool,
        next_check_at: datetime | None,
        now: datetime,
    ) -> None:
        if not notify_positive and not notify_negative:
            raise ValueError("Нужно выбрать хотя бы одно направление фандинга.")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO funding_alert_settings(
                    chat_id, enabled, interval_hours, threshold,
                    notify_positive, notify_negative, next_check_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_hours = excluded.interval_hours,
                    threshold = excluded.threshold,
                    notify_positive = excluded.notify_positive,
                    notify_negative = excluded.notify_negative,
                    next_check_at = excluded.next_check_at,
                    updated_at = excluded.updated_at
                """,
                (
                    str(chat_id),
                    int(enabled),
                    parse_interval_hours(interval_hours),
                    str(parse_threshold(threshold)),
                    int(notify_positive),
                    int(notify_negative),
                    _iso(next_check_at) if next_check_at else None,
                    _iso(now),
                ),
            )

    def set_enabled(
        self,
        chat_id: int,
        enabled: bool,
        *,
        now: datetime | None = None,
    ) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._upsert(
            chat_id,
            enabled=bool(enabled),
            interval_hours=current["interval_hours"],
            threshold=current["threshold"],
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=next_hour_at_50(current_time) if enabled else None,
            now=current_time,
        )
        if not enabled:
            self.clear_crossings(chat_id)
        return self.user(chat_id)

    def set_interval(
        self,
        chat_id: int,
        interval_hours: int,
        *,
        now: datetime | None = None,
    ) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._upsert(
            chat_id,
            enabled=current["enabled"],
            interval_hours=parse_interval_hours(interval_hours),
            threshold=current["threshold"],
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=(
                next_hour_at_50(current_time) if current["enabled"] else None
            ),
            now=current_time,
        )
        return self.user(chat_id)

    def set_threshold(
        self,
        chat_id: int,
        threshold,
        *,
        now: datetime | None = None,
    ) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._upsert(
            chat_id,
            enabled=current["enabled"],
            interval_hours=current["interval_hours"],
            threshold=parse_threshold(threshold),
            notify_positive=current["notify_positive"],
            notify_negative=current["notify_negative"],
            next_check_at=(
                next_hour_at_50(current_time) if current["enabled"] else None
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
        now: datetime | None = None,
    ) -> dict:
        current = self.user(chat_id)
        current_time = (now or utc_now()).astimezone(UTC)
        self._upsert(
            chat_id,
            enabled=current["enabled"],
            interval_hours=current["interval_hours"],
            threshold=current["threshold"],
            notify_positive=notify_positive,
            notify_negative=notify_negative,
            next_check_at=(
                next_hour_at_50(current_time) if current["enabled"] else None
            ),
            now=current_time,
        )
        self.clear_crossings(chat_id)
        return self.user(chat_id)

    def due_users(self, now: datetime | None = None) -> list[dict]:
        current_time = (now or utc_now()).astimezone(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM funding_alert_settings
                WHERE enabled = 1
                  AND (next_check_at IS NULL OR next_check_at <= ?)
                ORDER BY next_check_at, chat_id
                """,
                (_iso(current_time),),
            ).fetchall()
        return [self._row_to_settings(row) for row in rows]

    def advance(self, chat_id: int, now: datetime | None = None) -> datetime:
        current_time = (now or utc_now()).astimezone(UTC)
        settings = self.user(chat_id)
        scheduled = settings["next_check_at"] or current_time.replace(
            minute=50, second=0, microsecond=0
        )
        next_check = scheduled
        step = timedelta(hours=settings["interval_hours"])
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

    def active_crossings(self, chat_id: int) -> set[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, direction
                FROM funding_alert_crossings
                WHERE chat_id = ?
                """,
                (str(chat_id),),
            ).fetchall()
        return {(row["symbol"], row["direction"]) for row in rows}

    def replace_crossings(
        self,
        chat_id: int,
        crossings: dict[tuple[str, str], Decimal],
        *,
        now: datetime | None = None,
    ) -> None:
        current_time = (now or utc_now()).astimezone(UTC)
        timestamp = _iso(current_time)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = {
                (row["symbol"], row["direction"]): row["first_seen_at"]
                for row in connection.execute(
                    """
                    SELECT symbol, direction, first_seen_at
                    FROM funding_alert_crossings WHERE chat_id = ?
                    """,
                    (str(chat_id),),
                ).fetchall()
            }
            connection.execute(
                "DELETE FROM funding_alert_crossings WHERE chat_id = ?",
                (str(chat_id),),
            )
            connection.executemany(
                """
                INSERT INTO funding_alert_crossings(
                    chat_id, symbol, direction, rate, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(chat_id),
                        symbol,
                        direction,
                        str(rate),
                        previous.get((symbol, direction), timestamp),
                        timestamp,
                    )
                    for (symbol, direction), rate in crossings.items()
                ],
            )
            connection.commit()

    def clear_crossings(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM funding_alert_crossings WHERE chat_id = ?",
                (str(chat_id),),
            )

    def cleanup(self, now: datetime | None = None, *, force: bool = False) -> dict:
        current_time = (now or utc_now()).astimezone(UTC)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'last_cleanup_at'"
            ).fetchone()
            last_cleanup = _parse_datetime(row["value"]) if row else None
            if not force and last_cleanup and current_time - last_cleanup < CLEANUP_INTERVAL:
                return {"settings": 0, "crossings": 0, "skipped": True}

            crossing_cutoff = _iso(
                current_time - timedelta(days=CROSSING_RETENTION_DAYS)
            )
            settings_cutoff = _iso(
                current_time - timedelta(days=DISABLED_SETTINGS_RETENTION_DAYS)
            )
            stale_crossings = connection.execute(
                "DELETE FROM funding_alert_crossings WHERE last_seen_at < ?",
                (crossing_cutoff,),
            ).rowcount
            stale_settings = connection.execute(
                """
                DELETE FROM funding_alert_settings
                WHERE enabled = 0 AND updated_at < ?
                """,
                (settings_cutoff,),
            ).rowcount
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('last_cleanup_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_iso(current_time),),
            )

        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA incremental_vacuum(200)")
        return {
            "settings": max(stale_settings, 0),
            "crossings": max(stale_crossings, 0),
            "skipped": False,
        }


def _funding_rate(item: dict) -> Decimal | None:
    for key in ("fundingRate", "funding_rate", "rate"):
        value = item.get(key)
        if value is None:
            continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed.is_finite():
            return parsed
    return None


def matching_crossings(
    rates: list[dict],
    settings: dict,
) -> dict[tuple[str, str], Decimal]:
    threshold = parse_threshold(settings["threshold"])
    matches: dict[tuple[str, str], Decimal] = {}
    for item in rates:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        rate = _funding_rate(item)
        if rate is None:
            continue
        symbol = str(item["symbol"])
        if settings["notify_positive"] and rate >= threshold:
            matches[(symbol, "positive")] = rate
        elif settings["notify_negative"] and rate <= -threshold:
            matches[(symbol, "negative")] = rate
    return matches


def _direction_label(settings: dict) -> str:
    if settings["notify_positive"] and settings["notify_negative"]:
        return "положительный и отрицательный"
    return "положительный" if settings["notify_positive"] else "отрицательный"


def format_funding_alert(
    settings: dict,
    crossings: dict[tuple[str, str], Decimal],
) -> list[str]:
    threshold = parse_threshold(settings["threshold"])
    header = (
        "🔔 <b>Фандинг пересёк заданный порог</b>\n"
        f"Порог: {threshold}%\n"
        f"Направление: {_direction_label(settings)}\n\n"
    )
    ordered = sorted(
        crossings.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    lines = []
    for (symbol, direction), rate in ordered:
        icon = "🟢" if direction == "positive" else "🔴"
        sign = "+" if rate > 0 else ""
        lines.append(f"{icon} <code>{escape(symbol[:24])}</code>: {sign}{rate:.4f}%")

    messages: list[str] = []
    current = header
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            messages.append(current.rstrip())
            current = "🔔 <b>Продолжение уведомления о фандинге</b>\n\n"
        current += line + "\n"
    if current.strip():
        messages.append(current.rstrip())
    return messages


class FundingAlertService:
    """Refresh funding once and deliver due per-user threshold crossings."""

    def __init__(
        self,
        store: FundingAlertStore | None = None,
        loader: Callable[[], Awaitable[list[dict]]] | None = None,
    ):
        self.store = store or FundingAlertStore()
        self.loader = loader

    async def _load_rates(self) -> list[dict]:
        if self.loader is not None:
            return await self.loader()
        from handlers.funding import load_funding_rates

        return await load_funding_rates()

    async def run(self, bot, *, now: datetime | None = None) -> list[dict] | None:
        current_time = (now or utc_now()).astimezone(UTC)
        await asyncio.to_thread(self.store.cleanup, current_time)
        try:
            rates = await self._load_rates()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Hourly Bitunix funding refresh failed")
            return None

        for settings in await asyncio.to_thread(self.store.due_users, current_time):
            chat_id = settings["chat_id"]
            try:
                current = matching_crossings(rates, settings)
                previous = await asyncio.to_thread(self.store.active_crossings, chat_id)
                fresh = {key: value for key, value in current.items() if key not in previous}
                for text in format_funding_alert(settings, fresh) if fresh else ():
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                await asyncio.to_thread(
                    self.store.replace_crossings,
                    chat_id,
                    current,
                    now=current_time,
                )
                await asyncio.to_thread(self.store.advance, chat_id, current_time)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Funding notification failed for chat_id=%s", chat_id)
        return rates
