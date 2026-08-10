"""Persistent access decisions for Telegram users."""

import json
import os
import threading
from copy import deepcopy
from pathlib import Path


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class AccessRegistry:
    def __init__(self, path="data/access_control.json"):
        self.path = Path(path)
        self._resolved_path = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._resolved_path, threading.RLock())

    def status(self, user_id):
        with self._lock:
            return self._read_unlocked().get("users", {}).get(str(user_id), {}).get(
                "status"
            )

    def is_allowed(self, user_id):
        return self.status(user_id) == "allowed"

    def users(self, status=None):
        with self._lock:
            users = self._read_unlocked().get("users", {})
            if status is None:
                return deepcopy(users)
            return {
                str(user_id): deepcopy(record)
                for user_id, record in users.items()
                if isinstance(record, dict) and record.get("status") == status
            }

    def request(self, user_id, name, username):
        with self._lock:
            data = self._read_unlocked()
            users = data.setdefault("users", {})
            record = users.get(str(user_id), {})
            if record.get("status") in {"allowed", "blocked"}:
                return record["status"]
            if record.get("status") == "pending":
                return "pending_existing"
            users[str(user_id)] = {
                "status": "pending",
                "name": name,
                "username": username,
            }
            self._write_unlocked(data)
            return "pending"

    def decide(self, user_id, status):
        if status not in {"allowed", "blocked"}:
            raise ValueError("status must be allowed or blocked")
        with self._lock:
            data = self._read_unlocked()
            record = data.setdefault("users", {}).get(str(user_id))
            if record is None or record.get("status") != "pending":
                return False
            record["status"] = status
            self._write_unlocked(data)
            return True

    def allow(self, user_id, name=None, username=None):
        """Create or replace a runtime allowlist record.

        This method is intentionally separate from ``decide`` because an
        administrator may add a Telegram ID before that user submits a request.
        Environment-provided IDs remain outside this registry and must be
        protected by the caller.
        """

        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError("user_id must be positive")
        with self._lock:
            data = self._read_unlocked()
            users = data.setdefault("users", {})
            previous = users.get(str(user_id), {})
            record = {
                "status": "allowed",
                "name": str(name or previous.get("name") or "Без имени").strip()
                or "Без имени",
                "username": (
                    str(username).strip().lstrip("@")
                    if username is not None
                    else previous.get("username")
                ),
            }
            users[str(user_id)] = record
            self._write_unlocked(data)
            return deepcopy(record)

    def remove(self, user_id):
        """Remove a runtime access record and return whether it existed."""

        with self._lock:
            data = self._read_unlocked()
            users = data.setdefault("users", {})
            removed = users.pop(str(int(user_id)), None)
            if removed is None:
                return False
            self._write_unlocked(data)
            return True

    # Backward-compatible helpers used by tests and administrative code.
    def _read(self):
        with self._lock:
            return deepcopy(self._read_unlocked())

    def _write(self, data):
        with self._lock:
            self._write_unlocked(deepcopy(data))

    def _read_unlocked(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_unlocked(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(
            f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
