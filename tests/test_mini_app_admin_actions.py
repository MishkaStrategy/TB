import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from mini_app_backend.admin_actions import (
    AdminActionError,
    AdminConfirmationStore,
    MiniAppAdminActions,
)
from mini_app_backend.auth import TelegramUser


UTC = timezone.utc


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)

    def now(self):
        return self.value


class MiniAppAdminActionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.access = AccessRegistry(root / "access.json")
        self.runtime = RuntimeSettings(root / "runtime.json")
        self.activity = UserActivityRegistry(root / "activity.json")
        self.clock = MutableClock()
        self.confirmations = AdminConfirmationStore(
            ttl_seconds=60,
            now=self.clock.now,
        )
        self.backup_calls = []
        self.restart_calls = []

        async def backup_callback(user):
            self.backup_calls.append(user.id)
            return {"accepted": True, "operation": "backup"}

        def restart_callback(user):
            self.restart_calls.append(user.id)
            return {"accepted": True, "operation": "restart"}

        self.actions = MiniAppAdminActions(
            admin_checker=lambda telegram_id: telegram_id == 1,
            access_registry=self.access,
            activity_registry=self.activity,
            runtime_settings=self.runtime,
            env_allowed_ids={1, 9},
            env_admin_ids={1},
            confirmation_store=self.confirmations,
            backup_callback=backup_callback,
            restart_callback=restart_callback,
        )
        self.admin = TelegramUser(id=1, first_name="Admin")
        self.user = TelegramUser(id=42, first_name="User")

    def tearDown(self):
        self.temporary.cleanup()

    def challenge(self, action, telegram_id=None):
        return self.actions.create_confirmation(
            self.admin,
            action=action,
            target_telegram_id=telegram_id,
        )

    def test_non_admin_cannot_request_confirmation(self):
        with self.assertRaises(AdminActionError) as context:
            self.actions.create_confirmation(self.user, action="backup.create")
        self.assertEqual(context.exception.code, "ADMIN_REQUIRED")
        self.assertEqual(context.exception.status, 403)

    def test_allowlist_add_and_remove_require_bound_one_time_confirmation(self):
        challenge = self.challenge("allowlist.add", 42)
        added = self.actions.add_allowlist(
            self.admin,
            target_telegram_id=42,
            name="Михаил",
            username="@michael",
            confirmation_token=challenge["token"],
            confirmation_text=challenge["confirmationText"],
        )
        self.assertEqual(added["telegramId"], 42)
        self.assertEqual(added["username"], "michael")
        self.assertTrue(self.access.is_allowed(42))

        with self.assertRaises(AdminActionError) as replay:
            self.actions.add_allowlist(
                self.admin,
                target_telegram_id=42,
                confirmation_token=challenge["token"],
                confirmation_text=challenge["confirmationText"],
            )
        self.assertEqual(replay.exception.code, "CONFIRMATION_INVALID")

        remove = self.challenge("allowlist.remove", 42)
        result = self.actions.remove_allowlist(
            self.admin,
            target_telegram_id=42,
            confirmation_token=remove["token"],
            confirmation_text=remove["confirmationText"],
        )
        self.assertTrue(result["removed"])
        self.assertIsNone(self.access.status(42))

    def test_confirmation_is_bound_to_exact_target(self):
        challenge = self.challenge("allowlist.add", 42)
        with self.assertRaises(AdminActionError) as context:
            self.actions.add_allowlist(
                self.admin,
                target_telegram_id=43,
                confirmation_token=challenge["token"],
                confirmation_text=challenge["confirmationText"],
            )
        self.assertEqual(context.exception.code, "CONFIRMATION_MISMATCH")

    def test_expired_confirmation_is_rejected(self):
        challenge = self.challenge("access.public")
        self.clock.value += timedelta(seconds=61)
        with self.assertRaises(AdminActionError) as context:
            self.actions.set_public_access(
                self.admin,
                public_access_enabled=True,
                confirmation_token=challenge["token"],
                confirmation_text=challenge["confirmationText"],
            )
        self.assertEqual(context.exception.code, "CONFIRMATION_EXPIRED")

    def test_access_mode_uses_separate_confirmed_action(self):
        challenge = self.challenge("access.public")
        result = self.actions.set_public_access(
            self.admin,
            public_access_enabled=True,
            confirmation_token=challenge["token"],
            confirmation_text=challenge["confirmationText"],
        )
        self.assertTrue(result["publicAccessEnabled"])
        self.assertTrue(self.runtime.public_access_enabled(default=False))

    def test_env_and_admin_records_cannot_be_removed(self):
        challenge = self.challenge("allowlist.remove", 9)
        with self.assertRaises(AdminActionError) as context:
            self.actions.remove_allowlist(
                self.admin,
                target_telegram_id=9,
                confirmation_token=challenge["token"],
                confirmation_text=challenge["confirmationText"],
            )
        self.assertEqual(context.exception.code, "PROTECTED_ACCESS_RECORD")

    async def test_backup_and_restart_callbacks_are_confirmed_and_invoked(self):
        backup = self.challenge("backup.create")
        backup_result = await self.actions.create_backup(
            self.admin,
            confirmation_token=backup["token"],
            confirmation_text=backup["confirmationText"],
        )
        self.assertEqual(backup_result["operation"], "backup")
        self.assertEqual(self.backup_calls, [1])

        restart = self.challenge("bot.restart")
        restart_result = await self.actions.restart_bot(
            self.admin,
            confirmation_token=restart["token"],
            confirmation_text=restart["confirmationText"],
        )
        self.assertEqual(restart_result["operation"], "restart")
        self.assertEqual(self.restart_calls, [1])

    async def test_unwired_backup_and_restart_fail_closed(self):
        actions = MiniAppAdminActions(
            admin_checker=lambda telegram_id: telegram_id == 1,
            access_registry=self.access,
            activity_registry=self.activity,
            runtime_settings=self.runtime,
            confirmation_store=AdminConfirmationStore(now=self.clock.now),
        )
        self.assertFalse(actions.capabilities(self.admin)["backup"])
        self.assertFalse(actions.capabilities(self.admin)["restart"])

        backup = actions.create_confirmation(self.admin, action="backup.create")
        with self.assertRaises(AdminActionError) as backup_error:
            await actions.create_backup(
                self.admin,
                confirmation_token=backup["token"],
                confirmation_text=backup["confirmationText"],
            )
        self.assertEqual(backup_error.exception.code, "BACKUP_ACTION_UNAVAILABLE")

        restart = actions.create_confirmation(self.admin, action="bot.restart")
        with self.assertRaises(AdminActionError) as restart_error:
            await actions.restart_bot(
                self.admin,
                confirmation_token=restart["token"],
                confirmation_text=restart["confirmationText"],
            )
        self.assertEqual(restart_error.exception.code, "RESTART_ACTION_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
