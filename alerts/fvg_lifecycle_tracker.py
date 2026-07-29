"""Shadow-mode orchestration for persisted FVG lifecycle zones."""

from __future__ import annotations

from collections import defaultdict

from alerts.fvg_lifecycle import FvgLifecycleConfig, FvgLifecycleEventType
from alerts.fvg_lifecycle_store import FvgLifecycleStore
from alerts.fvg_models import Candle


class FvgLifecycleTracker:
    """Track confirmed FVG zones without changing user-visible notifications.

    The tracker is deliberately synchronous. Scheduler callers run its methods
    through ``asyncio.to_thread`` so SQLite work never blocks the Telegram event
    loop. All persistence is idempotent and survives process restarts.
    """

    def __init__(
        self,
        store: FvgLifecycleStore | None = None,
        config: FvgLifecycleConfig | None = None,
        health_store=None,
    ):
        self.store = store or FvgLifecycleStore()
        self.config = config or FvgLifecycleConfig()
        self.health_store = health_store
        self._active_symbols = set(self.store.active_symbols())

    def _increment(self, key: str, amount: int = 1) -> None:
        if self.health_store is None or not hasattr(self.health_store, "increment_health"):
            return
        self.health_store.increment_health(key, amount)

    def sync_detected_events(self, limit: int = 500) -> int:
        created = self.store.sync_confirmed_events(limit=limit)
        if created:
            self._increment("lifecycle_zones_created", created)
            self._active_symbols = set(self.store.active_symbols())
        return created

    def observe(self, candle: Candle) -> int:
        if candle.timeframe != "1m" or not candle.is_closed or not candle.is_complete:
            return 0
        transitions = self.store.apply_candle(candle, self.config)
        if not transitions:
            return 0

        event_count = sum(len(transition.events) for transition in transitions)
        self._increment("lifecycle_candles_processed")
        self._increment("lifecycle_transitions", len(transitions))
        self._increment("lifecycle_domain_events", event_count)

        for transition in transitions:
            for event in transition.events:
                if event.event_type is FvgLifecycleEventType.FILLED:
                    self._increment("lifecycle_filled")
                elif event.event_type is FvgLifecycleEventType.INVALIDATED:
                    self._increment("lifecycle_invalidated")
                elif event.event_type is FvgLifecycleEventType.EXPIRED:
                    self._increment("lifecycle_expired")

        if any(transition.zone.is_terminal for transition in transitions):
            self._active_symbols = set(self.store.active_symbols())
        return event_count

    def observe_many(self, candles) -> int:
        """Replay only candles newer than the oldest active-zone cursor."""
        grouped = defaultdict(list)
        for candle in candles:
            if candle.timeframe == "1m" and candle.is_closed and candle.is_complete:
                grouped[candle.symbol.upper()].append(candle)

        total = 0
        for symbol, items in grouped.items():
            zones = self.store.active_zones(symbol)
            if not zones:
                continue
            cutoff = min(
                zone.last_processed_candle or zone.formation_close_time
                for zone in zones
            )
            for candle in sorted(items, key=lambda item: item.open_time):
                if candle.open_time > cutoff:
                    total += self.observe(candle)
        return total

    def active_symbols(self) -> frozenset[str]:
        return frozenset(self._active_symbols)

    def counts(self) -> dict:
        return self.store.counts()
