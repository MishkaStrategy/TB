"""Operational health alert evaluation with cooldown and recovery notices."""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except (TypeError, ValueError):
        return None


class HealthAlertMonitor:
    """Turn persisted health metrics into low-noise administrator alerts."""

    COUNTERS = {
        "recovery_failures": "ошибка REST-восстановления Bitunix",
        "control_point_failures": "ошибка контрольной проверки FVG",
        "delivery_retry_job_failures": "ошибка фоновой обработки Telegram outbox",
    }

    def __init__(
        self,
        *,
        stale_ws_seconds: float = 180,
        outbox_threshold: int = 100,
        cooldown_seconds: float = 1800,
    ):
        self.stale_ws_seconds = float(stale_ws_seconds)
        self.outbox_threshold = int(outbox_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self._active: dict[str, str] = {}
        self._last_sent: dict[str, datetime] = {}
        self._last_counters: dict[str, int] | None = None

    def evaluate(
        self,
        health: dict,
        *,
        now: datetime | None = None,
        has_active_symbols: bool = True,
    ) -> list[str]:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        conditions: dict[str, str] = {}

        if has_active_symbols:
            if health.get("ws_connected") is False:
                conditions["ws"] = "Bitunix WebSocket отключён"
            else:
                last_ws = _parse_time(health.get("last_ws_message"))
                if last_ws is not None:
                    age = max(0, int((now - last_ws).total_seconds()))
                    if age >= self.stale_ws_seconds:
                        conditions["ws"] = (
                            f"Bitunix WebSocket не передавал свечи {age} сек."
                        )

        outbox = int(health.get("outbox") or 0)
        if outbox >= self.outbox_threshold:
            conditions["outbox"] = (
                f"Telegram outbox вырос до {outbox} сообщений "
                f"(порог {self.outbox_threshold})"
            )

        alerts: list[str] = []
        previous_active = dict(self._active)

        for key, message in conditions.items():
            last_sent = self._last_sent.get(key)
            if (
                key not in previous_active
                or last_sent is None
                or (now - last_sent).total_seconds() >= self.cooldown_seconds
            ):
                alerts.append(f"⚠️ FVG Alert Bot: {message}")
                self._last_sent[key] = now

        for key, old_message in previous_active.items():
            if key not in conditions:
                alerts.append(f"✅ FVG Alert Bot: восстановлено — {old_message}")
                self._last_sent.pop(key, None)

        counters = {
            key: int(health.get(key) or 0)
            for key in self.COUNTERS
        }
        if self._last_counters is not None:
            for key, label in self.COUNTERS.items():
                delta = counters[key] - self._last_counters.get(key, 0)
                if delta > 0:
                    alerts.append(
                        f"⚠️ FVG Alert Bot: {label}; новых случаев: {delta}"
                    )
        self._last_counters = counters
        self._active = conditions
        return alerts
