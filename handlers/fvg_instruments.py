"""Button-driven FVG instrument management and FAQ screens."""

from __future__ import annotations

import asyncio
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from alerts.fvg_store import FvgAlertSettings, instrument_key
from config import MAX_SYMBOLS_PER_USER
from exchanges.funding import EXCHANGE_LABELS, EXCHANGE_ORDER, exchange_label
from exchanges.fvg_candles import (
    CONFIRMED_TIMEFRAMES,
    PublicCandleClient,
    is_bitcoin_symbol,
    normalize_fvg_symbol,
)
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
        "Выберите раздел. Здесь объясняется, когда приходит сигнал, почему "
        "пред-FVG доступен только для Bitcoin и как считается лимит инструментов."
    ),
    "add": (
        "➕ <b>Как добавить инструмент</b>\n\n"
        "1. Выберите биржу.\n"
        "2. Введите пару: BTC, BTCUSDT или BTC/USDT.\n"
        "3. Отметьте таймфреймы.\n"
        "4. Сохраните настройки.\n\n"
        "Одинаковая пара на разных биржах считается разными инструментами, "
        "потому что свечи и котировки могут отличаться."
    ),
    "confirmed": (
        "✅ <b>FVG и подтверждение</b>\n\n"
        "FVG — ценовой дисбаланс между тремя свечами. Обычное уведомление "
        "приходит только после закрытия свечи C, которая подтверждает зону.\n\n"
        "Доступные таймфреймы: 15 минут, 1 час, 4 часа и 1 день. "
        "Одна и та же подтверждённая зона повторно не отправляется."
    ),
    "pre": (
        "⏳ <b>Пред-FVG</b>\n\n"
        "Пред-FVG предупреждает о возможной 15-минутной зоне до закрытия "
        "свечи C. Эта функция доступна только для пар с базовым активом BTC.\n\n"
        "Для ETH, SOL и остальных активов уведомление приходит исключительно "
        "после подтверждения закрытой свечой."
    ),
    "limits": (
        "⚙️ <b>Лимиты и настройки</b>\n\n"
        f"Можно отслеживать не более {MAX_SYMBOLS_PER_USER} инструментов. "
        "Несколько таймфреймов одной пары занимают одно место.\n\n"
        "Отключённый инструмент сохраняет настройки и продолжает занимать "
        "место. После удаления место освобождается."
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
    return f"{config['symbol']} · {EXCHANGE_LABELS.get(config['exchange'], config['exchange'])}"


def format_instruments_text(chat_id: int, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    instruments = list(user.get("symbols", {}).values())
    lines = [
        "📉 <b>FVG-уведомления</b>",
        "",
        f"Добавлено инструментов: <b>{len(instruments)} из {MAX_SYMBOLS_PER_USER}</b>",
    ]
    if not instruments:
        lines.extend((
            "",
            "У вас пока нет инструментов. Добавьте биржу, торговую пару и таймфреймы.",
        ))
        return "\n".join(lines)

    for index, config in enumerate(instruments, 1):
        status = "✅" if config.get("enabled", True) else "⏸️"
        lines.extend((
            "",
            f"{index}. {status} <b>{escape(config['symbol'])}</b> · "
            f"{escape(EXCHANGE_LABELS.get(config['exchange'], config['exchange']))}",
            f"   Таймфреймы: {_display_timeframes(config.get('timeframes'))}",
        ))
        if is_bitcoin_symbol(config["symbol"]):
            lines.append(
                "   Пред-FVG: "
                + ("включён" if user.get("notify_pre_fvg", False) else "выключен")
            )
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
                callback_data=(
                    f"fvg-inst:detail:{config['exchange']}:{config['symbol']}"
                ),
            )
        ])
    if len(user.get("symbols", {})) < MAX_SYMBOLS_PER_USER:
        rows.append([
            InlineKeyboardButton("➕ Добавить инструмент", callback_data="fvg-inst:add")
        ])
    rows.extend((
        [InlineKeyboardButton("❓ FAQ", callback_data="fvg-inst:faq:main")],
        [InlineKeyboardButton("⬅️ Настройки FVG", callback_data="menu:fvg-settings")],
    ))
    return InlineKeyboardMarkup(rows)


def build_exchange_menu() -> InlineKeyboardMarkup:
    rows = []
    for index in range(0, len(EXCHANGE_ORDER), 2):
        rows.append([
            InlineKeyboardButton(
                EXCHANGE_LABELS[exchange],
                callback_data=f"fvg-inst:exchange:{exchange}",
            )
            for exchange in EXCHANGE_ORDER[index:index + 2]
        ])
    rows.append([InlineKeyboardButton("Отмена", callback_data="fvg-inst:cancel")])
    return InlineKeyboardMarkup(rows)


def build_timeframe_menu(state: dict) -> InlineKeyboardMarkup:
    selected = set(state.get("timeframes", ()))
    rows = []
    for index in range(0, len(CONFIRMED_TIMEFRAMES), 2):
        row = []
        for timeframe in CONFIRMED_TIMEFRAMES[index:index + 2]:
            mark = "✅" if timeframe in selected else "⬜"
            row.append(InlineKeyboardButton(
                f"{mark} {TIMEFRAME_LABELS[timeframe]}",
                callback_data=f"fvg-inst:tf:{timeframe}",
            ))
        rows.append(row)
    rows.extend((
        [InlineKeyboardButton("Выбрать все", callback_data="fvg-inst:tf-all")],
        [InlineKeyboardButton("Сохранить", callback_data="fvg-inst:save")],
        [InlineKeyboardButton("Отмена", callback_data="fvg-inst:cancel")],
    ))
    return InlineKeyboardMarkup(rows)


def format_timeframe_text(state: dict) -> str:
    action = "Изменение" if state.get("action") == "edit" else "Добавление"
    return (
        f"🕒 <b>{action} FVG-инструмента</b>\n\n"
        f"Биржа: {escape(exchange_label(state['exchange']))}\n"
        f"Инструмент: <code>{escape(state['symbol'])}</code>\n"
        f"Таймфреймы: {_display_timeframes(state.get('timeframes'))}\n\n"
        "Выберите хотя бы один таймфрейм. Уведомление придёт только после "
        "закрытия подтверждающей свечи."
    )


def format_detail_text(chat_id: int, exchange: str, symbol: str, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    config = user.get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        raise ValueError("Инструмент уже удалён или не найден.")
    lines = [
        f"📌 <b>{escape(config['symbol'])} · {escape(exchange_label(config['exchange']))}</b>",
        "",
        f"Таймфреймы: {_display_timeframes(config.get('timeframes'))}",
        f"Уведомления: {'включены' if config.get('enabled', True) else 'выключены'}",
    ]
    if is_bitcoin_symbol(config["symbol"]):
        lines.append(
            "Пред-FVG: "
            + ("включён" if user.get("notify_pre_fvg", False) else "выключен")
        )
    return "\n".join(lines)


def build_detail_menu(chat_id: int, exchange: str, symbol: str, settings=None):
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    config = user.get("symbols", {}).get(instrument_key(exchange, symbol))
    if config is None:
        return build_instruments_menu(chat_id, settings)
    rows = [
        [InlineKeyboardButton(
            "🕒 Изменить таймфреймы",
            callback_data=f"fvg-inst:edit:{exchange}:{symbol}",
        )],
        [InlineKeyboardButton(
            "⏸️ Отключить уведомления" if config.get("enabled", True) else "▶️ Включить уведомления",
            callback_data=f"fvg-inst:toggle:{exchange}:{symbol}",
        )],
    ]
    if is_bitcoin_symbol(symbol):
        rows.append([InlineKeyboardButton(
            "⏳ Выключить пред-FVG" if user.get("notify_pre_fvg", False) else "⏳ Включить пред-FVG",
            callback_data=f"fvg-inst:pre:{exchange}:{symbol}",
        )])
    rows.extend((
        [InlineKeyboardButton(
            "🗑 Удалить инструмент",
            callback_data=f"fvg-inst:delete:{exchange}:{symbol}",
        )],
        [InlineKeyboardButton("⬅️ Мои инструменты", callback_data="fvg-inst:open")],
    ))
    return InlineKeyboardMarkup(rows)


def build_delete_menu(exchange: str, symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Удалить",
            callback_data=f"fvg-inst:delete-confirm:{exchange}:{symbol}",
        )],
        [InlineKeyboardButton(
            "Отмена",
            callback_data=f"fvg-inst:detail:{exchange}:{symbol}",
        )],
    ])


def build_faq_menu(section="main") -> InlineKeyboardMarkup:
    rows = []
    if section == "main":
        rows.extend((
            [InlineKeyboardButton("Как добавить инструмент", callback_data="fvg-inst:faq:add")],
            [InlineKeyboardButton("FVG и подтверждение", callback_data="fvg-inst:faq:confirmed")],
            [InlineKeyboardButton("Пред-FVG", callback_data="fvg-inst:faq:pre")],
            [InlineKeyboardButton("Лимиты и настройки", callback_data="fvg-inst:faq:limits")],
        ))
    else:
        rows.append([InlineKeyboardButton("⬅️ Все вопросы", callback_data="fvg-inst:faq:main")])
    rows.append([InlineKeyboardButton("⬅️ FVG-инструменты", callback_data="fvg-inst:open")])
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

    if action == "open":
        _clear_state(context)
        await show_fvg_instruments(query.message, chat_id, edit=True)
        return
    if action == "cancel":
        _clear_state(context)
        await show_fvg_instruments(query.message, chat_id, edit=True)
        return
    if action == "add":
        if len(settings.user(chat_id).get("symbols", {})) >= MAX_SYMBOLS_PER_USER:
            await _edit(
                query.message,
                "⚠️ <b>Достигнут лимит инструментов</b>\n\n"
                f"Можно отслеживать не более {MAX_SYMBOLS_PER_USER} инструментов. "
                "Удалите один из добавленных инструментов, чтобы добавить новый.",
                build_instruments_menu(chat_id, settings),
            )
            return
        _set_state(context, {"action": "add", "stage": "exchange"})
        await _edit(
            query.message,
            "🏦 <b>Выберите биржу</b>\n\nНа какой бирже отслеживать FVG?",
            build_exchange_menu(),
        )
        return
    if action == "exchange" and len(parts) == 3:
        exchange = parts[2]
        _set_state(context, {
            "action": "add",
            "stage": "symbol",
            "exchange": exchange,
        })
        await _edit(
            query.message,
            f"🔎 <b>{escape(exchange_label(exchange))}: торговая пара</b>\n\n"
            "Введите BTC, BTCUSDT или BTC/USDT одним сообщением.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("Отмена", callback_data="fvg-inst:cancel")]
            ]),
        )
        return
    if action in {"tf", "tf-all", "save"}:
        state = _state(context)
        if not state or state.get("stage") != "timeframes":
            await query.message.reply_text(
                "Эта кнопка устарела. Откройте добавление инструмента ещё раз."
            )
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
                await query.answer("Выберите хотя бы один таймфрейм.", show_alert=True)
                return
            try:
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
        await _edit(
            query.message,
            format_timeframe_text(state),
            build_timeframe_menu(state),
        )
        return
    if action == "faq" and len(parts) == 3:
        section = parts[2] if parts[2] in FAQ_TEXTS else "main"
        _clear_state(context)
        await _edit(query.message, FAQ_TEXTS[section], build_faq_menu(section))
        return

    if len(parts) != 4:
        await query.message.reply_text(
            "Эта кнопка устарела. Откройте настройки FVG ещё раз."
        )
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
        await _edit(
            query.message,
            format_timeframe_text(state),
            build_timeframe_menu(state),
        )
    elif action == "toggle":
        config = settings.user(chat_id)["symbols"][key]
        settings.set_instrument_enabled(chat_id, key, not config.get("enabled", True))
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
    elif action == "pre":
        if not is_bitcoin_symbol(symbol):
            await query.answer("Пред-FVG доступен только для Bitcoin.", show_alert=True)
            return
        settings.set_pre_enabled(
            chat_id,
            not settings.user(chat_id).get("notify_pre_fvg", False),
        )
        await _edit(
            query.message,
            format_detail_text(chat_id, exchange, symbol, settings),
            build_detail_menu(chat_id, exchange, symbol, settings),
        )
    elif action == "delete":
        await _edit(
            query.message,
            f"🗑 <b>Удалить инструмент?</b>\n\n"
            f"{escape(symbol)} на {escape(exchange_label(exchange))} будет удалён. "
            "Все его таймфреймы и фильтры будут удалены.",
            build_delete_menu(exchange, symbol),
        )
    elif action == "delete-confirm":
        settings.remove_instrument(chat_id, key)
        _clear_state(context)
        await show_fvg_instruments(query.message, chat_id, edit=True)


@authorized
async def receive_fvg_instrument_symbol(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
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
        await update.effective_message.reply_text(
            "Не удалось получить список инструментов от биржи. Попробуйте позже."
        )
        return
    if not exists:
        await update.effective_message.reply_text(
            "Инструмент не найден на выбранной бирже. Проверьте название и попробуйте ещё раз."
        )
        return
    state.update({
        "stage": "timeframes",
        "symbol": symbol,
        "timeframes": ["15m"],
    })
    _set_state(context, state)
    await update.effective_message.reply_text(
        format_timeframe_text(state),
        reply_markup=build_timeframe_menu(state),
        parse_mode="HTML",
    )


def build_fvg_instrument_handlers():
    return (
        CallbackQueryHandler(fvg_instrument_callback, pattern=r"^fvg-inst:"),
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_fvg_instrument_symbol,
        ),
    )


__all__ = [
    "FAQ_TEXTS",
    "FLOW_KEY",
    "build_fvg_instrument_handlers",
    "build_instruments_menu",
    "format_instruments_text",
    "show_fvg_instruments",
]
