import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from alerts.process_watchdog import FvgProcessWatchdog, candle_silence_seconds


UTC = timezone.utc


class FakeSettings:
    def __init__(self, symbols=("BTCUSDT",)):
        self.symbols = set(symbols)

    def active_symbols(self):
        return frozenset(self.symbols)


class FakeEventStore:
    def __init__(self, health=None):
        self.health_value = dict(health or {})
        self.counters = {}
        self.updated = {}

    def health(self):
        return dict(self.health_value)

    def update_health(self, **values):
        self.updated.update(values)
        self.health_value.update(values)

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class CandleSilenceTests(unittest.TestCase):
    def test_uses_freshest_of_process_start_and_last_ws_message(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        now = started + timedelta(seconds=500)
        health = {
            "last_ws_message": (started + timedelta(seconds=200)).isoformat(),
        }

        self.assertEqual(
            candle_silence_seconds(health, watch_since=started, now=now),
            300,
        )

    def test_ignores_stale_timestamp_from_previous_process(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        health = {
            "last_ws_message": (started - timedelta(hours=1)).isoformat(),
        }

        self.assertEqual(
            candle_silence_seconds(
                health,
                watch_since=started,
                now=started + timedelta(seconds=100),
            ),
            100,
        )


class FvgProcessWatchdogTests(unittest.TestCase):
    def test_restarts_at_one_thousand_seconds_only_once(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        clock = MutableClock(started)
        event_store = FakeEventStore()
        exits = []
        watchdog = FvgProcessWatchdog(
            settings=FakeSettings(),
            event_store=event_store,
            stale_seconds=1000,
            restart_process=exits.append,
            restart_mode="test_callback",
            clock=clock,
        )

        clock.value = started + timedelta(seconds=999.999)
        self.assertAlmostEqual(watchdog.evaluate_once(), 999.999, places=3)
        self.assertEqual(exits, [])

        clock.value = started + timedelta(seconds=1000)
        self.assertEqual(watchdog.evaluate_once(), 1000)
        self.assertEqual(watchdog.evaluate_once(), 1000)
        self.assertEqual(exits, [1])
        self.assertTrue(watchdog.restart_requested)
        self.assertEqual(event_store.counters["stale_process_restarts"], 1)
        self.assertEqual(event_store.counters["stale_process_restart_requests"], 1)
        self.assertIn("1000 seconds", event_store.updated["last_error"])
        self.assertEqual(
            event_store.updated["process_restart_mode"],
            "test_callback",
        )
        self.assertEqual(
            event_store.updated["process_restart_silence_seconds"],
            1000,
        )
        self.assertIsNone(event_store.updated["process_restart_request_error"])

    def test_failed_restart_request_resets_latch_for_retry(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        clock = MutableClock(started + timedelta(seconds=1000))
        event_store = FakeEventStore()
        calls = []

        def restart(exit_code):
            calls.append(exit_code)
            if len(calls) == 1:
                raise OSError("signal failed")

        watchdog = FvgProcessWatchdog(
            settings=FakeSettings(),
            event_store=event_store,
            stale_seconds=1000,
            restart_process=restart,
            restart_mode="test_callback",
            clock=lambda: clock.value,
        )
        watchdog._watch_since = started

        with self.assertRaisesRegex(OSError, "signal failed"):
            watchdog.evaluate_once()
        self.assertFalse(watchdog.restart_requested)
        self.assertEqual(
            event_store.counters["process_restart_request_failures"],
            1,
        )
        self.assertIn(
            "signal failed",
            event_store.updated["process_restart_request_error"],
        )

        self.assertEqual(watchdog.evaluate_once(), 1000)
        self.assertTrue(watchdog.restart_requested)
        self.assertEqual(calls, [1, 1])
        self.assertIsNone(event_store.updated["process_restart_request_error"])

    def test_no_active_symbols_resets_the_watch_window(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        clock = MutableClock(started)
        settings = FakeSettings(symbols=())
        exits = []
        watchdog = FvgProcessWatchdog(
            settings=settings,
            event_store=FakeEventStore(),
            stale_seconds=1000,
            restart_process=exits.append,
            clock=clock,
        )

        clock.value = started + timedelta(seconds=5000)
        self.assertIsNone(watchdog.evaluate_once())
        settings.symbols.add("BTCUSDT")

        clock.value += timedelta(seconds=999)
        self.assertEqual(watchdog.evaluate_once(), 999)
        self.assertEqual(exits, [])

    def test_validates_thresholds(self):
        with self.assertRaisesRegex(ValueError, "stale_seconds"):
            FvgProcessWatchdog(
                settings=FakeSettings(),
                event_store=FakeEventStore(),
                stale_seconds=0,
            )
        with self.assertRaisesRegex(ValueError, "check_interval_seconds"):
            FvgProcessWatchdog(
                settings=FakeSettings(),
                event_store=FakeEventStore(),
                check_interval_seconds=0,
            )


class FvgProcessWatchdogRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_exits_after_successful_restart_request(self):
        started = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        calls = []
        watchdog = FvgProcessWatchdog(
            settings=FakeSettings(),
            event_store=FakeEventStore(),
            stale_seconds=1,
            check_interval_seconds=60,
            restart_process=calls.append,
            clock=lambda: started + timedelta(seconds=2),
        )
        watchdog._watch_since = started

        await asyncio.wait_for(watchdog.run(), timeout=1)

        self.assertEqual(calls, [1])
        self.assertTrue(watchdog.restart_requested)


if __name__ == "__main__":
    unittest.main()
