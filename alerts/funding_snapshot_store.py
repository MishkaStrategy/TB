"""Compressed, bounded history for scheduled multi-exchange funding snapshots."""

from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
MAX_SNAPSHOTS = 3


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class FundingSnapshotStore:
    """Keep only the three most recent full-market snapshots in SQLite."""

    DEFAULT_PATH = Path("data/funding_alerts.sqlite3")

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare(self):
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS funding_snapshot_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL UNIQUE,
                    exchange_count INTEGER NOT NULL,
                    rate_count INTEGER NOT NULL,
                    compressed_bytes INTEGER NOT NULL,
                    payload_zlib BLOB NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_funding_snapshot_captured
                ON funding_snapshot_history(captured_at DESC)
                """
            )
            self._prune(connection)
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _rate_count(snapshot) -> int:
        return sum(
            len(rates)
            for rates in snapshot.values()
            if isinstance(rates, list)
        )

    @staticmethod
    def _encode(snapshot) -> bytes:
        payload = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return zlib.compress(payload, level=6)

    @staticmethod
    def _decode(payload: bytes):
        return json.loads(zlib.decompress(payload).decode("utf-8"))

    @staticmethod
    def _prune(connection) -> int:
        cursor = connection.execute(
            """
            DELETE FROM funding_snapshot_history
            WHERE id NOT IN (
                SELECT id FROM funding_snapshot_history
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
            )
            """,
            (MAX_SNAPSHOTS,),
        )
        return max(cursor.rowcount, 0)

    def _checkpoint(self) -> None:
        """Prevent the WAL from accumulating deleted snapshot pages between cleanups."""
        connection = self._connect()
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()

    def save(self, snapshot, *, captured_at: datetime) -> dict:
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("Funding snapshot must be a non-empty dictionary.")
        timestamp = _iso(captured_at)
        payload = self._encode(snapshot)
        exchange_count = sum(
            1 for rates in snapshot.values() if isinstance(rates, list)
        )
        rate_count = self._rate_count(snapshot)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO funding_snapshot_history(
                    captured_at, exchange_count, rate_count,
                    compressed_bytes, payload_zlib
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(captured_at) DO UPDATE SET
                    exchange_count = excluded.exchange_count,
                    rate_count = excluded.rate_count,
                    compressed_bytes = excluded.compressed_bytes,
                    payload_zlib = excluded.payload_zlib
                """,
                (
                    timestamp,
                    exchange_count,
                    rate_count,
                    len(payload),
                    sqlite3.Binary(payload),
                ),
            )
            pruned = self._prune(connection)
            connection.commit()
        finally:
            connection.close()
        self._checkpoint()
        return {
            "captured_at": captured_at.astimezone(UTC),
            "exchange_count": exchange_count,
            "rate_count": rate_count,
            "compressed_bytes": len(payload),
            "pruned": pruned,
        }

    def latest(self, limit: int = MAX_SNAPSHOTS) -> list[dict]:
        bounded_limit = max(1, min(int(limit), MAX_SNAPSHOTS))
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT captured_at, exchange_count, rate_count,
                       compressed_bytes, payload_zlib
                FROM funding_snapshot_history
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "captured_at": datetime.fromisoformat(row["captured_at"]).astimezone(UTC),
                "exchange_count": int(row["exchange_count"]),
                "rate_count": int(row["rate_count"]),
                "compressed_bytes": int(row["compressed_bytes"]),
                "snapshot": self._decode(row["payload_zlib"]),
            }
            for row in rows
        ]

    def count(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM funding_snapshot_history"
            ).fetchone()
            return int(row["total"])
        finally:
            connection.close()
