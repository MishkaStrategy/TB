"""Administrator dashboard with restored user activity statistics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import is_admin
from database.user_activity import UserActivityRegistry
from handlers import admin_settings as _settings


_ORIGINAL_ADMIN_KEYBOARD = _settings.admin_keyboard


def admin_keyboard(public_access=None) -> InlineKeyboardMarkup:
    """Extend the current admin keyboard with the user statistics screen."""
    markup = _ORIGINAL_ADMIN_KEYBOARD(public_access)
    rows = [list(row) for row in markup.inline_keyboard]
    has_user_stats = any(
        button.callback_data == "admin:users"
        for row in rows
        for button in row
    )
    if not has_user_stats:
        rows.insert(
            2,
            [
                InlineKeyboardButton(
                    "👥 Статистика пользователей",
                    callback_data="admin:users",
                )
            ],
        )
    return InlineKeyboardMarkup(rows)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "—"
    return parsed.astimezone().strftime("%d.%m.%Y %H:%M:%S")


def format_user_stats(registry=None, now=None) -> str:
    """Format aggregate user activity and the five latest users."""
    registry = registry or UserActivityRegistry()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    users = list(registry.users().values())

    def active_since(delta):
        threshold = current_time - delta
        return sum(
            1
            for user in users
            if (last_seen := _parse_time(user.get("last_seen"))) is not None
            and last_seen >= threshold
        )

    latest = sorted(
        users,
        key=lambda user: _parse_time(user.get("last_seen"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:5]
    lines = [
        "👥 Статистика пользователей",
        "",
        f"Всего пользователей: {len(users)}",
        f"Активны за 24 часа: {active_since(timedelta(days=1))}",
        f"Активны за 7 дней: {active_since(timedelta(days=7))}",
        f"Активны за 30 дней: {active_since(timedelta(days=30))}",
    ]
    if latest:
        lines.extend(["", "Последняя активность:"])
        for user in latest:
            username = f" @{user['username']}" if user.get("username") else ""
            lines.append(
                f"• {user.get('name', 'Без имени')}{username} — "
                f"{_format_time(user.get('last_seen'))}"
            )
    return "\n".join(lines)


# Existing admin functions resolve this global at call time, so patching it keeps
# every current admin screen on the same extended keyboard.
_settings.admin_keyboard = admin_keyboard
admin = _settings.admin


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    if query is None or user is None:
        return
    if query.data != "admin:users":
        await _settings.admin_callback(update, context)
        return
    if not is_admin(user.id):
        await query.answer(
            "Эта панель доступна только администраторам.",
            show_alert=True,
        )
        return
    await query.answer()
    text = await asyncio.to_thread(format_user_stats)
    await query.edit_message_text(text, reply_markup=admin_keyboard())
