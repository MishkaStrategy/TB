"""Compact button-driven UI for confirmed 15m FVG price and size filters."""

import re
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from alerts.fvg_store import FvgAlertSettings
from exchanges.funding import EXCHANGE_LABELS
from handlers.auth import authorized


FILTER_INPUT_KEY = "waiting_fvg_filter_range"


def parse_filter_range(text: str) -> tuple[str | None, str | None]:
    value = text.strip().lower().replace(" ", "").replace(",", ".")
    value = value.removeprefix("от").replace("до", "-")
    value = value.replace("$", "").replace("%", "").replace("—", "-").replace("–", "-")
    if value in {"нет", "без", "-"}:
        return None, None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)?[-…:](\d+(?:\.\d+)?)?", value)
    if not match or not any(match.groups()):
        raise ValueError("Отправь диапазон, например 60000-90000, 60000- или -90000.")
    minimum, maximum = match.groups()
    try:
        low = Decimal(minimum) if minimum else None
        high = Decimal(maximum) if maximum else None
    except InvalidOperation as error:
        raise ValueError("Не удалось распознать числа диапазона.") from error
    if low is not None and high is not None and low > high:
        raise ValueError("Первое число не может быть больше второго.")
    return minimum, maximum


def parse_size_minimum(text: str) -> str:
    value = text.strip().lower().replace(" ", "").replace(",", ".")
    value = value.replace("$", "").replace("%", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("Отправь одно минимальное значение, например 0,1 или 10.")
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("Минимальное значение должно быть неотрицательным числом.")
    return value


def _instrument(settings: FvgAlertSettings, chat_id: int, key: str) -> dict:
    return settings.user(chat_id).get("symbols", {}).get(key, {})


def _filter(settings: FvgAlertSettings, chat_id: int, kind: str, symbol: str) -> dict:
    key = "price_filter" if kind == "price" else "size_filter"
    return _instrument(settings, chat_id, symbol).get(key, {})


def _instrument_label(key: str, config: dict) -> str:
    symbol = config.get("symbol", key)
    exchange = config.get("exchange")
    if not exchange:
        return symbol
    return f"{symbol} · {EXCHANGE_LABELS.get(exchange, exchange)}"


def _kind_name(kind: str) -> str:
    return "цены" if kind == "price" else "размера"


def parse_filter_callback(data: str) -> tuple[str, str, str | None]:
    parts = data.split(":")
    if len(parts) not in {3, 4} or parts[0] != "fvg-filter":
        raise ValueError("Некорректная кнопка фильтра FVG")
    _, action, kind, *tail = parts
    if kind not in {"price", "size"}:
        raise ValueError("Неизвестный тип фильтра FVG")
    symbol = tail[0] if tail else None
    if action != "open" and not symbol:
        raise ValueError("В кнопке фильтра не указан инструмент")
    return action, kind, symbol


def build_filter_symbol_menu(chat_id: int, kind: str, settings=None):
    settings = settings or FvgAlertSettings()
    symbols = settings.user(chat_id).get("symbols", {})
    rows = []
    key = "price_filter" if kind == "price" else "size_filter"
    for instrument_key, config in symbols.items():
        mark = "✅" if config.get(key, {}).get("enabled", False) else "⏸️"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {_instrument_label(instrument_key, config)}",
                callback_data=f"fvg-filter:select:{kind}:{instrument_key}",
            )
        ])
    rows.append([InlineKeyboardButton("⬅️ Настройки FVG", callback_data="menu:fvg-settings")])
    return InlineKeyboardMarkup(rows)


def build_filter_menu(chat_id: int, kind: str, symbol: str, settings=None):
    settings = settings or FvgAlertSettings()
    config = _filter(settings, chat_id, kind, symbol)

    def mark(value):
        return "✅" if value else "⏸️"

    rows = [
        [InlineKeyboardButton(
            "✅ Фильтр включён" if config.get("enabled", False) else "⏸️ Фильтр выключен",
            callback_data=f"fvg-filter:toggle:{kind}:{symbol}",
        )],
        [
            InlineKeyboardButton(
                f"{mark(config.get('apply_to_bullish', True))} 🐮 Бычьи",
                callback_data=f"fvg-filter:bull:{kind}:{symbol}",
            ),
            InlineKeyboardButton(
                f"{mark(config.get('apply_to_bearish', True))} 🐻 Медвежьи",
                callback_data=f"fvg-filter:bear:{kind}:{symbol}",
            ),
        ],
    ]
    if kind == "size":
        unit = config.get("unit", "USD")
        rows.append([
            InlineKeyboardButton(
                f"{'✅' if unit == 'PERCENT' else '▫️'} Проценты",
                callback_data=f"fvg-filter:percent:{kind}:{symbol}",
            ),
            InlineKeyboardButton(
                f"{'✅' if unit == 'USD' else '▫️'} Доллары",
                callback_data=f"fvg-filter:usd:{kind}:{symbol}",
            ),
        ])
    rows.extend([
        [InlineKeyboardButton(
            "✏️ Ввести минимум" if kind == "size" else "✏️ Ввести диапазон",
            callback_data=f"fvg-filter:range:{kind}:{symbol}",
        )],
        [InlineKeyboardButton("⬅️ Инструменты", callback_data=f"fvg-filter:open:{kind}")],
        [InlineKeyboardButton("⚙️ Настройки FVG", callback_data="menu:fvg-settings")],
    ])
    return InlineKeyboardMarkup(rows)


def format_filter_text(chat_id: int, kind: str, symbol: str, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    instrument = _instrument(settings, chat_id, symbol)
    config = _filter(settings, chat_id, kind, symbol)
    suffix = ""
    if kind == "size":
        suffix = "%" if config.get("unit") == "PERCENT" else "$"
    minimum = config.get("min") or "без минимума"
    maximum = config.get("max") or "без максимума"
    value_text = (
        f"Минимальный размер: {minimum}{suffix}"
        if kind == "size"
        else f"Диапазон: {minimum} — {maximum}"
    )
    title = _instrument_label(symbol, instrument)
    return (
        f"{'💰' if kind == 'price' else '📏'} Фильтр {_kind_name(kind)} · {title}\n\n"
        f"Статус: {'✅ включён' if config.get('enabled', False) else '⏸️ выключен'}\n"
        f"{value_text}\n"
        "Фильтр применяется только к подтверждённым FVG на закрытых 15м свечах."
    )


async def _show_picker(message, chat_id: int, kind: str, *, edit=False):
    settings = FvgAlertSettings()
    symbols = settings.user(chat_id).get("symbols", {})
    text = f"Выбери инструмент для фильтра {_kind_name(kind)}:"
    if not symbols:
        text = "Сначала добавьте инструмент в разделе «📌 Инструменты»."
    method = message.edit_text if edit else message.reply_text
    await method(text, reply_markup=build_filter_symbol_menu(chat_id, kind, settings))


@authorized
async def fvg_filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = "size" if update.effective_message.text.startswith("/fvg_size") else "price"
    context.user_data.pop(FILTER_INPUT_KEY, None)
    context.chat_data.pop(FILTER_INPUT_KEY, None)
    await _show_picker(update.effective_message, update.effective_chat.id, kind)


def _save_filter(settings, chat_id, kind, symbol, config, **changes):
    values = {**config, **changes}
    arguments = (
        chat_id,
        symbol,
        values.get("min"),
        values.get("max"),
    )
    options = dict(
        enabled=values.get("enabled", False),
        apply_to_pre=False,
        apply_to_confirmed=True,
        apply_to_bullish=values.get("apply_to_bullish", True),
        apply_to_bearish=values.get("apply_to_bearish", True),
    )
    if kind == "price":
        settings.set_price_filter(*arguments, **options)
    else:
        settings.set_size_filter(
            chat_id,
            symbol,
            values.get("min"),
            None,
            unit=values.get("unit", "USD"),
            **options,
        )


@authorized
async def fvg_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("menu:fvg-"):
        kind = query.data.removeprefix("menu:fvg-")
        context.user_data.pop(FILTER_INPUT_KEY, None)
        context.chat_data.pop(FILTER_INPUT_KEY, None)
        await _show_picker(query.message, update.effective_chat.id, kind, edit=True)
        return
    try:
        action, kind, symbol = parse_filter_callback(query.data)
    except ValueError:
        await query.message.reply_text("Эта кнопка устарела. Открой настройки FVG ещё раз.")
        return
    chat_id = update.effective_chat.id
    context.user_data.pop(FILTER_INPUT_KEY, None)
    context.chat_data.pop(FILTER_INPUT_KEY, None)
    if action == "open":
        await _show_picker(query.message, chat_id, kind, edit=True)
        return
    settings = FvgAlertSettings()
    config = _filter(settings, chat_id, kind, symbol)
    if action == "select":
        await query.message.edit_text(
            format_filter_text(chat_id, kind, symbol, settings),
            reply_markup=build_filter_menu(chat_id, kind, symbol, settings),
        )
        return
    if action == "range":
        state = {"kind": kind, "symbol": symbol}
        context.user_data[FILTER_INPUT_KEY] = state
        context.chat_data[FILTER_INPUT_KEY] = state
        if kind == "size":
            example = "0,1" if config.get("unit") == "PERCENT" else "10"
            await query.message.reply_text(
                f"Отправь только минимальный размер одним числом. Например: {example}\n"
                "Отмена: /cancel"
            )
        else:
            await query.message.reply_text(
                "Отправь только диапазон одним сообщением. Например: 60000-90000\n"
                "Без минимума: -90000 · без максимума: 60000- · отмена: /cancel"
            )
        return
    changes = {}
    toggle_keys = {
        "toggle": "enabled",
        "bull": "apply_to_bullish",
        "bear": "apply_to_bearish",
    }
    if action in toggle_keys:
        key = toggle_keys[action]
        changes[key] = not config.get(key, key != "enabled")
    elif action in {"percent", "usd"}:
        changes["unit"] = "PERCENT" if action == "percent" else "USD"
    else:
        await query.message.reply_text("Эта кнопка больше не используется.")
        return
    _save_filter(settings, chat_id, kind, symbol, config, **changes)
    await query.message.edit_text(
        format_filter_text(chat_id, kind, symbol, settings),
        reply_markup=build_filter_menu(chat_id, kind, symbol, settings),
    )


@authorized
async def receive_filter_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get(FILTER_INPUT_KEY) or context.chat_data.get(FILTER_INPUT_KEY)
    if not state:
        return
    try:
        kind, symbol = state["kind"], state["symbol"]
        if kind == "size":
            minimum, maximum = parse_size_minimum(update.effective_message.text), None
        else:
            minimum, maximum = parse_filter_range(update.effective_message.text)
        settings = FvgAlertSettings()
        chat_id = update.effective_chat.id
        config = _filter(settings, chat_id, kind, symbol)
        _save_filter(
            settings,
            chat_id,
            kind,
            symbol,
            config,
            min=minimum,
            max=maximum,
            enabled=True,
        )
    except ValueError as error:
        await update.effective_message.reply_text(
            f"Не получилось: {error}\nПопробуй ещё раз или /cancel."
        )
        return
    context.user_data.pop(FILTER_INPUT_KEY, None)
    context.chat_data.pop(FILTER_INPUT_KEY, None)
    await update.effective_message.reply_text(
        "✅ Минимальный размер сохранён. Статус: фильтр включён."
        if kind == "size"
        else "✅ Диапазон сохранён. Статус: фильтр включён.",
        reply_markup=build_filter_menu(chat_id, kind, symbol, settings),
    )


@authorized
async def cancel_filter_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(FILTER_INPUT_KEY, None)
    context.chat_data.pop(FILTER_INPUT_KEY, None)
    await update.effective_message.reply_text("Ввод диапазона отменён.")


def build_fvg_filter_handlers():
    return (
        CommandHandler(("fvg_price", "fvg_size"), fvg_filter_command),
        CallbackQueryHandler(fvg_filter_callback, pattern=r"^fvg-filter:"),
        CallbackQueryHandler(fvg_filter_callback, pattern=r"^menu:fvg-(price|size)$"),
        CommandHandler("cancel", cancel_filter_input),
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_filter_range),
    )
