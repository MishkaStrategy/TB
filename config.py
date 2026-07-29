import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

BITUNIX_API_KEY = os.getenv("BITUNIX_API_KEY")
BITUNIX_SECRET = os.getenv("BITUNIX_SECRET")


def parse_bool(value, default=False):
    if value is None:
        return bool(default)
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Некорректное логическое значение: {value}")


def parse_positive_int(value, default, name):
    if value is None or not value.strip():
        return int(default)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} должно быть целым числом") from error
    if parsed <= 0:
        raise ValueError(f"{name} должно быть больше нуля")
    return parsed


def parse_positive_float(value, default, name):
    if value is None or not value.strip():
        return float(default)
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} должно быть числом") from error
    if parsed <= 0:
        raise ValueError(f"{name} должно быть больше нуля")
    return parsed


def parse_ratio(value, default, name):
    if value is None or not value.strip():
        return float(default)
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} должно быть числом от 0 до 1") from error
    if not 0 <= parsed <= 1:
        raise ValueError(f"{name} должно быть числом от 0 до 1")
    return parsed


def parse_telegram_ids(value):
    if not value:
        return frozenset()

    return frozenset(
        int(user_id.strip())
        for user_id in value.split(",")
        if user_id.strip()
    )


ALLOWED_TELEGRAM_IDS = parse_telegram_ids(
    os.getenv("ALLOWED_TELEGRAM_IDS")
)
ADMIN_TELEGRAM_IDS = parse_telegram_ids(
    os.getenv("ADMIN_TELEGRAM_IDS")
) or ALLOWED_TELEGRAM_IDS

# Production defaults are intentionally restrictive. Public mode must be
# enabled explicitly in the environment.
PUBLIC_ACCESS_ENABLED = parse_bool(os.getenv("PUBLIC_ACCESS_ENABLED"), default=False)

# Delivery changes are additive and remain disabled until explicitly enabled.
DELIVERY_STATUS_TRACKING_ENABLED = parse_bool(
    os.getenv("DELIVERY_STATUS_TRACKING_ENABLED"),
    default=False,
)
USER_BLOCK_STATUS_ENABLED = parse_bool(
    os.getenv("USER_BLOCK_STATUS_ENABLED"),
    default=False,
)
OUTBOX_RETRY_POLICY_ENABLED = parse_bool(
    os.getenv("OUTBOX_RETRY_POLICY_ENABLED"),
    default=False,
)
OUTBOX_EXPIRATION_ENABLED = parse_bool(
    os.getenv("OUTBOX_EXPIRATION_ENABLED"),
    default=False,
)
OUTBOX_MAX_ATTEMPTS = parse_positive_int(
    os.getenv("OUTBOX_MAX_ATTEMPTS"),
    8,
    "OUTBOX_MAX_ATTEMPTS",
)
OUTBOX_BASE_BACKOFF_SECONDS = parse_positive_float(
    os.getenv("OUTBOX_BASE_BACKOFF_SECONDS"),
    5,
    "OUTBOX_BASE_BACKOFF_SECONDS",
)
OUTBOX_MAX_BACKOFF_SECONDS = parse_positive_float(
    os.getenv("OUTBOX_MAX_BACKOFF_SECONDS"),
    900,
    "OUTBOX_MAX_BACKOFF_SECONDS",
)
OUTBOX_JITTER_RATIO = parse_ratio(
    os.getenv("OUTBOX_JITTER_RATIO"),
    0.2,
    "OUTBOX_JITTER_RATIO",
)
OUTBOX_PROCESSING_LEASE_SECONDS = parse_positive_float(
    os.getenv("OUTBOX_PROCESSING_LEASE_SECONDS"),
    120,
    "OUTBOX_PROCESSING_LEASE_SECONDS",
)
OUTBOX_TERMINAL_RETENTION_DAYS = parse_positive_int(
    os.getenv("OUTBOX_TERMINAL_RETENTION_DAYS"),
    30,
    "OUTBOX_TERMINAL_RETENTION_DAYS",
)
OUTBOX_DEFAULT_TTL_SECONDS = parse_positive_int(
    os.getenv("OUTBOX_DEFAULT_TTL_SECONDS"),
    3600,
    "OUTBOX_DEFAULT_TTL_SECONDS",
)

# Read-only SQLite growth snapshots. Expensive row counts and integrity checks
# are independently opt-in and disabled for the scheduled collector by default.
DATABASE_OBSERVABILITY_ENABLED = parse_bool(
    os.getenv("DATABASE_OBSERVABILITY_ENABLED"),
    default=False,
)
DATABASE_OBSERVABILITY_INTERVAL_SECONDS = parse_positive_float(
    os.getenv("DATABASE_OBSERVABILITY_INTERVAL_SECONDS"),
    3600,
    "DATABASE_OBSERVABILITY_INTERVAL_SECONDS",
)
DATABASE_OBSERVABILITY_RETENTION_DAYS = parse_positive_int(
    os.getenv("DATABASE_OBSERVABILITY_RETENTION_DAYS"),
    90,
    "DATABASE_OBSERVABILITY_RETENTION_DAYS",
)
DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED = parse_bool(
    os.getenv("DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED"),
    default=False,
)
DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED = parse_bool(
    os.getenv("DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED"),
    default=False,
)

# Cross-process background job leases and a read-only stale-job watchdog.
# Both remain disabled until explicitly rolled out.
BACKGROUND_TASK_REGISTRY_ENABLED = parse_bool(
    os.getenv("BACKGROUND_TASK_REGISTRY_ENABLED"),
    default=False,
)
BACKGROUND_TASK_WATCHDOG_ENABLED = parse_bool(
    os.getenv("BACKGROUND_TASK_WATCHDOG_ENABLED"),
    default=False,
)
BACKGROUND_TASK_HISTORY_RETENTION_DAYS = parse_positive_int(
    os.getenv("BACKGROUND_TASK_HISTORY_RETENTION_DAYS"),
    30,
    "BACKGROUND_TASK_HISTORY_RETENTION_DAYS",
)
BACKGROUND_TASK_HEARTBEAT_SECONDS = parse_positive_float(
    os.getenv("BACKGROUND_TASK_HEARTBEAT_SECONDS"),
    30,
    "BACKGROUND_TASK_HEARTBEAT_SECONDS",
)
BACKGROUND_TASK_MIN_LEASE_SECONDS = parse_positive_float(
    os.getenv("BACKGROUND_TASK_MIN_LEASE_SECONDS"),
    120,
    "BACKGROUND_TASK_MIN_LEASE_SECONDS",
)
BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS = parse_positive_float(
    os.getenv("BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS"),
    60,
    "BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS",
)
BACKGROUND_TASK_STALE_MULTIPLIER = parse_positive_float(
    os.getenv("BACKGROUND_TASK_STALE_MULTIPLIER"),
    3,
    "BACKGROUND_TASK_STALE_MULTIPLIER",
)

# Application lifecycle tracking and bounded delivery drain during PTB post_stop.
RUNTIME_LIFECYCLE_ENABLED = parse_bool(
    os.getenv("RUNTIME_LIFECYCLE_ENABLED"),
    default=False,
)
GRACEFUL_SHUTDOWN_ENABLED = parse_bool(
    os.getenv("GRACEFUL_SHUTDOWN_ENABLED"),
    default=False,
)
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = parse_positive_float(
    os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS"),
    25,
    "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS",
)
RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS = parse_positive_int(
    os.getenv("RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS"),
    30,
    "RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS",
)

MAX_ACTIVE_SYMBOLS = parse_positive_int(
    os.getenv("MAX_ACTIVE_SYMBOLS"), 100, "MAX_ACTIVE_SYMBOLS"
)
MAX_SYMBOLS_PER_USER = parse_positive_int(
    os.getenv("MAX_SYMBOLS_PER_USER"), 20, "MAX_SYMBOLS_PER_USER"
)
FVG_DELIVERY_QUEUE_SIZE = parse_positive_int(
    os.getenv("FVG_DELIVERY_QUEUE_SIZE"), 1000, "FVG_DELIVERY_QUEUE_SIZE"
)
FVG_PROCESS_RESTART_STALE_SECONDS = parse_positive_float(
    os.getenv("FVG_PROCESS_RESTART_STALE_SECONDS"),
    1000,
    "FVG_PROCESS_RESTART_STALE_SECONDS",
)
HEALTH_WRITE_INTERVAL_SECONDS = parse_positive_float(
    os.getenv("HEALTH_WRITE_INTERVAL_SECONDS"),
    30,
    "HEALTH_WRITE_INTERVAL_SECONDS",
)
BITUNIX_REQUESTS_PER_SECOND = parse_positive_float(
    os.getenv("BITUNIX_REQUESTS_PER_SECOND"),
    8,
    "BITUNIX_REQUESTS_PER_SECOND",
)
HEALTH_ALERT_INTERVAL_SECONDS = parse_positive_float(
    os.getenv("HEALTH_ALERT_INTERVAL_SECONDS"),
    60,
    "HEALTH_ALERT_INTERVAL_SECONDS",
)
HEALTH_ALERT_STALE_WS_SECONDS = parse_positive_float(
    os.getenv("HEALTH_ALERT_STALE_WS_SECONDS"),
    180,
    "HEALTH_ALERT_STALE_WS_SECONDS",
)
HEALTH_ALERT_OUTBOX_THRESHOLD = parse_positive_int(
    os.getenv("HEALTH_ALERT_OUTBOX_THRESHOLD"),
    100,
    "HEALTH_ALERT_OUTBOX_THRESHOLD",
)
HEALTH_ALERT_COOLDOWN_SECONDS = parse_positive_float(
    os.getenv("HEALTH_ALERT_COOLDOWN_SECONDS"),
    1800,
    "HEALTH_ALERT_COOLDOWN_SECONDS",
)


def is_authorized(telegram_id):
    return telegram_id in ALLOWED_TELEGRAM_IDS


def is_admin(telegram_id):
    return telegram_id in ADMIN_TELEGRAM_IDS
