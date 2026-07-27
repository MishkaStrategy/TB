"""Persistent per-user interface and notification preferences."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
SUPPORTED_LANGUAGES = frozenset({"ru", "en"})
SUPPORTED_MESSAGE_MODES = frozenset({"compact", "detailed"})


def _defaults() -> dict:
    return {"language": "ru", "message_mode": "detailed"}


class UserPreferences:
    def __init__(self, path: str | os.PathLike = "data/user_preferences.json"):
        self.path = Path(path)
        resolved = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(resolved, threading.RLock())

    def user(self, chat_id: int) -> dict:
        with self._lock:
            data = self._read_unlocked()
            value = data.get("users", {}).get(str(chat_id), {})
            result = _defaults()
            if isinstance(value, dict):
                result.update(value)
            if result["language"] not in SUPPORTED_LANGUAGES:
                result["language"] = "ru"
            if result["message_mode"] not in SUPPORTED_MESSAGE_MODES:
                result["message_mode"] = "detailed"
            return deepcopy(result)

    def ensure(self, chat_id: int, *, language: str | None = None) -> dict:
        with self._lock:
            data = self._read_unlocked()
            users = data.setdefault("users", {})
            key = str(chat_id)
            if key not in users:
                initial = _defaults()
                if language in SUPPORTED_LANGUAGES:
                    initial["language"] = language
                users[key] = initial
                self._write_unlocked(data)
            return self.user(chat_id)

    def set_language(self, chat_id: int, language: str) -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("language must be ru or en")
        return self._update(chat_id, language=language)

    def set_message_mode(self, chat_id: int, mode: str) -> dict:
        if mode not in SUPPORTED_MESSAGE_MODES:
            raise ValueError("message mode must be compact or detailed")
        return self._update(chat_id, message_mode=mode)

    def _update(self, chat_id: int, **values) -> dict:
        with self._lock:
            data = self._read_unlocked()
            user = data.setdefault("users", {}).setdefault(str(chat_id), _defaults())
            user.update(values)
            self._write_unlocked(data)
        return self.user(chat_id)

    def _read_unlocked(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_unlocked(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
