import asyncio
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alerts.funding_alerts import FundingAlertStore as LegacyFundingAlertStore
from alerts.funding_quarter_hour import (
    FundingAlertStore,
    next_quarter_hour,
    parse_interval_minutes,
)
from alerts.funding_snapshot_store import FundingSnapshotStore

UTC = timezone.utc


class FakeBot:
    async def send_message(self, **kwargs):
        return kwargs


class FundingStorageStdlibTests(unittest.TestCase):
    def test_quarter_hour_parser_and_legacy_migration(self):
        self.assertEqual(parse_interval_minutes("15"), 15)
        self.assertEqual(parse_interval_minutes("1,5ч"), 90)
        self.assertEqual(
            next_quarter_hour(datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
            datetime(2026, 7, 28, 14, 30, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            now = datetime(2026, 7, 28, 14, 1, tzinfo=UTC)
            legacy = LegacyFundingAlertStore(path)
            legacy.set_interval(10, 4, now=now)
            legacy.set_enabled(10, True, now=now)

            store = FundingAlertStore(path)
            settings = store.user(10)
            self.assertEqual(settings["interval_minutes"], 240)
            self.assertIsNone(settings["next_check_at"])

            store.set_interval(10, 45, now=now)
            self.assertEqual(store.user(10)["interval_minutes"], 45)
            self.assertEqual(
                store.advance(10, datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
                datetime(2026, 7, 28, 15, 0, tzinfo=UTC),
            )

    def test_history_keeps_three_rows_and_checkpoints_wal(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            store = FundingSnapshotStore(path)
            for minute in (0, 15, 30, 45):
                store.save(
                    {
                        "binance": [
                            {
                                "symbol": "BTCUSDT",
                                "fundingRate": str(minute / 1000),
                            }
                        ],
                        "bingx": [],
                    },
                    captured_at=datetime(2026, 7, 28, 14, minute, tzinfo=UTC),
                )

            self.assertEqual(store.count(), 3)
            self.assertEqual(
                [item["captured_at"].minute for item in store.latest()],
                [45, 30, 15],
            )
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM funding_snapshot_history"
                    ).fetchone()[0],
                    3,
                )
            wal_path = Path(f"{path}-wal")
            self.assertTrue(not wal_path.exists() or wal_path.stat().st_size == 0)

    def test_scheduled_service_saves_only_three_downloads(self):
        module_names = (
            "exchanges.funding",
            "alerts.funding_exchange_store",
            "alerts.multi_funding_alerts",
        )
        previous = {name: sys.modules.get(name) for name in module_names}
        for name in module_names:
            sys.modules.pop(name, None)

        funding_stub = types.ModuleType("exchanges.funding")
        funding_stub.DEFAULT_EXCHANGE = "bitunix"
        funding_stub.EXCHANGE_LABELS = {
            "bitunix": "Bitunix",
            "binance": "Binance",
        }

        def normalize_exchange(value):
            exchange = str(value or "bitunix").strip().lower()
            if exchange not in funding_stub.EXCHANGE_LABELS:
                raise ValueError(exchange)
            return exchange

        def normalize_exchanges(values):
            if values is None:
                values = ("bitunix",)
            selected = {normalize_exchange(value) for value in values}
            ordered = tuple(
                value
                for value in ("bitunix", "binance")
                if value in selected
            )
            if not ordered:
                raise ValueError("empty")
            return ordered

        funding_stub.normalize_exchange = normalize_exchange
        funding_stub.normalize_exchanges = normalize_exchanges
        funding_stub.exchange_label = lambda value: funding_stub.EXCHANGE_LABELS[
            normalize_exchange(value)
        ]
        sys.modules["exchanges.funding"] = funding_stub

        try:
            from alerts.multi_funding_alerts import MultiFundingAlertService

            async def scenario():
                with tempfile.TemporaryDirectory() as tempdir:
                    path = Path(tempdir) / "funding.sqlite3"
                    settings = FundingAlertStore(path)
                    history = FundingSnapshotStore(path)
                    calls = 0

                    async def loader():
                        nonlocal calls
                        calls += 1
                        return {
                            "binance": [
                                {
                                    "symbol": "BTCUSDT",
                                    "fundingRate": str(calls / 100),
                                }
                            ]
                        }

                    service = MultiFundingAlertService(
                        settings_store=settings,
                        snapshot_store=history,
                        loader=loader,
                    )
                    for minute in (0, 15, 30, 45):
                        await service.run(
                            FakeBot(),
                            now=datetime(2026, 7, 28, 14, minute, tzinfo=UTC),
                        )
                    self.assertEqual(calls, 4)
                    self.assertEqual(history.count(), 3)
                    self.assertEqual(
                        [item["captured_at"].minute for item in history.latest()],
                        [45, 30, 15],
                    )

            asyncio.run(scenario())
        finally:
            for name in module_names:
                sys.modules.pop(name, None)
                if previous[name] is not None:
                    sys.modules[name] = previous[name]


if __name__ == "__main__":
    unittest.main()
