import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from mini_app_backend.diagnostics import collect_admin_diagnostics


UTC = timezone.utc


class FakeEventStore:
    def __init__(self, path):
        self.path = path

    def health(self):
        return {
            "ws_connected": True,
            "last_ws_message": datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            "last_rest_recovery": "2026-07-29T11:45:00+00:00",
            "last_error": "temporary failure",
            "outbox": 4,
            "deliveries": 120,
            "delivery_failures": 3,
            "delivery_retries": 8,
            "delivery_permanent_failures": 1,
        }


class MiniAppDiagnosticsTests(unittest.TestCase):
    def test_collects_health_storage_resources_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            event_path = data / "events.sqlite3"
            funding_path = data / "funding.sqlite3"
            for path in (event_path, funding_path):
                with closing(sqlite3.connect(path)) as connection:
                    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
            (data / "user_preferences.json").write_text("{}", encoding="utf-8")
            (data / "runtime_settings.json").write_text("{\"x\": true}", encoding="utf-8")
            (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
            (root / "BUILD_COMMIT").write_text("abc123\n", encoding="utf-8")

            result = collect_admin_diagnostics(
                funding_database_path=funding_path,
                event_store_provider=lambda: FakeEventStore(event_path),
                project_dir=root,
                data_dir=data,
            )

            self.assertEqual(result["websocket"], "connected")
            self.assertEqual(result["outbox"], 4)
            self.assertEqual(result["deliveries"], 120)
            self.assertEqual(result["deliveryPermanentFailures"], 1)
            self.assertEqual(result["fvgDatabaseStatus"], "ok")
            self.assertEqual(result["fundingDatabaseStatus"], "ok")
            self.assertGreater(result["fvgDatabaseBytes"], 0)
            self.assertGreater(result["jsonSettingsBytes"], 0)
            self.assertEqual(result["release"], "2.0.0")
            self.assertEqual(result["gitCommit"], "abc123")
            self.assertTrue(result["pythonVersion"])
            self.assertGreater(result["pid"], 0)
            self.assertGreaterEqual(result["processMemoryBytes"], 0)


if __name__ == "__main__":
    unittest.main()
