import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.fvg_lifecycle import (
    FvgLifecycleConfig,
    FvgLifecycleEventType,
    FvgLifecycleStatus,
    ZoneRelation,
    advance_zone,
    stable_fvg_id,
    zone_from_event,
)
from alerts.fvg_lifecycle_store import FvgLifecycleStore
from alerts.fvg_lifecycle_tracker import FvgLifecycleTracker
from alerts.fvg_models import Candle, FvgDirection, FvgEvent, FvgEventType, event_id
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc
BASE = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def make_event(
    *,
    event_type=FvgEventType.CONFIRMED_FVG,
    direction=FvgDirection.BULLISH,
    base=BASE,
):
    if direction == FvgDirection.BULLISH:
        lower, upper, signal = Decimal("100"), Decimal("105"), Decimal("110")
    else:
        lower, upper, signal = Decimal("100"), Decimal("105"), Decimal("95")
    return FvgEvent(
        event_id=event_id("BTCUSDT", "15m", direction, base, event_type),
        event_type=event_type,
        symbol="BTCUSDT",
        timeframe="15m",
        direction=direction,
        candle_a_open_time=base - timedelta(minutes=30),
        candle_b_open_time=base - timedelta(minutes=15),
        candle_c_open_time=base,
        candle_c_close_time=base + timedelta(minutes=15),
        zone_low=lower,
        zone_high=upper,
        zone_size=upper - lower,
        signal_price=signal,
        detected_at=base + timedelta(minutes=15),
        is_confirmed=event_type == FvgEventType.CONFIRMED_FVG,
        data_complete=True,
    )


def minute(index, *, high, low, close, symbol="BTCUSDT", base=BASE):
    opened = base + timedelta(minutes=15 + index)
    return Candle(
        symbol=symbol,
        timeframe="1m",
        open_time=opened,
        close_time=opened + timedelta(minutes=1),
        open=Decimal(str(close)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        is_closed=True,
        is_complete=True,
    )


class StableIdentityTests(unittest.TestCase):
    def test_pre_and_confirmed_forms_share_stable_zone_id(self):
        pre = make_event(event_type=FvgEventType.PRE_FVG)
        confirmed = make_event(event_type=FvgEventType.CONFIRMED_FVG)

        self.assertNotEqual(pre.event_id, confirmed.event_id)
        self.assertEqual(stable_fvg_id(pre), stable_fvg_id(confirmed))


class BullishLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.zone = zone_from_event(make_event())

    def test_detected_approaching_touch_and_fill_thresholds(self):
        approaching = advance_zone(
            self.zone,
            minute(1, high=111, low=107, close=108),
        )
        self.assertEqual(approaching.zone.status, FvgLifecycleStatus.APPROACHING)
        self.assertEqual(
            [event.event_type for event in approaching.events],
            [FvgLifecycleEventType.APPROACHED],
        )
        self.assertEqual(approaching.zone.last_relation, ZoneRelation.ABOVE)

        touched = advance_zone(
            approaching.zone,
            minute(2, high=108, low=104, close=104),
        )
        self.assertEqual(touched.zone.status, FvgLifecycleStatus.PARTIALLY_FILLED)
        self.assertEqual(touched.zone.touch_count, 1)
        self.assertEqual(touched.zone.max_fill_percent, Decimal("20.0"))
        self.assertEqual(touched.events[0].event_type, FvgLifecycleEventType.FIRST_TOUCH)
        self.assertEqual(touched.zone.first_touch_price, Decimal("105"))

        fifty = advance_zone(
            touched.zone,
            minute(3, high=108, low=102, close=104),
        )
        self.assertEqual(fifty.zone.max_fill_percent, Decimal("60.0"))
        self.assertEqual(
            [event.event_type for event in fifty.events],
            [FvgLifecycleEventType.FILL_25, FvgLifecycleEventType.FILL_50],
        )

        duplicate = advance_zone(
            fifty.zone,
            minute(3, high=108, low=102, close=104),
        )
        self.assertFalse(duplicate.changed)
        self.assertEqual(duplicate.events, ())

        no_repeat = advance_zone(
            fifty.zone,
            minute(4, high=107, low=102.2, close=104),
        )
        self.assertTrue(no_repeat.changed)
        self.assertEqual(no_repeat.events, ())

    def test_retouch_requires_exit_and_new_entry(self):
        first = advance_zone(
            self.zone,
            minute(1, high=108, low=104, close=104),
        )
        still_inside = advance_zone(
            first.zone,
            minute(2, high=105, low=103, close=104),
        )
        self.assertEqual(still_inside.zone.touch_count, 1)
        self.assertNotIn(
            FvgLifecycleEventType.RETOUCH,
            [event.event_type for event in still_inside.events],
        )

        exited = advance_zone(
            still_inside.zone,
            minute(3, high=108, low=106, close=107),
        )
        self.assertEqual(exited.zone.last_relation, ZoneRelation.ABOVE)

        retouched = advance_zone(
            exited.zone,
            minute(4, high=108, low=104, close=106),
        )
        self.assertEqual(retouched.zone.touch_count, 2)
        self.assertIn(
            FvgLifecycleEventType.RETOUCH,
            [event.event_type for event in retouched.events],
        )

    def test_wick_fill_and_close_through_have_different_final_states(self):
        wick_fill = advance_zone(
            self.zone,
            minute(1, high=108, low=99, close=101),
        )
        self.assertEqual(wick_fill.zone.status, FvgLifecycleStatus.FILLED)
        self.assertEqual(wick_fill.zone.max_fill_percent, Decimal("100"))
        self.assertIn(
            FvgLifecycleEventType.FILLED,
            [event.event_type for event in wick_fill.events],
        )

        close_on_far_edge = advance_zone(
            self.zone,
            minute(1, high=108, low=99, close=100),
        )
        self.assertEqual(close_on_far_edge.zone.status, FvgLifecycleStatus.FILLED)

        close_through = advance_zone(
            self.zone,
            minute(1, high=108, low=99, close=99),
        )
        self.assertEqual(close_through.zone.status, FvgLifecycleStatus.INVALIDATED)
        self.assertEqual(close_through.zone.max_fill_percent, Decimal("100"))
        event_types = [event.event_type for event in close_through.events]
        self.assertIn(FvgLifecycleEventType.FULLY_TRAVERSED, event_types)
        self.assertIn(FvgLifecycleEventType.INVALIDATED, event_types)
        self.assertNotIn(FvgLifecycleEventType.FILLED, event_types)

    def test_expiration_uses_zone_timeframe_bars_not_one_minute_updates(self):
        config = FvgLifecycleConfig(max_age_bars=2)
        early = advance_zone(
            self.zone,
            minute(1, high=120, low=115, close=117),
            config,
        )
        self.assertEqual(early.zone.processed_bars, 0)
        self.assertEqual(early.zone.status, FvgLifecycleStatus.DETECTED)

        expired = advance_zone(
            early.zone,
            minute(30, high=121, low=116, close=118),
            config,
        )
        self.assertEqual(expired.zone.processed_bars, 2)
        self.assertEqual(expired.zone.status, FvgLifecycleStatus.EXPIRED)
        self.assertEqual(expired.zone.expiration_reason, "max_age_bars")


class BearishLifecycleTests(unittest.TestCase):
    def test_bearish_fill_is_symmetric(self):
        zone = zone_from_event(make_event(direction=FvgDirection.BEARISH))
        touched = advance_zone(
            zone,
            minute(1, high=102, low=97, close=101),
        )
        self.assertEqual(touched.zone.touch_count, 1)
        self.assertEqual(touched.zone.max_fill_percent, Decimal("40.0"))
        self.assertEqual(touched.zone.first_touch_price, Decimal("100"))

        invalidated = advance_zone(
            touched.zone,
            minute(2, high=106, low=101, close=106),
        )
        self.assertEqual(invalidated.zone.status, FvgLifecycleStatus.INVALIDATED)
        self.assertEqual(invalidated.zone.invalidation_reason, "close_beyond_far_edge")


class LifecycleStoreTests(unittest.TestCase):
    def test_additive_tables_sync_restart_and_idempotency(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            event_store = FvgEventStore(path)
            event = make_event()
            self.assertTrue(event_store.record_event(event))

            store = FvgLifecycleStore(path)
            self.assertEqual(store.sync_confirmed_events(), 1)
            self.assertEqual(store.sync_confirmed_events(), 0)
            self.assertEqual(
                store.counts(),
                {"zones": 1, "active_zones": 1, "zone_events": 1},
            )

            zone = store.active_zones("BTCUSDT")[0]
            candle = minute(1, high=108, low=102, close=104)
            transitions = store.apply_candle(candle)
            self.assertEqual(len(transitions), 1)
            events_after_first = store.zone_events(zone.fvg_id)

            restarted = FvgLifecycleStore(path)
            self.assertEqual(restarted.apply_candle(candle), [])
            self.assertEqual(restarted.zone_events(zone.fvg_id), events_after_first)

            # A previous application version can still open and use its original
            # event tables because lifecycle migrations are additive only.
            rolled_back = FvgEventStore(path)
            self.assertFalse(rolled_back.record_event(event))
            with closing(sqlite3.connect(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertTrue({"events", "deliveries", "outbox"}.issubset(tables))
            self.assertTrue({"fvg_zones", "fvg_zone_events"}.issubset(tables))

    def test_tracker_replays_only_recent_unprocessed_cache_candles(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            recent_base = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(
                minutes=30
            )
            event_store = FvgEventStore(path)
            event_store.record_event(make_event(base=recent_base))
            tracker = FvgLifecycleTracker(
                store=FvgLifecycleStore(path),
                health_store=event_store,
            )
            self.assertEqual(tracker.sync_detected_events(), 1)

            candles = [
                minute(1, high=112, low=108, close=110, base=recent_base),
                minute(2, high=108, low=104, close=104, base=recent_base),
            ]
            first_events = tracker.observe_many(candles)
            second_events = tracker.observe_many(candles)

            self.assertGreater(first_events, 0)
            self.assertEqual(second_events, 0)
            self.assertEqual(tracker.counts()["zones"], 1)


if __name__ == "__main__":
    unittest.main()
