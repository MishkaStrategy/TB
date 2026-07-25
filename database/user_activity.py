"""Persistent, privacy-minimal Telegram user activity tracking."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_LAST_TOUCH: dict[tuple[str, str], float] = {}


class UserActivityRegistry:
    WRITE_INTERVAL_SECONDS = 60

    def __init__(self, path="data/user_activity.json"):
        self.path = Path(path)
        self._resolved_path = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._resolved_path, threading.RLock())

    def touch(self, user):
        """Persist at most one activity update per user per minute."""
        user_id = str(user.id)
        throttle_key = (self._resolved_path, user_id)
        monotonic_now = time.monotonic()
        with self._lock:
            previous = _LAST_TOUCH.get(throttle_key)
            if (
                previous is not None
                and monotonic_now - previous < self.WRITE_INTERVAL_SECONDS
            ):
                return False

            data = self._read_unlocked()
            users = data.setdefault("users", {})
            record = users.get(user_id, {})
            now = datetime.now(timezone.utc).isoformat()
            users[user_id] = {
                "name": " ".join(
                    filter(None, [user.first_name, user.last_name])
                )
                or "Без имени",
                "username": user.username,
                "first_seen": record.get("first_seen", now),
                "last_seen": now,
                "visits": record.get("visits", 0) + 1,
            }
            self._write_unlocked(data)
            _LAST_TOUCH[throttle_key] = monotonic_now
            return True

    def users(self):
        with self._lock:
            return self._read_unlocked().get("users", {})

    def _read_unlocked(self):
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_unlocked(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(
            f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
