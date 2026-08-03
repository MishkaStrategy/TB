"""Read-only watchdog for overdue or lease-expired background tasks."""

from __future__ import annotations

from datetime import datetime, timezone

from database.background_tasks import BackgroundTaskRegistry


UTC = timezone.utc


class BackgroundTaskWatchdog:
    """Evaluate task freshness without restarting or cancelling the process."""

    def __init__(
        self,
        registry: BackgroundTaskRegistry,
        *,
        metrics=None,
        stale_multiplier: float = 3.0,
        history_retention_days: int = 30,
    ):
        self.registry = registry
        self.metrics = metrics
        self.stale_multiplier = max(1.0, float(stale_multiplier))
        self.history_retention_days = max(1, int(history_retention_days))

    def _write_health(self, **values) -> None:
        method = getattr(self.metrics, "update_health", None)
        if callable(method):
            method(**values)

    def _increment(self, key: str, amount: int = 1) -> None:
        method = getattr(self.metrics, "increment_health", None)
        if callable(method):
            method(key, amount)

    def evaluate_once(self, *, now: datetime | None = None) -> dict:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)

        stale_recovered = self.registry.recover_stale(now=current)
        overdue = self.registry.overdue_tasks(
            stale_multiplier=self.stale_multiplier,
            now=current,
        )
        stale_states = [
            state
            for state in self.registry.states()
            if state["status"] == "stale"
        ]
        pruned = self.registry.prune_runs(
            retention_days=self.history_retention_days,
            now=current,
        )
        overdue_names = [item["task_name"] for item in overdue]
        stale_names = [item["task_name"] for item in stale_states]
        degraded = bool(overdue or stale_states)
        self._write_health(
            background_tasks_degraded=degraded,
            background_tasks_overdue_count=len(overdue),
            background_tasks_overdue_names=overdue_names,
            background_tasks_stale_count=len(stale_states),
            background_tasks_stale_names=stale_names,
            background_tasks_last_check=current.isoformat(),
            background_task_runs_pruned=pruned,
        )
        if stale_recovered:
            self._increment("background_task_stale_recoveries", stale_recovered)
        return {
            "checked_at": current.isoformat(),
            "degraded": degraded,
            "overdue_count": len(overdue),
            "overdue_tasks": overdue,
            "stale_count": len(stale_states),
            "stale_tasks": stale_states,
            "stale_recovered": stale_recovered,
            "pruned": pruned,
        }
