"""High-level FVG dashboard for the multi-exchange instrument workflow."""

from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes

from alerts.fvg_models import FvgDirection
from alerts.fvg_store import FvgAlertSettings
from config import MAX_SYMBOLS_PER_USER
from exchanges.funding import EXCHANGE_LABELS
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES, is_bitcoin_symbol
from handlers.auth import authorized


TIMEFRAME_SHORT = {
    "15m": "15м",
    "1h": "1ч",
    "4h": "4ч",
    "1d": "1д",
}


def _instrument_values(user: dict) -> list[dict]:
    symbols = user.get("symbols", {})
    if not isinstance(symbols, dict):
        return []
    return [value for value in symbols.values() if isinstance(value, dict)]


def _pre_capable(config: dict) -> bool:
    return bool(
        is_bitcoin_symbol(str(config.get("symbol", "")))
        and "15m" in set(config.get("timeframes") or ())
    )


def dashboard_snapshot(chat_id: int, settings=None) -> dict:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    instruments = _instrument_values(user)
    active = [item for item in instruments if item.get("enabled", True)]
    exchanges = sorted(
        {
            str(item.get("exchange", "bitunix"))
            for item in instruments
            if item.get("exchange")
        },
        key=lambda value: EXCHANGE_LABELS.get(value, value).lower(),
    )
    selected_timeframes = {
        timeframe
        for item in instruments
        for timeframe in (item.get("timeframes") or ())
        if timeframe in CONFIRMED_TIMEFRAMES
    }
    timeframes = [
        timeframe
        for timeframe in CONFIRMED_TIMEFRAMES
        if timeframe in selected_timeframes
    ]
    price_filters = sum(
        bool(item.get("price_filter", {}).get("enabled"))
        for item in instruments
    )
    size_filters = sum(
        bool(item.get("size_filter", {}).get("enabled"))
        for item in instruments
    )
    return {
        "module_enabled": bool(user.get("enabled")),
        "confirmed_enabled": bool(user.get("notify_confirmed_fvg", True)),
        "pre_enabled": bool(user.get("notify_pre_fvg", False)),
        "bullish_enabled": bool(user.get("bullish_enabled", True)),
        "bearish_enabled": bool(user.get("bearish_enabled", True)),
        "instrument_count": len(instruments),
        "active_count": len(active),
        "exchanges": exchanges,
        "timeframes": timeframes,
        "pre_capable": any(_pre_capable(item) for item in instruments),
        "price_filter_count": price_filters,
        "size_filter_count": size_filters,
    }


def _enabled(value: bool) -> str:
    return "✅ включён" if value else "⏸️ выключен"


def _list_or_dash(values) -> str:
    return ", ".join(values) if values else "—"


def format_fvg_dashboard_text(chat_id: int, settings=None) -> str:
    settings = settings or FvgAlertSettings()
    summary = dashboard_snapshot(chat_id, settings)
    exchange_labels = [
        EXCHANGE_LABELS.get(value, value)
        for value in summary["exchanges"]
    ]
    timeframe_labels = [
        TIMEFRAME_SHORT[value]
        for value in summary["timeframes"]
    ]
    signal_parts = [
        "подтверждённые" if summary["confirmed_enabled"] else "без подтверждённых"
    ]
    if summary["pre_capable"]:
        signal_parts.append(
            "пред-FVG BTC" if summary["pre_enabled"] else "пред-FVG BTC выключен"
        )
    else:
        signal_parts.append("пред-FVG недоступен")
    direction_parts = []
    if summary["bullish_enabled"]:
        direction_parts.append("🐮 бычьи")
    if summary["bearish_enabled"]:
        direction_parts.append("🐻 медвежьи")
    if not direction_parts:
        direction_parts.append("выключены")

    lines = [
        "📉 <b>FVG-центр</b>",
        "",
        f"Модуль: {_enabled(summary['module_enabled'])}",
        (
            "Инструменты: "
            f"<b>{summary['instrument_count']} из {MAX_SYMBOLS_PER_USER}</b>"
            f" · активны {summary['active_count']}"
        ),
        f"Биржи: {escape(_list_or_dash(exchange_labels))}",
        f"Таймфреймы: {_list_or_dash(timeframe_labels)}",
        f"Сигналы: {' · '.join(signal_parts)}",
        f"Направления: {' · '.join(direction_parts)}",
        (
            "Фильтры: "
            f"цена {summary['price_filter_count']} · "
            f"размер {summary['size_filter_count']}"
        ),
        "",
    ]
    if summary["instrument_count"]:
        lines.append(
            "Подтверждённые FVG приходят после закрытия свечи C. "
            "Пред-FVG доступен только для BTC на 15-минутном таймфрейме."
        )
    else:
        lines.append(
            "Добавьте первый инструмент: выберите биржу, пару и один или несколько "
            "таймфреймов."
        )
    return "\n".join(lines)


def build_fvg_dashboard_menu(chat_id: int, settings=None) -> InlineKeyboardMarkup:
    settings = settings or FvgAlertSettings()
    summary = dashboard_snapshot(chat_id, settings)
    rows = [[
        InlineKeyboardButton(
            "✅ Модуль включён" if summary["module_enabled"] else "⏸️ Модуль выключен",
            callback_data="fvg-ui:module",
        )
    ]]
    if summary["instrument_count"] < MAX_SYMBOLS_PER_USER:
        rows.append([
            InlineKeyboardButton("➕ Добавить инструмент", callback_data="fvg-inst:add")
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                f"🔒 Лимит {MAX_SYMBOLS_PER_USER}/{MAX_SYMBOLS_PER_USER}",
                callback_data="fvg-ui:limit",
            )
        ])
    rows.extend((
        [InlineKeyboardButton(
            f"📌 Мои инструменты · {summary['active_count']}/{summary['instrument_count']}",
            callback_data="fvg-inst:open",
        )],
        [InlineKeyboardButton(
            "🔔 Сигналы и направления",
            callback_data="fvg-ui:signals",
        )],
        [
            InlineKeyboardButton("💰 Фильтр цены", callback_data="menu:fvg-price"),
            InlineKeyboardButton("📏 Фильтр размера", callback_data="menu:fvg-size"),
        ],
        [
            InlineKeyboardButton("📊 Статистика FVG", callback_data="menu:fvg-stats"),
            InlineKeyboardButton("❓ FAQ по FVG", callback_data="fvg-inst:faq:main"),
        ],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="fvg-ui:main")],
    ))
    return InlineKeyboardMarkup(rows)


def build_fvg_signal_menu(chat_id: int, settings=None) -> InlineKeyboardMarkup:
    settings = settings or FvgAlertSettings()
    summary = dashboard_snapshot(chat_id, settings)

    def mark(value: bool) -> str:
        return "✅" if value else "⏸️"

    rows = [
        [InlineKeyboardButton(
            f"{mark(summary['confirmed_enabled'])} Подтверждённые FVG",
            callback_data="fvg-ui:confirmed",
        )],
    ]
    if summary["pre_capable"]:
        rows.append([InlineKeyboardButton(
            f"{mark(summary['pre_enabled'])} Пред-FVG BTC · 15м",
            callback_data="fvg-ui:pre",
        )])
    else:
        rows.append([InlineKeyboardButton(
            "ℹ️ Пред-FVG: нужен BTC · 15м",
            callback_data="fvg-ui:pre-info",
        )])
    rows.extend((
        [
            InlineKeyboardButton(
                f"{mark(summary['bullish_enabled'])} 🐮 Бычьи",
                callback_data="fvg-ui:bull",
            ),
            InlineKeyboardButton(
                f"{mark(summary['bearish_enabled'])} 🐻 Медвежьи",
                callback_data="fvg-ui:bear",
            ),
        ],
        [InlineKeyboardButton("⬅️ FVG-центр", callback_data="fvg-ui:center")],
    ))
    return InlineKeyboardMarkup(rows)


def format_fvg_signal_text(chat_id: int, settings=None) -> str:
    summary = dashboard_snapshot(chat_id, settings)
    pre_text = (
        _enabled(summary["pre_enabled"])
        if summary["pre_capable"]
        else "нужен BTC с таймфреймом 15м"
    )
    return "\n".join((
        "🔔 <b>FVG-сигналы</b>",
        "",
        f"Подтверждённые: {_enabled(summary['confirmed_enabled'])}",
        f"Пред-FVG BTC: {pre_text}",
        f"Бычьи: {_enabled(summary['bullish_enabled'])}",
        f"Медвежьи: {_enabled(summary['bearish_enabled'])}",
        "",
        "Пред-FVG формируется только для BTC на 15м. Для остальных инструментов "
        "доступны только подтверждённые сигналы после закрытия свечи C.",
    ))


async def _edit(message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def show_fvg_dashboard(message, chat_id: int, *, edit=False) -> None:
    settings = FvgAlertSettings()
    text = format_fvg_dashboard_text(chat_id, settings)
    markup = build_fvg_dashboard_menu(chat_id, settings)
    if edit:
        await _edit(message, text, markup)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def show_fvg_signals(message, chat_id: int, *, edit=True) -> None:
    settings = FvgAlertSettings()
    text = format_fvg_signal_text(chat_id, settings)
    markup = build_fvg_signal_menu(chat_id, settings)
    if edit:
        await _edit(message, text, markup)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML")


@authorized
async def fvg_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    action = query.data.removeprefix("fvg-ui:")
    chat_id = update.effective_chat.id

    if action == "limit":
        await query.answer(
            f"Можно добавить не более {MAX_SYMBOLS_PER_USER} инструментов. "
            "Удалите один инструмент, чтобы освободить место.",
            show_alert=True,
        )
        return
    if action == "pre-info":
        await query.answer(
            "Пред-FVG доступен только для BTC-инструмента с таймфреймом 15 минут.",
            show_alert=True,
        )
        return

    await query.answer()
    settings = FvgAlertSettings()
    if action in {"center", "back"}:
        await show_fvg_dashboard(query.message, chat_id, edit=True)
    elif action == "main":
        from handlers.menu import build_main_menu

        await _edit(
            query.message,
            "Панель управления:",
            build_main_menu(chat_id),
        )
    elif action == "signals":
        await show_fvg_signals(query.message, chat_id, edit=True)
    elif action == "module":
        settings.set_enabled(chat_id, not settings.is_enabled(chat_id))
        await show_fvg_dashboard(query.message, chat_id, edit=True)
    elif action == "confirmed":
        user = settings.user(chat_id)
        settings.set_confirmed_enabled(
            chat_id,
            not user.get("notify_confirmed_fvg", True),
        )
        await show_fvg_signals(query.message, chat_id, edit=True)
    elif action == "pre":
        summary = dashboard_snapshot(chat_id, settings)
        if not summary["pre_capable"]:
            await query.message.reply_text(
                "Пред-FVG доступен только после добавления BTC-инструмента с "
                "таймфреймом 15 минут."
            )
            return
        settings.set_pre_enabled(chat_id, not summary["pre_enabled"])
        await show_fvg_signals(query.message, chat_id, edit=True)
    elif action in {"bull", "bear"}:
        user = settings.user(chat_id)
        direction = (
            FvgDirection.BULLISH
            if action == "bull"
            else FvgDirection.BEARISH
        )
        key = "bullish_enabled" if action == "bull" else "bearish_enabled"
        settings.set_direction_enabled(chat_id, direction, not user.get(key, True))
        await show_fvg_signals(query.message, chat_id, edit=True)


def build_fvg_dashboard_handlers():
    return (
        CallbackQueryHandler(fvg_dashboard_callback, pattern=r"^fvg-ui:"),
    )
