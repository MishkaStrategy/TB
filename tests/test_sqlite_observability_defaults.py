import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import config
from database.sqlite_observability import SQLiteSnapshotCollector


class SQLiteObservabilityDefaultsTests(unittest.TestCase):
    def test_scheduled_defaults_are_disabled_and_low_cost(self):
        self.assertFalse(config.DATABASE_OBSERVABILITY_ENABLED)
        self.assertFalse(config.DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED)
        self.assertFalse(config.DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED)
        self.assertEqual(config.DATABASE_OBSERVABILITY_INTERVAL_SECONDS, 3600)
        self.assertEqual(config.DATABASE_OBSERVABILITY_RETENTION_DAYS, 90)

    def test_default_collector_skips_row_counts_and_quick_check(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "target.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
                connection.executemany(
                    "INSERT INTO items DEFAULT VALUES",
                    [() for _ in range(3)],
                )
                connection.commit()

            result = SQLiteSnapshotCollector().collect("target", path)
            objects = {item["object_name"]: item for item in result["objects"]}

            self.assertTrue(result["available"])
            self.assertIsNone(result["quick_check"])
            self.assertIn("items", objects)
            self.assertIsNone(objects["items"]["row_count"])


if __name__ == "__main__":
    unittest.main()
