import unittest
from datetime import datetime, timedelta, timezone

from alerts.process_watchdog import FvgProcessWatchdog


UTC = timezone.utc


class Settings:
    def active_symbols(self):
        return frozenset({"BTCUSDT"})


class EventStore:
    def __init__(self):
        self.values = {}
        self.counters = {}

    def health(self):
        return dict(self.values)

    def update_health(self, **values):
        self.values.update(values)

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class Guard:
    def __init__(self, decisions=None, error=None):
        self.decisions = list(decisions or [])
        self.error = error
        self.calls = []
        self.failed = []

    def decide(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.decisions.pop(0)

    def mark_failed(self, request_id, error, *, now=None):
        self.failed.append((request_id, error, now))
        return True


class ProcessWatchdogGuardTests(unittest.TestCase):
    def test_guard_denial_suppresses_signal_and_local_block_avoids_spam(self):
        started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        blocked_until = started + timedelta(seconds=2000)
        clock = Clock(started + timedelta(seconds=1000))
        guard = Guard(
            [
                {
                    "allowed": False,
                    "request_id": "blocked-request",
                    "decision_reason": "limit_reached",
                    "blocked_until": blocked_until.isoformat(),
                    "requests_in_window": 3,
                }
            ]
        )
        event_store = EventStore()
        restarts = []
        watchdog = FvgProcessWatchdog(
            settings=Settings(),
            event_store=event_store,
            stale_seconds=1000,
            restart_process=restarts.append,
            restart_guard=guard,
            clock=clock,
        )
        watchdog._watch_since = started

        self.assertEqual(watchdog.evaluate_once(), 1000)
        clock.value = started + timedelta(seconds=1001)
        self.assertEqual(watchdog.evaluate_once(), 1001)

        self.assertEqual(restarts, [])
        self.assertEqual(len(guard.calls), 1)
        self.assertEqual(
            event_store.counters["process_restart_guard_suppressions"],
            1,
        )
        self.assertTrue(event_store.values["process_restart_guard_blocked"])
        self.assertEqual(
            event_store.values["process_restart_guard_reason"],
            "limit_reached",
        )
        self.assertEqual(
            event_store.values["process_restart_guard_requests_in_window"],
            3,
        )

    def test_guard_error_fails_closed_and_retries_after_local_delay(self):
        started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        clock = Clock(started + timedelta(seconds=1000))
        guard = Guard(error=RuntimeError("guard database locked"))
        event_store = EventStore()
        restarts = []
        watchdog = FvgProcessWatchdog(
            settings=Settings(),
            event_store=event_store,
            stale_seconds=1000,
            check_interval_seconds=30,
            restart_process=restarts.append,
            restart_guard=guard,
            clock=clock,
        )
        watchdog._watch_since = started

        watchdog.evaluate_once()
        clock.value += timedelta(seconds=1)
        watchdog.evaluate_once()

        self.assertEqual(restarts, [])
        self.assertEqual(len(guard.calls), 1)
        self.assertEqual(event_store.counters["process_restart_guard_failures"], 1)
        self.assertEqual(
            event_store.counters["process_restart_guard_suppressions"],
            1,
        )
        self.assertIn(
            "guard database locked",
            event_store.values["process_restart_guard_error"],
        )
        self.assertEqual(
            event_store.values["process_restart_guard_reason"],
            "guard_error",
        )

    def test_allowed_request_calls_restart_and_records_guard_request(self):
        started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        clock = Clock(started + timedelta(seconds=1000))
        guard = Guard(
            [
                {
                    "allowed": True,
                    "request_id": "request-1",
                    "decision_reason": "allowed",
                    "blocked_until": None,
                    "requests_in_window": 1,
                }
            ]
        )
        event_store = EventStore()
        restarts = []
        watchdog = FvgProcessWatchdog(
            settings=Settings(),
            event_store=event_store,
            stale_seconds=1000,
            restart_process=restarts.append,
            restart_mode="test",
            restart_guard=guard,
            clock=clock,
        )
        watchdog._watch_since = started

        watchdog.evaluate_once()

        self.assertEqual(restarts, [1])
        self.assertTrue(watchdog.restart_requested)
        self.assertEqual(
            event_store.values["process_restart_guard_request_id"],
            "request-1",
        )
        self.assertFalse(event_store.values["process_restart_guard_blocked"])
        self.assertEqual(event_store.values["process_restart_mode"], "test")

    def test_restart_callback_failure_marks_guard_request_failed(self):
        started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        clock = Clock(started + timedelta(seconds=1000))
        guard = Guard(
            [
                {
                    "allowed": True,
                    "request_id": "request-failed",
                    "decision_reason": "allowed",
                    "blocked_until": None,
                    "requests_in_window": 1,
                }
            ]
        )
        event_store = EventStore()

        def restart(exit_code):
            del exit_code
            raise OSError("signal denied")

        watchdog = FvgProcessWatchdog(
            settings=Settings(),
            event_store=event_store,
            stale_seconds=1000,
            restart_process=restart,
            restart_guard=guard,
            clock=clock,
        )
        watchdog._watch_since = started

        with self.assertRaisesRegex(OSError, "signal denied"):
            watchdog.evaluate_once()

        self.assertFalse(watchdog.restart_requested)
        self.assertEqual(len(guard.failed), 1)
        request_id, error, failed_at = guard.failed[0]
        self.assertEqual(request_id, "request-failed")
        self.assertIsInstance(error, OSError)
        self.assertEqual(failed_at, clock.value)


if __name__ == "__main__":
    unittest.main()
