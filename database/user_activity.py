"""Persistent, privacy-minimal Telegram user activity tracking."""

import json
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_LAST_TOUCH: dict[tuple[str, str], float] = {}
_CACHE: dict[str, dict] = {}


class UserActivityRegistry:
    WRITE_INTERVAL_SECONDS = 60

    def __init__(self, path="data/user_activity.json"):
        self.path = Path(path)
        self._resolved_path = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._resolved_path, threading.RLock())

    def touch(self, user):
        """Count every interaction, but flush each user at most once per minute."""
        user_id = str(user.id)
        throttle_key = (self._resolved_path, user_id)
        monotonic_now = time.monotonic()
        with self._lock:
            data = self._load_unlocked()
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

            previous = _LAST_TOUCH.get(throttle_key)
            should_flush = (
                previous is None
                or monotonic_now - previous >= self.WRITE_INTERVAL_SECONDS
            )
            if should_flush:
                self._write_unlocked(data)
                _LAST_TOUCH[throttle_key] = monotonic_now
            return should_flush

    def users(self):
        with self._lock:
            return deepcopy(self._load_unlocked().get("users", {}))

    # Backward-compatible helpers used by tests and administrative code.
    def _read(self):
        with self._lock:
            return deepcopy(self._load_unlocked())

    def _write(self, data):
        with self._lock:
            cached = deepcopy(data)
            _CACHE[self._resolved_path] = cached
            self._write_unlocked(cached)

    def _load_unlocked(self):
        if self._resolved_path in _CACHE:
            return _CACHE[self._resolved_path]
        if not self.path.exists():
            data = {}
        else:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        _CACHE[self._resolved_path] = data
        return data

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
