"""Persistent runtime settings managed from the Telegram admin panel."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


_WRITE_LOCK = Lock()


class RuntimeSettings:
    """Store small mutable bot settings outside the release configuration."""

    def __init__(self, path="data/runtime_settings.json"):
        self.path = Path(path)

    def public_access_enabled(self, default=False):
        value = self._read().get("public_access_enabled")
        return value if isinstance(value, bool) else bool(default)

    def set_public_access_enabled(self, enabled):
        with _WRITE_LOCK:
            data = self._read()
            data["public_access_enabled"] = bool(enabled)
            self._write(data)
        return bool(enabled)

    def toggle_public_access(self, default=False):
        with _WRITE_LOCK:
            data = self._read()
            value = data.get("public_access_enabled")
            current = value if isinstance(value, bool) else bool(default)
            enabled = not current
            data["public_access_enabled"] = enabled
            self._write(data)
        return enabled

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
