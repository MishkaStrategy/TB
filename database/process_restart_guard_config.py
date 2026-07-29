"""Environment-backed settings for the persistent process restart guard."""

import os

from config import parse_bool, parse_positive_float, parse_positive_int


FVG_PROCESS_RESTART_GUARD_ENABLED = parse_bool(
    os.getenv("FVG_PROCESS_RESTART_GUARD_ENABLED"),
    default=False,
)
FVG_PROCESS_RESTART_MAX_REQUESTS = parse_positive_int(
    os.getenv("FVG_PROCESS_RESTART_MAX_REQUESTS"),
    3,
    "FVG_PROCESS_RESTART_MAX_REQUESTS",
)
FVG_PROCESS_RESTART_WINDOW_SECONDS = parse_positive_float(
    os.getenv("FVG_PROCESS_RESTART_WINDOW_SECONDS"),
    3600,
    "FVG_PROCESS_RESTART_WINDOW_SECONDS",
)
FVG_PROCESS_RESTART_COOLDOWN_SECONDS = parse_positive_float(
    os.getenv("FVG_PROCESS_RESTART_COOLDOWN_SECONDS"),
    3600,
    "FVG_PROCESS_RESTART_COOLDOWN_SECONDS",
)
FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS = parse_positive_int(
    os.getenv("FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS"),
    30,
    "FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS",
)
