import inspect
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from alerts.funding_alerts import FundingAlertStore
from alerts.sqlite_event_store import FvgEventStore


class SQLiteWalInitializationTests(unittest.TestCase):
    def test_event_store_configures_wal_once_during_prepare(self):
        self.assertNotIn("journal_mode", inspect.getsource(FvgEventStore._connect))
        self.assertIn("journal_mode", inspect.getsource(FvgEventStore._prepare_database))
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "events.sqlite3"
            FvgEventStore(path, legacy_json_path=None)
            with closing(sqlite3.connect(path)) as connection:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")

    def test_funding_store_configures_wal_once_during_prepare(self):
        self.assertNotIn("journal_mode", inspect.getsource(FundingAlertStore._connect))
        self.assertIn("journal_mode", inspect.getsource(FundingAlertStore._prepare_database))
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            FundingAlertStore(path)
            with closing(sqlite3.connect(path)) as connection:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")


if __name__ == "__main__":
    unittest.main()
