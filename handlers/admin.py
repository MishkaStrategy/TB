"""Administrator dashboard, user statistics and operational health."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import PUBLIC_ACCESS_ENABLED, is_admin
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry


_RUNTIME_SETTINGS = RuntimeSettings()


def public_access_enabled():
    """Return the access mode currently applied by authorization handlers."""
    return _RUNTIME_SETTINGS.public_access_enabled(default=PUBLIC_ACCESS_ENABLED)


def admin_keyboard(public_access=None):
    if public_access is None:
        public_access = public_access_enabled()
    access_label = (
        "🌐 Доступ: публичный"
        if public_access
        else "🔐 Доступ: приватный"
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 Статистика пользователей",
                    callback_data="admin:users",
                )
            ],
            [
                InlineKeyboardButton(
                    "🩺 Состояние бота",
                    callback_data="admin:health",
                )
            ],
            [
                InlineKeyboardButton(
                    access_label,
                    callback_data="admin:toggle_access",
                )
            ],
        ]
    )


def _format_time(raw):
    if not raw:
        return "—"
    try:
        value = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return "некорректное значение"
    return value.astimezone().strftime("%d.%m.%Y %H:%M:%S")


def _format_bytes(value):
    size = max(0, int(value or 0))
    units = ("Б", "КБ", "МБ", "ГБ")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "Б" else f"{int(amount)} {unit}"
        amount /= 1024
    return f"{size} Б"


def format_user_stats(registry=None, now=None):
    registry = registry or UserActivityRegistry()
    now = now or datetime.now(timezone.utc)
    users = list(registry.users().values())

    def active_since(delta):
        return sum(
            datetime.fromisoformat(user["last_seen"]) >= now - delta
            for user in users
            if user.get("last_seen")
        )

    latest = sorted(
        users,
        key=lambda user: user.get("last_seen", ""),
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


def format_bot_health(event_store, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    health = event_store.health()
    ws_connected = health.get("ws_connected")
    if ws_connected is True:
        ws_status = "подключён"
    elif ws_connected is False:
        ws_status = "отключён"
    else:
        ws_status = "неизвестно"

    database_size = 0
    try:
        database_size = event_store.path.stat().st_size
    except OSError:
        pass

    last_ws = health.get("last_ws_message")
    ws_age = ""
    if last_ws:
        try:
            age = max(
                0,
                int(
                    (
                        now
                        - datetime.fromisoformat(str(last_ws)).astimezone(
                            timezone.utc
                        )
                    ).total_seconds()
                ),
            )
            ws_age = f" ({age} сек. назад)"
        except (TypeError, ValueError):
            ws_age = ""

    return "\n".join(
        [
            "🩺 Состояние FVG Alert Bot",
            "",
            f"Bitunix WebSocket: {ws_status}",
            f"Последняя WS-свеча: {_format_time(last_ws)}{ws_age}",
            (
                "Последний REST recovery: "
                f"{_format_time(health.get('last_rest_recovery'))}"
            ),
            f"Последняя ошибка: {health.get('last_error') or '—'}",
            "",
            f"Событий в SQLite: {int(health.get('events') or 0)}",
            f"Успешных доставок: {int(health.get('deliveries') or 0)}",
            f"Сообщений в outbox: {int(health.get('outbox') or 0)}",
            (
                "Ошибок доставки: "
                f"{int(health.get('delivery_failures') or 0)}"
            ),
            (
                "Повторных доставок: "
                f"{int(health.get('delivery_retries') or 0)}"
            ),
            f"Размер SQLite: {_format_bytes(database_size)}",
        ]
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.effective_message.reply_text(
            "Эта панель доступна только администраторам."
        )
        return
    current_access = await asyncio.to_thread(public_access_enabled)
    await update.effective_message.reply_text(
        "🛠 Админ-панель",
        reply_markup=admin_keyboard(current_access),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    await query.answer()
    if not is_admin(user.id):
        await query.edit_message_text(
            "Эта панель доступна только администраторам."
        )
        return
    if query.data == "admin:users":
        text = await asyncio.to_thread(format_user_stats)
        await query.edit_message_text(text, reply_markup=admin_keyboard())
    elif query.data == "admin:health":
        from alerts.scheduler import get_fvg_service

        text = await asyncio.to_thread(
            format_bot_health,
            get_fvg_service().event_store,
        )
        await query.edit_message_text(text, reply_markup=admin_keyboard())
    elif query.data == "admin:toggle_access":
        enabled = await asyncio.to_thread(
            _RUNTIME_SETTINGS.toggle_public_access,
            PUBLIC_ACCESS_ENABLED,
        )
        if enabled:
            text = (
                "🌐 Публичный доступ включён.\n\n"
                "Бот теперь принимает команды от всех Telegram-пользователей."
            )
        else:
            text = (
                "🔐 Приватный доступ включён.\n\n"
                "Бот принимает команды только от пользователей из allowlist "
                "и одобренных заявок."
            )
        await query.edit_message_text(
            text,
            reply_markup=admin_keyboard(enabled),
        )
