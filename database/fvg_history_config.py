"""Environment-backed FVG history retention settings."""

import os

from config import parse_bool, parse_positive_int


# Historical FVG data must never fall back to delete-only retention. Archive
# retention is therefore the safe default. An explicit false value means
# "preserve runtime history without pruning", not "delete without archive".
FVG_HISTORY_ARCHIVE_ENABLED = parse_bool(
    os.getenv("FVG_HISTORY_ARCHIVE_ENABLED"),
    default=True,
)
FVG_HISTORY_ARCHIVE_PATH = os.getenv(
    "FVG_HISTORY_ARCHIVE_PATH",
    "data/archive/fvg_history.sqlite3",
).strip() or "data/archive/fvg_history.sqlite3"
FVG_HISTORY_RETENTION_DAYS = parse_positive_int(
    os.getenv("FVG_HISTORY_RETENTION_DAYS"),
    90,
    "FVG_HISTORY_RETENTION_DAYS",
)
FVG_HISTORY_ARCHIVE_BATCH_SIZE = parse_positive_int(
    os.getenv("FVG_HISTORY_ARCHIVE_BATCH_SIZE"),
    500,
    "FVG_HISTORY_ARCHIVE_BATCH_SIZE",
)
FVG_HISTORY_ARCHIVE_MAX_BATCHES = parse_positive_int(
    os.getenv("FVG_HISTORY_ARCHIVE_MAX_BATCHES"),
    10,
    "FVG_HISTORY_ARCHIVE_MAX_BATCHES",
)
