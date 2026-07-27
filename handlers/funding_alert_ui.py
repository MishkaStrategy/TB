"""Button-driven UI for per-user funding notifications."""

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
from handlers.auth import authorized


FUNDING_INPUT_KEY = "waiting_funding_alert_value"


def _mark(value: bool) -> str:
    return "✅" if value else "▫️"


def _format_threshold(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def format_funding_alert_settings(chat_id: int, store=None) -> str:
    store = store or FundingAlertStore()
    settings = store.user(chat_id)
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
        next_text = next_check.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")

    return (
        "🔔 <b>Уведомления о фандинге</b>\n\n"
        f"Статус: {'✅ включены' if settings['enabled'] else '⏸️ выключены'}\n"
        f"Частота: каждые {settings['interval_hours']} ч.\n"
        f"Порог: {_format_threshold(settings['threshold'])}%\n"
        f"Направление: {direction}\n"
        f"Следующая проверка: {next_text}\n\n"
        "Данные обновляются один раз в час — в 50 минут каждого часа."
    )


def build_funding_alert_menu(chat_id: int, store=None) -> InlineKeyboardMarkup:
    store = store or FundingAlertStore()
    settings = store.user(chat_id)
    status = "✅ Уведомления включены" if settings["enabled"] else "⏸️ Уведомления выключены"
    threshold = _format_threshold(settings["threshold"])
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(status, callback_data="funding-alert:toggle")],
            [
                InlineKeyboardButton(
                    f"⏱ {settings['interval_hours']} ч.",
                    callback_data="funding-alert:interval",
                ),
                InlineKeyboardButton(
                    f"📊 {threshold}%",
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
            [InlineKeyboardButton("📈 Топ ставок", callback_data="menu:funding")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
        ]
    )


def _clear_input_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(FUNDING_INPUT_KEY, None)
    context.chat_data.pop(FUNDING_INPUT_KEY, None)


async def _show_settings(message, chat_id: int, *, edit: bool) -> None:
    store = FundingAlertStore()
    method = message.edit_text if edit else message.reply_text
    await method(
        format_funding_alert_settings(chat_id, store),
        reply_markup=build_funding_alert_menu(chat_id, store),
        parse_mode="HTML",
    )


@authorized
async def funding_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    action = query.data.removeprefix("funding-alert:")
    chat_id = update.effective_chat.id
    store = FundingAlertStore()
    _clear_input_state(context)

    if action == "open":
        await query.answer()
        await _show_settings(query.message, chat_id, edit=True)
        return

    if action == "interval":
        state = {"kind": "interval"}
        context.user_data[FUNDING_INPUT_KEY] = state
        context.chat_data[FUNDING_INPUT_KEY] = state
        await query.answer()
        await query.message.reply_text(
            "Введите частоту уведомлений целым числом от 1 до 48.\n"
            "Например: 4"
        )
        return

    if action == "threshold":
        state = {"kind": "threshold"}
        context.user_data[FUNDING_INPUT_KEY] = state
        context.chat_data[FUNDING_INPUT_KEY] = state
        await query.answer()
        await query.message.reply_text(
            "Введите порог фандинга в процентах положительным числом.\n"
            "Например: 0,3"
        )
        return

    settings = store.user(chat_id)
    if action == "toggle":
        store.set_enabled(chat_id, not settings["enabled"])
    elif action in {"positive", "negative"}:
        positive = settings["notify_positive"]
        negative = settings["notify_negative"]
        if action == "positive":
            positive = not positive
        else:
            negative = not negative
        if not positive and not negative:
            await query.answer(
                "Нужно выбрать хотя бы одно направление.",
                show_alert=True,
            )
            return
        store.set_directions(
            chat_id,
            notify_positive=positive,
            notify_negative=negative,
        )
    else:
        await query.answer()
        return

    await query.answer()
    await query.message.edit_text(
        format_funding_alert_settings(chat_id, store),
        reply_markup=build_funding_alert_menu(chat_id, store),
        parse_mode="HTML",
    )


@authorized
async def receive_funding_alert_value(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    state = context.user_data.get(FUNDING_INPUT_KEY) or context.chat_data.get(
        FUNDING_INPUT_KEY
    )
    if not state:
        return

    chat_id = update.effective_chat.id
    store = FundingAlertStore()
    try:
        if state["kind"] == "interval":
            interval = parse_interval_hours(update.effective_message.text)
            store.set_interval(chat_id, interval)
            confirmation = f"✅ Частота сохранена: каждые {interval} ч."
        else:
            threshold = parse_threshold(update.effective_message.text)
            store.set_threshold(chat_id, threshold)
            confirmation = f"✅ Порог сохранён: {_format_threshold(threshold)}%."
    except ValueError as error:
        await update.effective_message.reply_text(
            f"Не получилось: {error}\nПопробуйте ещё раз."
        )
        return

    _clear_input_state(context)
    await update.effective_message.reply_text(
        confirmation,
        reply_markup=build_funding_alert_menu(chat_id, store),
    )


def build_funding_alert_handlers():
    return (
        CallbackQueryHandler(funding_alert_callback, pattern=r"^funding-alert:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_funding_alert_value),
    )
