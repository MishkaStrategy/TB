"""Telegram settings UI for multi-exchange funding alerts."""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from alerts.funding_alerts import (
    FundingAlertStore,
    parse_interval_hours,
    parse_threshold,
)
from alerts.funding_exchange_store import FundingExchangeStore
from exchanges.funding import EXCHANGE_LABELS, EXCHANGE_ORDER
from handlers.auth import authorized
from handlers.multi_funding import CHECK_INPUT_KEY, receive_funding_check

INPUT_KEY = "waiting_funding_alert_value"


def _mark(value):
    return "✅" if value else "▫️"


def _threshold(value: Decimal):
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def _stores():
    settings = FundingAlertStore()
    exchanges = FundingExchangeStore(getattr(settings, "path", None))
    return settings, exchanges


def format_settings(chat_id, settings_store=None, exchange_store=None):
    settings_store = settings_store or FundingAlertStore()
    exchange_store = exchange_store or FundingExchangeStore(
        getattr(settings_store, "path", None)
    )
    settings = settings_store.user(chat_id)
    exchanges = exchange_store.selected(chat_id)
    if settings["notify_positive"] and settings["notify_negative"]:
        direction = "положительный и отрицательный"
    elif settings["notify_positive"]:
        direction = "положительный"
    else:
        direction = "отрицательный"
    next_check = settings.get("next_check_at")
    if not settings["enabled"]:
        next_text = "после включения — в ближайшие :50"
    elif next_check is None:
        next_text = "в ближайшие :50"
    else:
        next_text = next_check.astimezone(timezone.utc).strftime(
            "%d.%m %H:%M UTC"
        )
    exchange_text = ", ".join(EXCHANGE_LABELS[value] for value in exchanges)
    return (
        "🔔 <b>Уведомления о фандинге</b>\n\n"
        f"Статус: {'✅ включены' if settings['enabled'] else '⏸️ выключены'}\n"
        f"Частота: каждые {settings['interval_hours']} ч.\n"
        f"Порог: {_threshold(settings['threshold'])}%\n"
        f"Направление: {direction}\n"
        f"Биржи: {exchange_text}\n"
        f"Следующая проверка: {next_text}\n\n"
        "Общий снимок выбранных бирж обновляется в 50 минут каждого часа."
    )


def build_menu(chat_id, settings_store=None, exchange_store=None):
    settings_store = settings_store or FundingAlertStore()
    exchange_store = exchange_store or FundingExchangeStore(
        getattr(settings_store, "path", None)
    )
    settings = settings_store.user(chat_id)
    selected = set(exchange_store.selected(chat_id))
    status = (
        "✅ Уведомления включены"
        if settings["enabled"]
        else "⏸️ Уведомления выключены"
    )
    exchange_buttons = [
        InlineKeyboardButton(
            f"{_mark(key in selected)} {EXCHANGE_LABELS[key]}",
            callback_data=f"funding-alert:exchange:{key}",
        )
        for key in EXCHANGE_ORDER
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(status, callback_data="funding-alert:toggle")],
        [
            InlineKeyboardButton(
                f"⏱ {settings['interval_hours']} ч.",
                callback_data="funding-alert:interval",
            ),
            InlineKeyboardButton(
                f"📊 {_threshold(settings['threshold'])}%",
                callback_data="funding-alert:threshold",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{_mark(settings['notify_positive'])} Положительный",
                callback_data="funding-alert:positive",
            ),
            InlineKeyboardButton(
                f"{_mark(settings['notify_negative'])} Отрицательный",
                callback_data="funding-alert:negative",
            ),
        ],
        exchange_buttons[:3],
        exchange_buttons[3:],
        [InlineKeyboardButton("🔎 Проверка фандинга", callback_data="menu:funding-check")],
        [InlineKeyboardButton("📈 Топ ставок", callback_data="menu:funding")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
    ])


def _clear_input(context):
    context.user_data.pop(INPUT_KEY, None)
    context.chat_data.pop(INPUT_KEY, None)
    context.user_data.pop(CHECK_INPUT_KEY, None)
    context.chat_data.pop(CHECK_INPUT_KEY, None)


async def _show(message, chat_id, *, edit):
    settings, exchanges = _stores()
    method = message.edit_text if edit else message.reply_text
    await method(
        format_settings(chat_id, settings, exchanges),
        reply_markup=build_menu(chat_id, settings, exchanges),
        parse_mode="HTML",
    )


@authorized
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data:
        return
    action = query.data.removeprefix("funding-alert:")
    chat_id = update.effective_chat.id
    settings_store, exchange_store = _stores()
    _clear_input(context)
    if action == "open":
        await query.answer()
        await _show(query.message, chat_id, edit=True)
        return
    if action in {"interval", "threshold"}:
        state = {"kind": action}
        context.user_data[INPUT_KEY] = state
        context.chat_data[INPUT_KEY] = state
        await query.answer()
        prompt = (
            "Введите частоту уведомлений целым числом от 1 до 48.\n"
            "Например: 4"
            if action == "interval"
            else "Введите порог фандинга в процентах положительным числом.\n"
            "Например: 0,3"
        )
        await query.message.reply_text(prompt)
        return
    settings = settings_store.user(chat_id)
    try:
        if action == "toggle":
            settings_store.set_enabled(chat_id, not settings["enabled"])
            if settings["enabled"]:
                exchange_store.clear_crossings(chat_id)
        elif action in {"positive", "negative"}:
            positive = settings["notify_positive"]
            negative = settings["notify_negative"]
            if action == "positive":
                positive = not positive
            else:
                negative = not negative
            if not positive and not negative:
                raise ValueError("Нужно выбрать хотя бы одно направление.")
            settings_store.set_directions(
                chat_id,
                notify_positive=positive,
                notify_negative=negative,
            )
            exchange_store.clear_crossings(chat_id)
        elif action.startswith("exchange:"):
            exchange_store.toggle(chat_id, action.split(":", 1)[1])
        else:
            await query.answer()
            return
    except ValueError as error:
        await query.answer(str(error), show_alert=True)
        return
    await query.answer()
    await query.message.edit_text(
        format_settings(chat_id, settings_store, exchange_store),
        reply_markup=build_menu(chat_id, settings_store, exchange_store),
        parse_mode="HTML",
    )


@authorized
async def receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get(INPUT_KEY) or context.chat_data.get(INPUT_KEY)
    if not state:
        await receive_funding_check(update, context)
        return
    chat_id = update.effective_chat.id
    settings_store, exchange_store = _stores()
    try:
        if state["kind"] == "interval":
            value = parse_interval_hours(update.effective_message.text)
            settings_store.set_interval(chat_id, value)
            confirmation = f"✅ Частота сохранена: каждые {value} ч."
        else:
            value = parse_threshold(update.effective_message.text)
            settings_store.set_threshold(chat_id, value)
            exchange_store.clear_crossings(chat_id)
            confirmation = f"✅ Порог сохранён: {_threshold(value)}%."
    except ValueError as error:
        await update.effective_message.reply_text(
            f"Не получилось: {error}\nПопробуйте ещё раз."
        )
        return
    _clear_input(context)
    await update.effective_message.reply_text(
        confirmation,
        reply_markup=build_menu(chat_id, settings_store, exchange_store),
    )


def build_handlers():
    return (
        CallbackQueryHandler(callback, pattern=r"^funding-alert:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_value),
    )
