"""Telegram administrator dashboard and safe operational controls."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import PUBLIC_ACCESS_ENABLED, is_admin
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from operations.admin_service import (
    active_user_count,
    background_tasks,
    clear_stuck_outbox,
    disable_symbol_for_all_users,
    event_counts,
    problematic_symbols,
    process_memory_bytes,
    run_recovery,
)
from operations.stream_control import restart_fvg_stream


_RUNTIME_SETTINGS = RuntimeSettings()
UTC = timezone.utc


def public_access_enabled():
    return _RUNTIME_SETTINGS.public_access_enabled(default=PUBLIC_ACCESS_ENABLED)


def maintenance_enabled():
    return _RUNTIME_SETTINGS.maintenance_enabled(default=False)


def admin_keyboard(public_access=None, maintenance=None):
    if public_access is None:
        public_access = public_access_enabled()
    if maintenance is None:
        maintenance = maintenance_enabled()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Обзор", callback_data="admin:overview"),
                InlineKeyboardButton("👥 Пользователи", callback_data="admin:users"),
            ],
            [
                InlineKeyboardButton("⚠️ Инструменты", callback_data="admin:problems"),
                InlineKeyboardButton("⏱ Задачи", callback_data="admin:tasks"),
            ],
            [InlineKeyboardButton("🧰 Действия", callback_data="admin:actions")],
            [
                InlineKeyboardButton(
                    "🌐 Доступ: публичный" if public_access else "🔐 Доступ: приватный",
                    callback_data="admin:toggle_access",
                )
            ],
            [
                InlineKeyboardButton(
                    "🚧 Обслуживание: включено" if maintenance else "✅ Обслуживание: выключено",
                    callback_data="admin:ask_maintenance",
                )
            ],
        ]
    )


def actions_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔌 Перезапустить WebSocket", callback_data="admin:ask_restart")],
            [InlineKeyboardButton("♻️ Запустить REST recovery", callback_data="admin:ask_recovery")],
            [InlineKeyboardButton("🧹 Очистить зависший outbox", callback_data="admin:ask_clear")],
            [InlineKeyboardButton("🔔 Тестовое уведомление", callback_data="admin:test")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")],
        ]
    )


def confirm_keyboard(action, *, payload=None):
    data = f"admin:confirm_{action}"
    if payload:
        data += f":{payload}"
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Подтвердить", callback_data=data),
            InlineKeyboardButton("❌ Отмена", callback_data="admin:actions"),
        ]]
    )


def back_keyboard(target="main"):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад", callback_data=f"admin:{target}")]]
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


def _age_seconds(raw, now):
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw)).astimezone(UTC)
    except (TypeError, ValueError):
        return None
    return max(0, int((now - value).total_seconds()))


def format_user_stats(registry=None, now=None):
    registry = registry or UserActivityRegistry()
    now = now or datetime.now(UTC)
    users = list(registry.users().values())

    def active_since(delta):
        count = 0
        for user in users:
            try:
                count += datetime.fromisoformat(user["last_seen"]).astimezone(UTC) >= now - delta
            except (KeyError, TypeError, ValueError):
                continue
        return count

    latest = sorted(users, key=lambda user: user.get("last_seen", ""), reverse=True)[:5]
    lines = [
        "👥 Статистика пользователей", "",
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
                f"• {user.get('name', 'Без имени')}{username} — {_format_time(user.get('last_seen'))}"
            )
    return "\n".join(lines)


def format_bot_health(event_store, now=None, registry=None):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    health = event_store.health()
    ws_connected = health.get("ws_connected")
    ws_status = "подключён" if ws_connected is True else "отключён" if ws_connected is False else "неизвестно"
    last_ws = health.get("last_ws_message")
    ws_age = _age_seconds(last_ws, now)

    try:
        hour_signals, day_signals = event_counts(event_store, now)
    except (AttributeError, TypeError):
        hour_signals = day_signals = 0
    try:
        active_users = active_user_count(registry or UserActivityRegistry(), now)
    except (AttributeError, OSError):
        active_users = 0
    try:
        database_size = event_store.path.stat().st_size
    except OSError:
        database_size = 0

    lines = [
        "🩺 Состояние FVG Alert Bot", "",
        f"WebSocket: {ws_status}",
        f"Задержка последней свечи: {ws_age} сек." if ws_age is not None else "Задержка последней свечи: —",
        f"Последняя WS-свеча: {_format_time(last_ws)}",
        f"Активных пользователей за 24ч: {active_users}",
        f"Сигналов за час / сутки: {hour_signals} / {day_signals}",
        f"Outbox: {int(health.get('outbox') or 0)}",
        f"Ошибок доставки: {int(health.get('delivery_failures') or 0)}",
        f"Постоянных ошибок доставки: {int(health.get('delivery_permanent_failures') or 0)}",
        f"REST recovery: {int(health.get('rest_recoveries') or 0)}",
        f"Ошибок recovery: {int(health.get('recovery_failures') or 0)}",
        f"Использование памяти: {_format_bytes(process_memory_bytes())}",
        f"Размер SQLite: {_format_bytes(database_size)}",
        f"Последний recovery: {_format_time(health.get('last_rest_recovery'))}",
        f"Последняя ошибка: {health.get('last_error') or '—'}",
    ]
    return "\n".join(lines)


def format_problem_symbols(event_store):
    rows = problematic_symbols(event_store)
    if not rows:
        return "⚠️ Проблемные инструменты\n\nПроблемных инструментов в outbox нет.", []
    lines = ["⚠️ Проблемные инструменты", ""]
    for row in rows:
        error = str(row.get("last_error") or "—").replace("\n", " ")[:80]
        lines.append(
            f"• {row['symbol']}: сообщений {row['pending']}, попыток {row['attempts']}\n  {error}"
        )
    return "\n".join(lines), [row["symbol"] for row in rows]


def problems_keyboard(symbols):
    rows = [
        [InlineKeyboardButton(f"⛔ Отключить {symbol}", callback_data=f"admin:disable:{symbol}")]
        for symbol in symbols
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")])
    return InlineKeyboardMarkup(rows)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.effective_message.reply_text("Эта панель доступна только администраторам.")
        return
    await update.effective_message.reply_text(
        "🛠 Админ-панель",
        reply_markup=admin_keyboard(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    await query.answer()
    if not is_admin(user.id):
        await query.edit_message_text("Эта панель доступна только администраторам.")
        return

    from alerts.scheduler import get_fvg_service

    service = get_fvg_service()
    data = query.data or ""

    if data == "admin:main":
        await query.edit_message_text("🛠 Админ-панель", reply_markup=admin_keyboard())
    elif data in {"admin:overview", "admin:health"}:
        text = await asyncio.to_thread(format_bot_health, service.event_store)
        await query.edit_message_text(text, reply_markup=back_keyboard())
    elif data == "admin:users":
        text = await asyncio.to_thread(format_user_stats)
        await query.edit_message_text(text, reply_markup=back_keyboard())
    elif data == "admin:problems":
        text, symbols = await asyncio.to_thread(format_problem_symbols, service.event_store)
        await query.edit_message_text(text, reply_markup=problems_keyboard(symbols))
    elif data == "admin:tasks":
        tasks = background_tasks(context.application)
        text = "⏱ Фоновые задачи\n\n" + ("\n".join(f"• {name}" for name in tasks) or "Нет активных задач.")
        await query.edit_message_text(text, reply_markup=back_keyboard())
    elif data == "admin:actions":
        await query.edit_message_text("🧰 Служебные действия", reply_markup=actions_keyboard())
    elif data == "admin:ask_restart":
        await query.edit_message_text(
            "Перезапустить WebSocket-соединение Bitunix? Telegram-бот продолжит работать.",
            reply_markup=confirm_keyboard("restart"),
        )
    elif data == "admin:confirm_restart":
        await restart_fvg_stream(context.application)
        await query.edit_message_text("✅ WebSocket перезапущен.", reply_markup=actions_keyboard())
    elif data == "admin:ask_recovery":
        await query.edit_message_text(
            "Принудительно выполнить REST recovery для всех активных инструментов?",
            reply_markup=confirm_keyboard("recovery"),
        )
    elif data == "admin:confirm_recovery":
        events, failures = await run_recovery(service, context.bot)
        await query.edit_message_text(
            f"✅ Recovery завершён. Событий: {events}. Ошибок: {failures}.",
            reply_markup=actions_keyboard(),
        )
    elif data == "admin:ask_clear":
        await query.edit_message_text(
            "Удалить из outbox сообщения с 3+ попытками или старше 60 минут? Действие необратимо.",
            reply_markup=confirm_keyboard("clear"),
        )
    elif data == "admin:confirm_clear":
        removed = await asyncio.to_thread(clear_stuck_outbox, service.event_store)
        await query.edit_message_text(
            f"✅ Удалено зависших сообщений: {removed}.",
            reply_markup=actions_keyboard(),
        )
    elif data == "admin:test":
        await context.bot.send_message(
            chat_id=user.id,
            text="🔔 Тестовое уведомление администратора доставлено успешно.",
        )
        service.event_store.increment_health("admin_test_notifications")
        await query.edit_message_text("✅ Тестовое уведомление отправлено.", reply_markup=actions_keyboard())
    elif data == "admin:toggle_access":
        enabled = await asyncio.to_thread(
            _RUNTIME_SETTINGS.toggle_public_access,
            PUBLIC_ACCESS_ENABLED,
        )
        await query.edit_message_text(
            "🌐 Публичный доступ включён." if enabled else "🔐 Приватный доступ включён.",
            reply_markup=admin_keyboard(enabled, maintenance_enabled()),
        )
    elif data == "admin:ask_maintenance":
        target = not maintenance_enabled()
        await query.edit_message_text(
            "Включить режим обслуживания? Пользовательские команды будут доступны только администраторам."
            if target else "Выключить режим обслуживания и вернуть обычную работу?",
            reply_markup=confirm_keyboard("maintenance"),
        )
    elif data == "admin:confirm_maintenance":
        enabled = await asyncio.to_thread(_RUNTIME_SETTINGS.toggle_maintenance, False)
        await query.edit_message_text(
            "🚧 Режим обслуживания включён." if enabled else "✅ Режим обслуживания выключен.",
            reply_markup=admin_keyboard(public_access_enabled(), enabled),
        )
    elif data.startswith("admin:disable:"):
        symbol = data.rsplit(":", 1)[-1].upper()
        await query.edit_message_text(
            f"Отключить {symbol} у всех пользователей? Поток автоматически отпишется от инструмента.",
            reply_markup=confirm_keyboard("disable", payload=symbol),
        )
    elif data.startswith("admin:confirm_disable:"):
        symbol = data.rsplit(":", 1)[-1].upper()
        affected = await asyncio.to_thread(disable_symbol_for_all_users, service.settings, symbol)
        service.event_store.increment_health("admin_disabled_symbols")
        await query.edit_message_text(
            f"✅ {symbol} отключён. Изменено пользовательских настроек: {affected}.",
            reply_markup=back_keyboard("problems"),
        )
