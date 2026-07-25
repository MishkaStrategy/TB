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
MAX_ACTIVE_SYMBOLS = parse_positive_int(
    os.getenv("MAX_ACTIVE_SYMBOLS"), 100, "MAX_ACTIVE_SYMBOLS"
)
MAX_SYMBOLS_PER_USER = parse_positive_int(
    os.getenv("MAX_SYMBOLS_PER_USER"), 20, "MAX_SYMBOLS_PER_USER"
)
FVG_DELIVERY_QUEUE_SIZE = parse_positive_int(
    os.getenv("FVG_DELIVERY_QUEUE_SIZE"), 1000, "FVG_DELIVERY_QUEUE_SIZE"
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


def is_authorized(telegram_id):
    return telegram_id in ALLOWED_TELEGRAM_IDS


def is_admin(telegram_id):
    return telegram_id in ADMIN_TELEGRAM_IDS
