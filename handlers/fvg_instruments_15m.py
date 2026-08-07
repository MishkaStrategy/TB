"""Button-driven FVG instrument management for confirmed 15m alerts only."""

from __future__ import annotations

import asyncio
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from alerts.fvg_store import FvgAlertSettings, instrument_key
from config import MAX_SYMBOLS_PER_USER
from exchanges.funding import EXCHANGE_LABELS, EXCHANGE_ORDER, exchange_label
from exchanges.fvg_candles import PublicCandleClient, normalize_fvg_symbol
from handlers.auth import authorized


FLOW_KEY = "fvg_instrument_flow"
FAQ_TEXTS = {
    "main": (
        "❓ <b>FAQ по FVG</b>\n\n"
        "Модуль работает только по закрытым 15-минутным свечам. "
        "Выберите раздел ниже."
    ),
    "add": (
        "➕ <b>Как добавить инструмент</b>\n\n"
        "1. Выберите биржу.\n"
        "2. Введите пару: BTC, BTCUSDT или BTC/USDT.\n"
        "3. Проверьте настройки и подтвердите добавление.\n\n"
        "Таймфрейм фиксированный — 15 минут. Одинаковая пара на разных "
        "биржах считается разными инструментами."
    ),
    "confirmed": (
        "✅ <b>Когда приходит FVG</b>\n\n"
        "FVG определяется по трём последовательным 15-минутным свечам. "
        "Уведомление отправляется только после закрытия свечи C, которая "
        "подтверждает зону. Предварительных сигналов до закрытия свечи нет."
    ),
    "limits": (
        "⚙️ <b>Лимиты и настройки</b>\n\n"
        f"Можно отслеживать не более {MAX_SYMBOLS_PER_USER} инструментов. "
        "Отключённый инструмент сохраняется и занимает место в лимите. "
        "Удаление освобождает одно место."
    ),
}


def _state(context):
    return context.user_data.get(FLOW_KEY) or context.chat_data.get(FLOW_KEY)


def _set_state(context, value):
    context.user_data[FLOW_KEY] = value
    context.chat_data[FLOW_KEY] = value


def _clear_state(context):
    context.user_data.pop(FLOW_KEY, None)
    context.chat_data.pop(FLOW_KEY, None)


def _instrument_label(config: dict) -> str:
    return (
        f"{config['symbol']} · "
        f"{EXCHANGE_LABELS.get(config['exchange'], config['exchange'])}"
    )


def format_instruments_text(chat_id: int, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    instruments = list(user.get("symbols", {}).values())
    lines = [
        "📉 <b>FVG-уведомления</b>",
        "",
        "Таймфрейм: <b>15 минут</b>",
        f"Добавлено инструментов: <b>{len(instruments)} из {MAX_SYMBOLS_PER_USER}</b>",
    ]
    if not instruments:
        lines.extend(("", "У вас пока нет инструментов. Добавьте биржу и торговую пару."))
        return "\n".join(lines)
    for index, config in enumerate(instruments, 1):
        status = "✅" if config.get("enabled", True) else "⏸️"
        lines.extend((
            "",
            f"{index}. {status} <b>{escape(config['symbol'])}</b> · "
            f"{escape(EXCHANGE_LABELS.get(config['exchange'], config['exchange']))}",
            "   Подтверждение: после закрытия 15м свечи",
        ))
    return "\n".join(lines)


def build_instruments_menu(chat_id: int, settings=None) -> InlineKeyboardMarkup:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    rows = []
    for config in user.get("symbols", {}).values():
        status = "✅" if config.get("enabled", True) else "⏸️"
        rows.append([
            InlineKeyboardButton(
                f"{status} {_instrument_label(config)}",
                callback_data=f"fvg15:detail:{config['exchange']}:{config['symbol']}",
            )
        ])
    if len(user.get("symbols", {})) < MAX_SYMBOLS_PER_USER:
        rows.append([InlineKeyboardButton("➕ Добавить инструмент", callback_data="fvg15:add")])
    rows.extend((
        [InlineKeyboardButton("❓ FAQ", callback_data="fvg15:faq:main")],
        [InlineKeyboardButton("⬅️ Настройки FVG", callback_data="menu:fvg-settings")],
    ))
    return InlineKeyboardMarkup(rows)


def build_exchange_menu() -> InlineKeyboardMarkup:
    rows = []
    for index in range(0, len(EXCHANGE_ORDER), 2):
        rows.append([
            InlineKeyboardButton(
                EXCHANGE_LABELS[exchange],
                callback_data=f"fvg15:exchange:{exchange}",
            )
            for exchange in EXCHANGE_ORDER[index:index + 2]
        ])
    rows.append([InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")])
    return InlineKeyboardMarkup(rows)


def build_confirmation_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="fvg15:confirm")],
        [InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")],
    ])


def format_confirmation_text(state: dict) -> str:
    return (
        "🔎 <b>Проверьте настройки</b>\n\n"
        f"Биржа: {escape(exchange_label(state['exchange']))}\n"
        f"Инструмент: <code>{escape(state['symbol'])}</code>\n"
        "Таймфрейм: 15 минут\n"
        "Уведомления: включены\n\n"
        "Сигнал будет отправлен только после закрытия 15-минутной свечи, "
        "подтверждающей FVG."
    )


def format_detail_text(chat_id: int, exchange: str, symbol: str, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    config = settings.user(chat_id).get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        raise ValueError("Инструмент уже удалён или не найден.")
    return (
        f"📌 <b>{escape(config['symbol'])} · {escape(exchange_label(config['exchange']))}</b>\n\n"
        "Таймфрейм: 15 минут\n"
        f"Уведомления: {'включены' if config.get('enabled', True) else 'выключены'}\n"
        "Тип сигнала: только подтверждённый FVG"
    )


def build_detail_menu(chat_id: int, exchange: str, symbol: str, settings=None):
    settings = settings or FvgAlertSettings()
    config = settings.user(chat_id).get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        return build_instruments_menu(chat_id, settings)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⏸️ Отключить уведомления" if config.get("enabled", True) else "▶️ Включить уведомления",
            callback_data=f"fvg15:toggle:{exchange}:{symbol}",
        )],
        [InlineKeyboardButton("🗑 Удалить инструмент", callback_data=f"fvg15:delete:{exchange}:{symbol}")],
        [InlineKeyboardButton("⬅️ Мои инструменты", callback_data="fvg15:open")],
    ])


def build_delete_menu(exchange: str, symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Удалить", callback_data=f"fvg15:delete-confirm:{exchange}:{symbol}")],
        [InlineKeyboardButton("Отмена", callback_data=f"fvg15:detail:{exchange}:{symbol}")],
    ])


def build_faq_menu(section="main") -> InlineKeyboardMarkup:
    rows = []
    if section == "main":
        rows.extend((
            [InlineKeyboardButton("Как добавить инструмент", callback_data="fvg15:faq:add")],
            [InlineKeyboardButton("FVG и подтверждение", callback_data="fvg15:faq:confirmed")],
            [InlineKeyboardButton("Лимиты и настройки", callback_data="fvg15:faq:limits")],
        ))
    else:
        rows.append([InlineKeyboardButton("⬅️ Все вопросы", callback_data="fvg15:faq:main")])
    rows.append([InlineKeyboardButton("⬅️ FVG-инструменты", callback_data="fvg15:open")])
    return InlineKeyboardMarkup(rows)


async def _edit(message, text, markup):
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def show_fvg_instruments(message, chat_id: int, *, edit=False):
    settings = FvgAlertSettings()
    text = format_instruments_text(chat_id, settings)
    markup = build_instruments_menu(chat_id, settings)
    if edit:
        await _edit(message, text, markup)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML")


@authorized
async def fvg_instrument_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    chat_id = update.effective_chat.id
    settings = FvgAlertSettings()

    if action in {"open", "cancel"}:
        _clear_state(context)
        await show_fvg_instruments(query.message, chat_id, edit=True)
        return
    if action == "add":
        if len(settings.user(chat_id).get("symbols", {})) >= MAX_SYMBOLS_PER_USER:
            await _edit(
                query.message,
                "⚠️ <b>Достигнут лимит инструментов</b>\n\n"
                f"Можно отслеживать не более {MAX_SYMBOLS_PER_USER} инструментов. "
                "Удалите один из добавленных инструментов.",
                build_instruments_menu(chat_id, settings),
            )
            return
        _set_state(context, {"stage": "exchange"})
        await _edit(query.message, "🏦 <b>Выберите биржу</b>", build_exchange_menu())
        return
    if action == "exchange" and len(parts) == 3:
        exchange = parts[2]
        _set_state(context, {"stage": "symbol", "exchange": exchange})
        await _edit(
            query.message,
            f"🔎 <b>{escape(exchange_label(exchange))}: торговая пара</b>\n\n"
            "Введите BTC, BTCUSDT или BTC/USDT одним сообщением.",
            InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")]]),
        )
        return
    if action == "confirm":
        state = _state(context)
        if not state or state.get("stage") != "confirm":
            await query.message.reply_text("Эта кнопка устарела. Откройте добавление инструмента ещё раз.")
            return
        try:
            settings.add_instrument(
                chat_id,
                state["exchange"],
                state["symbol"],
                ("15m",),
            )
        except ValueError as error:
            await query.message.reply_text(str(error))
            return
        exchange, symbol = state["exchange"], state["symbol"]
        _clear_state(context)
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
        return
    if action == "faq" and len(parts) == 3:
        section = parts[2] if parts[2] in FAQ_TEXTS else "main"
        _clear_state(context)
        await _edit(query.message, FAQ_TEXTS[section], build_faq_menu(section))
        return
    if len(parts) != 4:
        await query.message.reply_text("Эта кнопка устарела. Откройте настройки FVG ещё раз.")
        return

    exchange, symbol = parts[2], parts[3]
    key = instrument_key(exchange, symbol)
    if key not in settings.user(chat_id).get("symbols", {}):
        await show_fvg_instruments(query.message, chat_id, edit=True)
        return
    if action == "detail":
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
    elif action == "toggle":
        config = settings.user(chat_id)["symbols"][key]
        settings.set_instrument_enabled(chat_id, key, not config.get("enabled", True))
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
    elif action == "delete":
        await _edit(
            query.message,
            f"🗑 <b>Удалить инструмент?</b>\n\n"
            f"{escape(symbol)} на {escape(exchange_label(exchange))} будет удалён из отслеживания.",
            build_delete_menu(exchange, symbol),
        )
    elif action == "delete-confirm":
        settings.remove_instrument(chat_id, key)
        _clear_state(context)
        await show_fvg_instruments(query.message, chat_id, edit=True)


@authorized
async def receive_fvg_instrument_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = _state(context)
    if not state or state.get("stage") != "symbol":
        return
    try:
        symbol = normalize_fvg_symbol(update.effective_message.text)
    except ValueError as error:
        await update.effective_message.reply_text(f"Не получилось: {error}")
        return
    settings = FvgAlertSettings()
    chat_id = update.effective_chat.id
    key = instrument_key(state["exchange"], symbol)
    if key in settings.user(chat_id).get("symbols", {}):
        await update.effective_message.reply_text("Этот инструмент уже добавлен.")
        return
    try:
        exists = await asyncio.to_thread(
            PublicCandleClient().symbol_exists,
            state["exchange"],
            symbol,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        await update.effective_message.reply_text("Не удалось получить данные от биржи. Попробуйте позже.")
        return
    if not exists:
        await update.effective_message.reply_text(
            "Инструмент не найден на выбранной бирже. Проверьте название и попробуйте ещё раз."
        )
        return
    state.update({"stage": "confirm", "symbol": symbol, "timeframes": ["15m"]})
    _set_state(context, state)
    await update.effective_message.reply_text(
        format_confirmation_text(state),
        reply_markup=build_confirmation_menu(),
        parse_mode="HTML",
    )


def build_fvg_instrument_handlers():
    return (
        CallbackQueryHandler(fvg_instrument_callback, pattern=r"^fvg15:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_fvg_instrument_symbol),
    )


__all__ = [
    "FAQ_TEXTS",
    "FLOW_KEY",
    "build_fvg_instrument_handlers",
    "build_instruments_menu",
    "format_instruments_text",
    "show_fvg_instruments",
]
