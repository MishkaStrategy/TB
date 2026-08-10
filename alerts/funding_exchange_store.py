"""Bounded per-user exchange selections and crossing state for funding alerts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from exchanges.funding import DEFAULT_EXCHANGE, normalize_exchange, normalize_exchanges

UTC = timezone.utc
CROSSING_RETENTION_DAYS = 7


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed connection, then always close it."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class FundingExchangeStore:
    DEFAULT_PATH = Path("data/funding_alerts.sqlite3")

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()

    def _connect(self):
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare(self):
        with self._connect() as connection:
            # WAL is persistent. Configure it once during store initialization
            # instead of reissuing a journal-mode transition on every read.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS funding_alert_exchange_selection (
                    chat_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    selected_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, exchange)
                );
                CREATE TABLE IF NOT EXISTS funding_alert_exchange_crossings (
                    chat_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    rate TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, exchange, symbol, direction)
                );
                CREATE INDEX IF NOT EXISTS idx_funding_exchange_crossings_seen
                    ON funding_alert_exchange_crossings(last_seen_at);
                """
            )
            migrated = (
                connection.execute(
                    "SELECT value FROM metadata WHERE key = 'multi_exchange_migrated'"
                ).fetchone()
                if self._table_exists(connection, "metadata")
                else None
            )
            if not migrated and self._table_exists(connection, "funding_alert_crossings"):
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(funding_alert_crossings)"
                    ).fetchall()
                }
                required = {
                    "chat_id",
                    "symbol",
                    "direction",
                    "rate",
                    "first_seen_at",
                    "last_seen_at",
                }
                if required <= columns:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO funding_alert_exchange_crossings(
                            chat_id, exchange, symbol, direction, rate,
                            first_seen_at, last_seen_at
                        )
                        SELECT chat_id, ?, symbol, direction, rate,
                               first_seen_at, last_seen_at
                        FROM funding_alert_crossings
                        """,
                        (DEFAULT_EXCHANGE,),
                    )
            if self._table_exists(connection, "metadata"):
                connection.execute(
                    """
                    INSERT INTO metadata(key, value)
                    VALUES ('multi_exchange_migrated', '1')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """
                )

    @staticmethod
    def _table_exists(connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def selected(self, chat_id: int) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT exchange FROM funding_alert_exchange_selection "
                "WHERE chat_id = ?",
                (str(chat_id),),
            ).fetchall()
        if not rows:
            return (DEFAULT_EXCHANGE,)
        try:
            return normalize_exchanges([row["exchange"] for row in rows])
        except ValueError:
            return (DEFAULT_EXCHANGE,)

    def set_selected(self, chat_id: int, exchanges, *, now: datetime | None = None):
        selected = normalize_exchanges(exchanges)
        timestamp = _iso(now or datetime.now(UTC))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM funding_alert_exchange_selection WHERE chat_id = ?",
                (str(chat_id),),
            )
            connection.executemany(
                """
                INSERT INTO funding_alert_exchange_selection(
                    chat_id, exchange, selected_at
                ) VALUES (?, ?, ?)
                """,
                [(str(chat_id), exchange, timestamp) for exchange in selected],
            )
            # Selection and threshold-crossing state are one logical update.
            # Clear crossings in the same transaction so a crash cannot leave
            # stale state attached to a newly selected exchange set.
            connection.execute(
                "DELETE FROM funding_alert_exchange_crossings WHERE chat_id = ?",
                (str(chat_id),),
            )
            connection.commit()
        return selected

    def toggle(self, chat_id: int, exchange: str, *, now: datetime | None = None):
        exchange = normalize_exchange(exchange)
        selected = set(self.selected(chat_id))
        if exchange in selected:
            if len(selected) == 1:
                raise ValueError("Нужно выбрать хотя бы одну биржу.")
            selected.remove(exchange)
        else:
            selected.add(exchange)
        return self.set_selected(chat_id, selected, now=now)

    def crossing_values(self, chat_id: int) -> dict[tuple[str, str, str], Decimal]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT exchange, symbol, direction, rate
                FROM funding_alert_exchange_crossings WHERE chat_id = ?
                """,
                (str(chat_id),),
            ).fetchall()
        return {
            (row["exchange"], row["symbol"], row["direction"]): Decimal(row["rate"])
            for row in rows
        }

    def replace_crossings(self, chat_id: int, crossings, *, now: datetime | None = None):
        timestamp = _iso(now or datetime.now(UTC))
        normalized = {
            (normalize_exchange(exchange), str(symbol), str(direction)): Decimal(str(rate))
            for (exchange, symbol, direction), rate in crossings.items()
        }
        with self._connect() as connection:
            previous = {
                (row["exchange"], row["symbol"], row["direction"]): row["first_seen_at"]
                for row in connection.execute(
                    """
                    SELECT exchange, symbol, direction, first_seen_at
                    FROM funding_alert_exchange_crossings WHERE chat_id = ?
                    """,
                    (str(chat_id),),
                ).fetchall()
            }
            connection.execute(
                "DELETE FROM funding_alert_exchange_crossings WHERE chat_id = ?",
                (str(chat_id),),
            )
            connection.executemany(
                """
                INSERT INTO funding_alert_exchange_crossings(
                    chat_id, exchange, symbol, direction, rate,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(chat_id),
                        exchange,
                        symbol,
                        direction,
                        str(rate),
                        previous.get((exchange, symbol, direction), timestamp),
                        timestamp,
                    )
                    for (exchange, symbol, direction), rate in normalized.items()
                ],
            )

    def clear_crossings(self, chat_id: int):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM funding_alert_exchange_crossings WHERE chat_id = ?",
                (str(chat_id),),
            )

    def cleanup(self, *, now: datetime | None = None):
        cutoff = _iso(
            (now or datetime.now(UTC)) - timedelta(days=CROSSING_RETENTION_DAYS)
        )
        with self._connect() as connection:
            crossings = connection.execute(
                "DELETE FROM funding_alert_exchange_crossings WHERE last_seen_at < ?",
                (cutoff,),
            ).rowcount
            if self._table_exists(connection, "funding_alert_settings"):
                selections = connection.execute(
                    """
                    DELETE FROM funding_alert_exchange_selection
                    WHERE chat_id NOT IN (
                        SELECT chat_id FROM funding_alert_settings
                    )
                    """
                ).rowcount
            else:
                selections = 0
        return {
            "crossings": max(crossings, 0),
            "selections": max(selections, 0),
        }
