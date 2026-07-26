import unittest

from alerts.fvg_stream import BitunixFvgStream


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

    def test_rejects_non_positive_watchdog_threshold(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            BitunixFvgStream(object(), kline_stale_seconds=0)


if __name__ == "__main__":
    unittest.main()
