"""Button-driven FVG instrument management with 15m-only exchange data."""

from __future__ import annotations

import asyncio
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from alerts.fvg_store import FvgAlertSettings, instrument_key
from config import MAX_SYMBOLS_PER_USER
from exchanges.funding import EXCHANGE_LABELS, EXCHANGE_ORDER, exchange_label
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES, PublicCandleClient, normalize_fvg_symbol
from handlers.auth import authorized


FLOW_KEY = "fvg_instrument_flow"
TIMEFRAME_LABELS = {
    "15m": "15 минут",
    "1h": "1 час",
    "4h": "4 часа",
    "1d": "1 день",
}
TIMEFRAME_SHORT = {
    "15m": "15м",
    "1h": "1ч",
    "4h": "4ч",
    "1d": "1д",
}
FAQ_TEXTS = {
    "main": (
        "❓ <b>FAQ по FVG</b>\n\n"
        "FVG рассчитывается на 15м, 1ч, 4ч и 1д. Для снижения нагрузки "
        "с бирж загружаются только 15-минутные свечи; старшие таймфреймы "
        "собираются локально."
    ),
    "add": (
        "➕ <b>Как добавить инструмент</b>\n\n"
        "1. Выберите биржу.\n"
        "2. Введите пару: BTC, BTCUSDT или BTC/USDT.\n"
        "3. Отметьте нужные таймфреймы.\n"
        "4. Проверьте настройки и подтвердите сохранение.\n\n"
        "Одинаковая пара на разных биржах считается разными инструментами."
    ),
    "confirmed": (
        "✅ <b>FVG и подтверждение</b>\n\n"
        "Уведомление приходит только после закрытия свечи C, подтверждающей FVG.\n\n"
        "Доступные таймфреймы: 15 минут, 1 час, 4 часа и 1 день. "
        "1ч/4ч/1д строятся внутри бота из закрытых 15-минутных свечей. "
        "Предварительных FVG до закрытия свечи нет."
    ),
    "limits": (
        "⚙️ <b>Лимиты и настройки</b>\n\n"
        f"Можно отслеживать не более {MAX_SYMBOLS_PER_USER} инструментов. "
        "Несколько таймфреймов одной пары занимают одно место.\n\n"
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


def _display_timeframes(values) -> str:
    selected = set(values or ())
    return ", ".join(
        TIMEFRAME_SHORT[item]
        for item in CONFIRMED_TIMEFRAMES
        if item in selected
    ) or "не выбраны"


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
        "Источник данных: <b>только закрытые 15м свечи</b>",
        "Расчёт FVG: <b>15м / 1ч / 4ч / 1д</b>",
        f"Добавлено инструментов: <b>{len(instruments)} из {MAX_SYMBOLS_PER_USER}</b>",
    ]
    if not instruments:
        lines.extend(("", "У вас пока нет инструментов. Добавьте биржу, пару и таймфреймы."))
        return "\n".join(lines)
    for index, config in enumerate(instruments, 1):
        status = "✅" if config.get("enabled", True) else "⏸️"
        lines.extend((
            "",
            f"{index}. {status} <b>{escape(config['symbol'])}</b> · "
            f"{escape(EXCHANGE_LABELS.get(config['exchange'], config['exchange']))}",
            f"   Таймфреймы: {_display_timeframes(config.get('timeframes'))}",
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


def build_timeframe_menu(state: dict) -> InlineKeyboardMarkup:
    selected = set(state.get("timeframes", ()))
    rows = []
    for index in range(0, len(CONFIRMED_TIMEFRAMES), 2):
        row = []
        for timeframe in CONFIRMED_TIMEFRAMES[index:index + 2]:
            mark = "✅" if timeframe in selected else "⬜"
            row.append(
                InlineKeyboardButton(
                    f"{mark} {TIMEFRAME_LABELS[timeframe]}",
                    callback_data=f"fvg15:tf:{timeframe}",
                )
            )
        rows.append(row)
    rows.extend((
        [InlineKeyboardButton("Выбрать все", callback_data="fvg15:tf-all")],
        [InlineKeyboardButton("Продолжить", callback_data="fvg15:save")],
        [InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")],
    ))
    return InlineKeyboardMarkup(rows)


def build_confirmation_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="fvg15:confirm")],
        [InlineKeyboardButton("✏️ Изменить", callback_data="fvg15:change")],
        [InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")],
    ])


def format_timeframe_text(state: dict) -> str:
    action = "Изменение" if state.get("action") == "edit" else "Добавление"
    return (
        f"🕒 <b>{action} FVG-инструмента</b>\n\n"
        f"Биржа: {escape(exchange_label(state['exchange']))}\n"
        f"Инструмент: <code>{escape(state['symbol'])}</code>\n"
        f"Таймфреймы: {_display_timeframes(state.get('timeframes'))}\n\n"
        "Выберите хотя бы один таймфрейм. Старшие свечи будут собраны "
        "локально из 15-минутных данных."
    )


def format_confirmation_text(state: dict) -> str:
    action = "изменение" if state.get("action") == "edit" else "добавление"
    return (
        "🔎 <b>Проверьте настройки</b>\n\n"
        f"Действие: {action}\n"
        f"Биржа: {escape(exchange_label(state['exchange']))}\n"
        f"Инструмент: <code>{escape(state['symbol'])}</code>\n"
        f"Таймфреймы: {_display_timeframes(state.get('timeframes'))}\n"
        "Уведомления: включены\n\n"
        "Сигнал отправляется только после закрытия подтверждающей свечи."
    )


def format_detail_text(chat_id: int, exchange: str, symbol: str, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    config = settings.user(chat_id).get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        raise ValueError("Инструмент уже удалён или не найден.")
    return (
        f"📌 <b>{escape(config['symbol'])} · {escape(exchange_label(config['exchange']))}</b>\n\n"
        f"Таймфреймы: {_display_timeframes(config.get('timeframes'))}\n"
        f"Уведомления: {'включены' if config.get('enabled', True) else 'выключены'}\n"
        "Источник свечей: только 15м\n"
        "Тип сигнала: только подтверждённый FVG"
    )


def build_detail_menu(chat_id: int, exchange: str, symbol: str, settings=None):
    settings = settings or FvgAlertSettings()
    config = settings.user(chat_id).get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        return build_instruments_menu(chat_id, settings)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🕒 Изменить таймфреймы",
            callback_data=f"fvg15:edit:{exchange}:{symbol}",
        )],
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


def _persist_state(settings: FvgAlertSettings, chat_id: int, state: dict) -> None:
    if state.get("action") == "edit":
        settings.update_instrument_timeframes(
            chat_id,
            instrument_key(state["exchange"], state["symbol"]),
            state["timeframes"],
        )
    else:
        settings.add_instrument(
            chat_id,
            state["exchange"],
            state["symbol"],
            state["timeframes"],
        )


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
        _set_state(context, {"action": "add", "stage": "exchange"})
        await _edit(query.message, "🏦 <b>Выберите биржу</b>", build_exchange_menu())
        return

    if action == "exchange" and len(parts) == 3:
        exchange = parts[2]
        _set_state(context, {"action": "add", "stage": "symbol", "exchange": exchange})
        await _edit(
            query.message,
            f"🔎 <b>{escape(exchange_label(exchange))}: торговая пара</b>\n\n"
            "Введите BTC, BTCUSDT или BTC/USDT одним сообщением.",
            InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="fvg15:cancel")]]),
        )
        return

    if action in {"tf", "tf-all", "save"}:
        state = _state(context)
        if not state or state.get("stage") != "timeframes":
            await query.message.reply_text("Эта кнопка устарела. Откройте инструмент ещё раз.")
            return
        if action == "tf" and len(parts) == 3:
            timeframe = parts[2]
            selected = set(state.get("timeframes", ()))
            if timeframe in selected:
                selected.remove(timeframe)
            elif timeframe in CONFIRMED_TIMEFRAMES:
                selected.add(timeframe)
            state["timeframes"] = [
                item for item in CONFIRMED_TIMEFRAMES if item in selected
            ]
            _set_state(context, state)
        elif action == "tf-all":
            state["timeframes"] = list(CONFIRMED_TIMEFRAMES)
            _set_state(context, state)
        elif action == "save":
            if not state.get("timeframes"):
                await query.message.reply_text("Выберите хотя бы один таймфрейм.")
                return
            state["stage"] = "confirm"
            _set_state(context, state)
            await _edit(query.message, format_confirmation_text(state), build_confirmation_menu())
            return
        await _edit(query.message, format_timeframe_text(state), build_timeframe_menu(state))
        return

    if action in {"confirm", "change"}:
        state = _state(context)
        if not state or state.get("stage") != "confirm":
            await query.message.reply_text("Эта кнопка устарела. Откройте инструмент ещё раз.")
            return
        if action == "change":
            state["stage"] = "timeframes"
            _set_state(context, state)
            await _edit(query.message, format_timeframe_text(state), build_timeframe_menu(state))
            return
        try:
            _persist_state(settings, chat_id, state)
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
        _clear_state(context)
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
    elif action == "edit":
        config = settings.user(chat_id)["symbols"][key]
        state = {
            "action": "edit",
            "stage": "timeframes",
            "exchange": exchange,
            "symbol": symbol,
            "timeframes": list(config.get("timeframes", ("15m",))),
        }
        _set_state(context, state)
        await _edit(query.message, format_timeframe_text(state), build_timeframe_menu(state))
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
            f"{escape(symbol)} на {escape(exchange_label(exchange))} будет удалён вместе с настройками таймфреймов.",
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
        await update.effective_message.reply_text(
            "Этот инструмент уже добавлен. Измените его таймфреймы в настройках."
        )
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
    state.update({"stage": "timeframes", "symbol": symbol, "timeframes": ["15m"]})
    _set_state(context, state)
    await update.effective_message.reply_text(
        format_timeframe_text(state),
        reply_markup=build_timeframe_menu(state),
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
    "TIMEFRAME_LABELS",
    "build_confirmation_menu",
    "build_fvg_instrument_handlers",
    "build_instruments_menu",
    "build_timeframe_menu",
    "format_confirmation_text",
    "format_instruments_text",
    "format_timeframe_text",
    "show_fvg_instruments",
]
