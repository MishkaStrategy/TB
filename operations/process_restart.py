"""Select and track the stale-process restart mechanism."""

from __future__ import annotations

import os
import signal
import threading

from config import FVG_PROCESS_GRACEFUL_RESTART_ENABLED


_GRACEFUL_RESTART_REQUESTED = threading.Event()


def graceful_restart_requested() -> bool:
    """Return whether this process requested a graceful systemd restart."""
    return _GRACEFUL_RESTART_REQUESTED.is_set()


def request_sigterm_restart(exit_code: int = 1) -> None:
    """Stop through PTB hooks, then let bot.main exit non-zero for systemd."""
    del exit_code
    _GRACEFUL_RESTART_REQUESTED.set()
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        _GRACEFUL_RESTART_REQUESTED.clear()
        raise


def default_restart_process():
    if FVG_PROCESS_GRACEFUL_RESTART_ENABLED:
        return request_sigterm_restart, "sigterm_then_failure_exit"
    return os._exit, "immediate_exit"
