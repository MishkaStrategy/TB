"""Persistent access decisions for Telegram users."""

import json
from copy import deepcopy
from pathlib import Path


class AccessRegistry:
    def __init__(self, path="data/access_control.json"):
        self.path = Path(path)

    def status(self, user_id):
        return self._read().get("users", {}).get(str(user_id), {}).get("status")

    def is_allowed(self, user_id):
        return self.status(user_id) == "allowed"

    def users(self, status=None):
        users = self._read().get("users", {})
        if status is None:
            return deepcopy(users)
        return {
            str(user_id): deepcopy(record)
            for user_id, record in users.items()
            if isinstance(record, dict) and record.get("status") == status
        }

    def request(self, user_id, name, username):
        data = self._read()
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
        self._write(data)
        return "pending"

    def decide(self, user_id, status):
        if status not in {"allowed", "blocked"}:
            raise ValueError("status must be allowed or blocked")
        data = self._read()
        record = data.setdefault("users", {}).get(str(user_id))
        if record is None or record.get("status") != "pending":
            return False
        record["status"] = status
        self._write(data)
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
        data = self._read()
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
        self._write(data)
        return deepcopy(record)

    def remove(self, user_id):
        """Remove a runtime access record and return whether it existed."""

        data = self._read()
        users = data.setdefault("users", {})
        removed = users.pop(str(int(user_id)), None)
        if removed is None:
            return False
        self._write(data)
        return True

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
