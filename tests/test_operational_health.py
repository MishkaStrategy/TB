import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from alerts.health_monitor import HealthAlertMonitor
from alerts.scheduler import run_operational_health
from handlers.admin import format_bot_health


UTC = timezone.utc


class FakeEventStore:
    def __init__(self, path, health):
        self.path = Path(path)
        self._health = dict(health)
        self.increments = []
        self.updates = []

    def health(self):
        return dict(self._health)

    def increment_health(self, key, amount=1):
        self.increments.append((key, amount))

    def update_health(self, **values):
        self.updates.append(values)


class OperationalHealthTests(unittest.TestCase):
    def test_monitor_throttles_active_alert_and_reports_recovery(self):
        now = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        monitor = HealthAlertMonitor(
            stale_ws_seconds=180,
            outbox_threshold=100,
            cooldown_seconds=1800,
        )
        stale = {
            "ws_connected": True,
            "last_ws_message": (now - timedelta(minutes=5)).isoformat(),
            "outbox": 0,
        }

        first = monitor.evaluate(stale, now=now, has_active_symbols=True)
        second = monitor.evaluate(
            stale,
            now=now + timedelta(minutes=1),
            has_active_symbols=True,
        )
        recovered = monitor.evaluate(
            {
                **stale,
                "last_ws_message": (now + timedelta(minutes=2)).isoformat(),
            },
            now=now + timedelta(minutes=2),
            has_active_symbols=True,
        )

        self.assertEqual(len(first), 1)
        self.assertIn("не передавал свечи", first[0])
        self.assertEqual(second, [])
        self.assertEqual(len(recovered), 1)
        self.assertIn("восстановлено", recovered[0])

    def test_monitor_reports_counter_deltas_after_baseline(self):
        monitor = HealthAlertMonitor()
        now = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        baseline = {"recovery_failures": 2, "outbox": 0}
        self.assertEqual(
            monitor.evaluate(baseline, now=now, has_active_symbols=False),
            [],
        )
        alerts = monitor.evaluate(
            {"recovery_failures": 4, "outbox": 0},
            now=now + timedelta(minutes=1),
            has_active_symbols=False,
        )
        self.assertEqual(len(alerts), 1)
        self.assertIn("новых случаев: 2", alerts[0])

    def test_admin_health_contains_operational_state_and_database_size(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            path.write_bytes(b"x" * 2048)
            now = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
            store = FakeEventStore(
                path,
                {
                    "ws_connected": True,
                    "last_ws_message": (now - timedelta(seconds=20)).isoformat(),
                    "last_rest_recovery": now.isoformat(),
                    "events": 12,
                    "deliveries": 10,
                    "outbox": 2,
                    "delivery_failures": 1,
                    "delivery_retries": 3,
                },
            )
            text = format_bot_health(store, now=now)

        self.assertIn("Bitunix WebSocket: подключён", text)
        self.assertIn("20 сек. назад", text)
        self.assertIn("Событий в SQLite: 12", text)
        self.assertIn("Сообщений в outbox: 2", text)
        self.assertIn("2.0 КБ", text)


class OperationalHealthJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_sends_alert_to_each_admin(self):
        now = datetime.now(UTC)
        store = FakeEventStore(
            "/tmp/nonexistent-health.sqlite3",
            {
                "ws_connected": False,
                "last_ws_message": now.isoformat(),
                "outbox": 0,
            },
        )
        service = SimpleNamespace(
            event_store=store,
            settings=SimpleNamespace(active_symbols=lambda: {"BTCUSDT"}),
        )

        class Bot:
            def __init__(self):
                self.messages = []

            async def send_message(self, **kwargs):
                self.messages.append(kwargs)

        bot = Bot()
        context = SimpleNamespace(
            bot=bot,
            job=SimpleNamespace(
                data={
                    "fvg_service": service,
                    "health_monitor": HealthAlertMonitor(),
                }
            ),
        )
        with patch(
            "alerts.scheduler.ADMIN_TELEGRAM_IDS",
            frozenset({42, 43}),
        ):
            await run_operational_health(context)

        self.assertEqual(
            [item["chat_id"] for item in bot.messages],
            [42, 43],
        )
        self.assertTrue(
            all("WebSocket отключён" in item["text"] for item in bot.messages)
        )


if __name__ == "__main__":
    unittest.main()
