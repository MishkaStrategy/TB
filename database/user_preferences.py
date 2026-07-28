"""Persistent per-user interface and notification preferences."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path

_LOCKS: dict[str, threading.RLock] = {}
_STATES: dict[str, dict] = {}
_LOADED: set[str] = set()
_LOCKS_GUARD = threading.Lock()
SUPPORTED_LANGUAGES = frozenset({"ru", "en"})
SUPPORTED_MESSAGE_MODES = frozenset({"compact", "detailed"})


def _defaults() -> dict:
    return {"language": "ru", "message_mode": "detailed"}


def _normalized(value) -> dict:
    value = value if isinstance(value, dict) else {}
    language = value.get("language", "ru")
    message_mode = value.get("message_mode", "detailed")
    if language not in SUPPORTED_LANGUAGES:
        language = "ru"
    if message_mode not in SUPPORTED_MESSAGE_MODES:
        message_mode = "detailed"
    return {"language": language, "message_mode": message_mode}


class UserPreferences:
    """Thread-safe preferences with one shared in-memory state per file path.

    Telegram delivery may call ``user`` thousands of times in one batch. Reading
    and parsing JSON for every message turns the notification hot path into
    synchronous disk I/O, so the file is loaded once per process and only
    rewritten when a preference actually changes.
    """

    def __init__(self, path: str | os.PathLike = "data/user_preferences.json"):
        self.path = Path(path)
        self._resolved = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._resolved, threading.RLock())

    def user(self, chat_id: int) -> dict:
        with self._lock:
            data = self._state_unlocked()
            value = data.get("users", {}).get(str(chat_id), {})
            return deepcopy(_normalized(value))

    def ensure(self, chat_id: int, *, language: str | None = None) -> dict:
        with self._lock:
            data = self._state_unlocked()
            users = data.setdefault("users", {})
            key = str(chat_id)
            if not isinstance(users.get(key), dict):
                initial = _defaults()
                if language in SUPPORTED_LANGUAGES:
                    initial["language"] = language
                users[key] = initial
                self._write_unlocked(data)
            return deepcopy(_normalized(users[key]))

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
            data = self._state_unlocked()
            users = data.setdefault("users", {})
            key = str(chat_id)
            current = users.get(key)
            if not isinstance(current, dict):
                current = _defaults()
                users[key] = current
            current.update(values)
            self._write_unlocked(data)
            return deepcopy(_normalized(current))

    def _state_unlocked(self) -> dict:
        if self._resolved not in _LOADED:
            _STATES[self._resolved] = self._read_file_unlocked()
            _LOADED.add(self._resolved)
        return _STATES[self._resolved]

    def _read_file_unlocked(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_unlocked(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(
            f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
