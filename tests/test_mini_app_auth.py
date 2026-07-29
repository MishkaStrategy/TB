import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from mini_app_backend.auth import TelegramInitDataError, validate_init_data


BOT_TOKEN = "123456:test-token"
NOW = 1_800_000_000


def signed_init_data(*, auth_date=NOW, user=None, token=BOT_TOKEN, **extra):
    user = user or {
        "id": 42,
        "first_name": "Михаил",
        "username": "michael",
        "language_code": "ru",
    }
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAExampleQuery",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        **{key: str(value) for key, value in extra.items()},
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_init_data_returns_verified_user(self):
        user = validate_init_data(signed_init_data(), BOT_TOKEN, now=NOW)
        self.assertEqual(user.id, 42)
        self.assertEqual(user.first_name, "Михаил")
        self.assertEqual(user.username, "michael")

    def test_tampered_payload_is_rejected(self):
        raw = signed_init_data().replace("michael", "attacker")
        with self.assertRaisesRegex(TelegramInitDataError, "signature"):
            validate_init_data(raw, BOT_TOKEN, now=NOW)

    def test_expired_payload_is_rejected(self):
        with self.assertRaises(TelegramInitDataError) as context:
            validate_init_data(
                signed_init_data(auth_date=NOW - 3601),
                BOT_TOKEN,
                max_age_seconds=3600,
                now=NOW,
            )
        self.assertEqual(context.exception.code, "EXPIRED_INIT_DATA")

    def test_future_payload_is_rejected(self):
        with self.assertRaises(TelegramInitDataError) as context:
            validate_init_data(
                signed_init_data(auth_date=NOW + 31),
                BOT_TOKEN,
                now=NOW,
            )
        self.assertEqual(context.exception.code, "FUTURE_INIT_DATA")

    def test_missing_user_is_rejected(self):
        fields = {"auth_date": str(NOW), "query_id": "AAExampleQuery"}
        check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(fields.items())
        )
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(
            secret, check_string.encode(), hashlib.sha256
        ).hexdigest()
        with self.assertRaises(TelegramInitDataError) as context:
            validate_init_data(urlencode(fields), BOT_TOKEN, now=NOW)
        self.assertEqual(context.exception.code, "INVALID_USER")

    def test_duplicate_fields_are_rejected(self):
        raw = signed_init_data() + "&auth_date=" + str(NOW)
        with self.assertRaises(TelegramInitDataError):
            validate_init_data(raw, BOT_TOKEN, now=NOW)


if __name__ == "__main__":
    unittest.main()
