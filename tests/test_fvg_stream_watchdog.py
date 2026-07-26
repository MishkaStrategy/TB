import inspect
import unittest

from alerts.fvg_stream import BitunixFvgStream


class FakeEventStore:
    def __init__(self):
        self.counters = {}

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class FakeService:
    def __init__(self):
        self.event_store = FakeEventStore()


class BitunixFvgStreamWatchdogTests(unittest.TestCase):
    def test_allows_short_receive_gap(self):
        stream = BitunixFvgStream(object(), kline_stale_seconds=120)

        stream._raise_if_kline_stale(100.0, now=219.999)

    def test_forces_reconnect_at_stale_threshold(self):
        stream = BitunixFvgStream(object(), kline_stale_seconds=120)

        with self.assertRaisesRegex(
            ConnectionError,
            "no kline messages for 120 seconds",
        ):
            stream._raise_if_kline_stale(100.0, now=220.0)

    def test_production_gap_is_treated_as_stale(self):
        stream = BitunixFvgStream(object(), kline_stale_seconds=120)

        with self.assertRaisesRegex(
            ConnectionError,
            "no kline messages for 1072 seconds",
        ):
            stream._raise_if_kline_stale(100.0, now=1172.0)

    def test_watchdog_records_stale_reconnect(self):
        service = FakeService()
        stream = BitunixFvgStream(service, kline_stale_seconds=120)

        with self.assertRaises(ConnectionError):
            stream._check_kline_watchdog(100.0, now=220.0)

        self.assertEqual(service.event_store.counters["stale_ws_reconnects"], 1)

    def test_watchdog_runs_before_every_receive(self):
        source = inspect.getsource(BitunixFvgStream._run_market)

        self.assertLess(
            source.index("self._check_kline_watchdog(last_kline_at)"),
            source.index("await ws.receive(timeout=5)"),
        )

    def test_rejects_non_positive_watchdog_threshold(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            BitunixFvgStream(object(), kline_stale_seconds=0)


if __name__ == "__main__":
    unittest.main()
