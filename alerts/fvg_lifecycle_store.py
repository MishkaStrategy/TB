"""Additive SQLite persistence for the optional FVG lifecycle engine.

The store uses the existing FVG SQLite database but creates only new tables.
Older application versions ignore these tables, so disabling the feature flag or
rolling the code back does not require a destructive database downgrade.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from alerts.fvg_lifecycle import (
    FvgLifecycleConfig,
    FvgLifecycleEventType,
    FvgLifecycleStatus,
    FvgLifecycleTransition,
    FvgZoneEvent,
    FvgZoneState,
    ZoneRelation,
    advance_zone,
    detected_event,
    zone_from_event,
)
from alerts.fvg_models import Candle, FvgDirection, FvgEvent, FvgEventType


UTC = timezone.utc
LIFECYCLE_SCHEMA_VERSION = 1
ACTIVE_STATUS_VALUES = (
    FvgLifecycleStatus.DETECTED.value,
    FvgLifecycleStatus.APPROACHING.value,
    FvgLifecycleStatus.TOUCHED.value,
    FvgLifecycleStatus.PARTIALLY_FILLED.value,
)


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _event_from_payload(payload: dict) -> FvgEvent:
    return FvgEvent(
        event_id=str(payload["event_id"]),
        event_type=FvgEventType(str(payload["event_type"])),
        symbol=str(payload["symbol"]),
        timeframe=str(payload["timeframe"]),
        direction=FvgDirection(str(payload["direction"])),
        candle_a_open_time=_datetime(payload["candle_a_open_time"]),
        candle_b_open_time=_datetime(payload["candle_b_open_time"]),
        candle_c_open_time=_datetime(payload["candle_c_open_time"]),
        candle_c_close_time=_datetime(payload["candle_c_close_time"]),
        zone_low=Decimal(str(payload["zone_low"])),
        zone_high=Decimal(str(payload["zone_high"])),
        zone_size=Decimal(str(payload["zone_size"])),
        signal_price=Decimal(str(payload["signal_price"])),
        detected_at=_datetime(payload["detected_at"]),
        is_confirmed=bool(payload["is_confirmed"]),
        data_complete=bool(payload["data_complete"]),
    )


class FvgLifecycleStore:
    """Lifecycle repository that is safe to leave behind after a rollback."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

    ZONE_COLUMNS = (
        "fvg_id",
        "source_event_id",
        "exchange",
        "symbol",
        "timeframe",
        "direction",
        "lower_bound",
        "upper_bound",
        "formation_time",
        "formation_close_time",
        "signal_price",
        "status",
        "current_price",
        "current_fill_percent",
        "max_fill_percent",
        "fill_threshold_mask",
        "touch_count",
        "first_approach_at",
        "first_touch_at",
        "first_touch_price",
        "first_touch_candle_time",
        "first_touch_depth_percent",
        "filled_at",
        "invalidated_at",
        "invalidation_price",
        "invalidation_reason",
        "expired_at",
        "expiration_reason",
        "last_relation",
        "last_processed_candle",
        "processed_bars",
        "state_version",
        "lifecycle_version",
        "created_at",
        "updated_at",
    )

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fvg_lifecycle_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fvg_zones (
                    fvg_id TEXT PRIMARY KEY,
                    source_event_id TEXT NOT NULL UNIQUE,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    lower_bound TEXT NOT NULL,
                    upper_bound TEXT NOT NULL,
                    formation_time TEXT NOT NULL,
                    formation_close_time TEXT NOT NULL,
                    signal_price TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_price TEXT,
                    current_fill_percent TEXT NOT NULL,
                    max_fill_percent TEXT NOT NULL,
                    fill_threshold_mask INTEGER NOT NULL,
                    touch_count INTEGER NOT NULL,
                    first_approach_at TEXT,
                    first_touch_at TEXT,
                    first_touch_price TEXT,
                    first_touch_candle_time TEXT,
                    first_touch_depth_percent TEXT,
                    filled_at TEXT,
                    invalidated_at TEXT,
                    invalidation_price TEXT,
                    invalidation_reason TEXT,
                    expired_at TEXT,
                    expiration_reason TEXT,
                    last_relation TEXT NOT NULL,
                    last_processed_candle TEXT,
                    processed_bars INTEGER NOT NULL,
                    state_version INTEGER NOT NULL,
                    lifecycle_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(exchange, symbol, timeframe, direction, formation_time)
                );

                CREATE INDEX IF NOT EXISTS idx_fvg_zones_active_symbol
                    ON fvg_zones(status, symbol, formation_time);
                CREATE INDEX IF NOT EXISTS idx_fvg_zones_updated
                    ON fvg_zones(updated_at);

                CREATE TABLE IF NOT EXISTS fvg_zone_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    fvg_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    price TEXT,
                    fill_percent TEXT,
                    touch_count INTEGER,
                    candle_time TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(fvg_id) REFERENCES fvg_zones(fvg_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_fvg_zone_events_zone_time
                    ON fvg_zone_events(fvg_id, event_time, id);
                CREATE INDEX IF NOT EXISTS idx_fvg_zone_events_type_time
                    ON fvg_zone_events(event_type, event_time);
                """
            )
            connection.execute(
                """
                INSERT INTO fvg_lifecycle_metadata(key, value_json)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (_json(LIFECYCLE_SCHEMA_VERSION),),
            )

    @staticmethod
    def _zone_values(zone: FvgZoneState) -> dict:
        created_at = zone.created_at or _now()
        updated_at = zone.updated_at or created_at
        return {
            "fvg_id": zone.fvg_id,
            "source_event_id": zone.source_event_id,
            "exchange": zone.exchange,
            "symbol": zone.symbol,
            "timeframe": zone.timeframe,
            "direction": zone.direction.value,
            "lower_bound": str(zone.lower_bound),
            "upper_bound": str(zone.upper_bound),
            "formation_time": _iso(zone.formation_time),
            "formation_close_time": _iso(zone.formation_close_time),
            "signal_price": str(zone.signal_price),
            "status": zone.status.value,
            "current_price": str(zone.current_price) if zone.current_price is not None else None,
            "current_fill_percent": str(zone.current_fill_percent),
            "max_fill_percent": str(zone.max_fill_percent),
            "fill_threshold_mask": int(zone.fill_threshold_mask),
            "touch_count": int(zone.touch_count),
            "first_approach_at": _iso(zone.first_approach_at),
            "first_touch_at": _iso(zone.first_touch_at),
            "first_touch_price": str(zone.first_touch_price) if zone.first_touch_price is not None else None,
            "first_touch_candle_time": _iso(zone.first_touch_candle_time),
            "first_touch_depth_percent": (
                str(zone.first_touch_depth_percent)
                if zone.first_touch_depth_percent is not None
                else None
            ),
            "filled_at": _iso(zone.filled_at),
            "invalidated_at": _iso(zone.invalidated_at),
            "invalidation_price": (
                str(zone.invalidation_price)
                if zone.invalidation_price is not None
                else None
            ),
            "invalidation_reason": zone.invalidation_reason,
            "expired_at": _iso(zone.expired_at),
            "expiration_reason": zone.expiration_reason,
            "last_relation": zone.last_relation.value,
            "last_processed_candle": _iso(zone.last_processed_candle),
            "processed_bars": int(zone.processed_bars),
            "state_version": int(zone.state_version),
            "lifecycle_version": zone.lifecycle_version,
            "created_at": _iso(created_at),
            "updated_at": _iso(updated_at),
        }

    @staticmethod
    def _row_to_zone(row: sqlite3.Row) -> FvgZoneState:
        return FvgZoneState(
            fvg_id=row["fvg_id"],
            source_event_id=row["source_event_id"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            direction=FvgDirection(row["direction"]),
            lower_bound=Decimal(row["lower_bound"]),
            upper_bound=Decimal(row["upper_bound"]),
            formation_time=_datetime(row["formation_time"]),
            formation_close_time=_datetime(row["formation_close_time"]),
            signal_price=Decimal(row["signal_price"]),
            status=FvgLifecycleStatus(row["status"]),
            current_price=_decimal(row["current_price"]),
            current_fill_percent=Decimal(row["current_fill_percent"]),
            max_fill_percent=Decimal(row["max_fill_percent"]),
            fill_threshold_mask=int(row["fill_threshold_mask"]),
            touch_count=int(row["touch_count"]),
            first_approach_at=_datetime(row["first_approach_at"]),
            first_touch_at=_datetime(row["first_touch_at"]),
            first_touch_price=_decimal(row["first_touch_price"]),
            first_touch_candle_time=_datetime(row["first_touch_candle_time"]),
            first_touch_depth_percent=_decimal(row["first_touch_depth_percent"]),
            filled_at=_datetime(row["filled_at"]),
            invalidated_at=_datetime(row["invalidated_at"]),
            invalidation_price=_decimal(row["invalidation_price"]),
            invalidation_reason=row["invalidation_reason"],
            expired_at=_datetime(row["expired_at"]),
            expiration_reason=row["expiration_reason"],
            last_relation=ZoneRelation(row["last_relation"]),
            last_processed_candle=_datetime(row["last_processed_candle"]),
            processed_bars=int(row["processed_bars"]),
            state_version=int(row["state_version"]),
            lifecycle_version=row["lifecycle_version"],
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
        )

    @staticmethod
    def _insert_zone_event(
        connection: sqlite3.Connection,
        fvg_id: str,
        event: FvgZoneEvent,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO fvg_zone_events(
                event_key, fvg_id, event_type, event_time, price,
                fill_percent, touch_count, candle_time, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.dedupe_key(fvg_id),
                fvg_id,
                event.event_type.value,
                _iso(event.event_time),
                str(event.price) if event.price is not None else None,
                str(event.fill_percent) if event.fill_percent is not None else None,
                event.touch_count,
                _iso(event.candle_time),
                _json(event.payload or {}),
                _iso(_now()),
            ),
        )
        return cursor.rowcount == 1

    def register(self, event: FvgEvent, exchange: str = "bitunix") -> bool:
        if not event.is_confirmed or event.event_type is not FvgEventType.CONFIRMED_FVG:
            return False
        zone = zone_from_event(event, exchange)
        values = self._zone_values(zone)
        columns = ", ".join(self.ZONE_COLUMNS)
        placeholders = ", ".join(f":{column}" for column in self.ZONE_COLUMNS)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"INSERT OR IGNORE INTO fvg_zones({columns}) VALUES ({placeholders})",
                values,
            )
            created = cursor.rowcount == 1
            if created:
                self._insert_zone_event(connection, zone.fvg_id, detected_event(zone))
            connection.commit()
        return created

    def sync_confirmed_events(self, limit: int = 500) -> int:
        """Create missing zones from the existing immutable events table."""
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            table = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'events'
                """
            ).fetchone()
            if table is None:
                return 0
            rows = connection.execute(
                """
                SELECT event.payload_json
                FROM events AS event
                LEFT JOIN fvg_zones AS zone
                    ON zone.source_event_id = event.event_id
                WHERE event.event_type = 'CONFIRMED_FVG'
                  AND zone.fvg_id IS NULL
                ORDER BY event.detected_at, event.event_id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        created = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                event = _event_from_payload(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            created += int(self.register(event))
        return created

    def get_zone(self, fvg_id: str) -> FvgZoneState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fvg_zones WHERE fvg_id = ?",
                (fvg_id,),
            ).fetchone()
        return self._row_to_zone(row) if row is not None else None

    def active_zones(self, symbol: str | None = None) -> list[FvgZoneState]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUS_VALUES)
        parameters: list[object] = list(ACTIVE_STATUS_VALUES)
        where = f"status IN ({placeholders})"
        if symbol is not None:
            where += " AND symbol = ?"
            parameters.append(symbol.upper())
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM fvg_zones WHERE {where} ORDER BY formation_time, fvg_id",
                parameters,
            ).fetchall()
        return [self._row_to_zone(row) for row in rows]

    def active_symbols(self) -> frozenset[str]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUS_VALUES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT symbol
                FROM fvg_zones
                WHERE status IN ({placeholders})
                ORDER BY symbol
                """,
                ACTIVE_STATUS_VALUES,
            ).fetchall()
        return frozenset(row["symbol"] for row in rows)

    def _update_zone(self, connection: sqlite3.Connection, zone: FvgZoneState) -> None:
        values = self._zone_values(zone)
        assignments = ", ".join(
            f"{column} = :{column}"
            for column in self.ZONE_COLUMNS
            if column not in {"fvg_id", "created_at"}
        )
        connection.execute(
            f"UPDATE fvg_zones SET {assignments} WHERE fvg_id = :fvg_id",
            values,
        )

    def _apply_to_zone(
        self,
        fvg_id: str,
        candle: Candle,
        config: FvgLifecycleConfig,
    ) -> FvgLifecycleTransition | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fvg_zones WHERE fvg_id = ?",
                (fvg_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            current = self._row_to_zone(row)
            transition = advance_zone(current, candle, config)
            if not transition.changed:
                connection.rollback()
                return None
            self._update_zone(connection, transition.zone)
            for event in transition.events:
                self._insert_zone_event(connection, transition.zone.fvg_id, event)
            connection.commit()
            return transition

    def apply_candle(
        self,
        candle: Candle,
        config: FvgLifecycleConfig | None = None,
    ) -> list[FvgLifecycleTransition]:
        config = config or FvgLifecycleConfig()
        transitions = []
        for zone in self.active_zones(candle.symbol):
            transition = self._apply_to_zone(zone.fvg_id, candle, config)
            if transition is not None:
                transitions.append(transition)
        return transitions

    def zone_events(self, fvg_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, event_type, event_time, price, fill_percent,
                       touch_count, candle_time, payload_json
                FROM fvg_zone_events
                WHERE fvg_id = ?
                ORDER BY event_time, id
                """,
                (fvg_id,),
            ).fetchall()
        return [
            {
                **dict(row),
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def counts(self) -> dict:
        with self._connect() as connection:
            zones = int(connection.execute("SELECT COUNT(*) FROM fvg_zones").fetchone()[0])
            active = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM fvg_zones WHERE status IN ({','.join('?' for _ in ACTIVE_STATUS_VALUES)})",
                    ACTIVE_STATUS_VALUES,
                ).fetchone()[0]
            )
            events = int(connection.execute("SELECT COUNT(*) FROM fvg_zone_events").fetchone()[0])
        return {"zones": zones, "active_zones": active, "zone_events": events}
