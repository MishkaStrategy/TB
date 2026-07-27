"""Multi-exchange funding leaderboard, symbol check, and Telegram callbacks."""

from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal, InvalidOperation
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from exchanges.funding import (
    DEFAULT_EXCHANGE,
    EXCHANGE_LABELS,
    EXCHANGE_ORDER,
    PublicFundingClient,
    exchange_label,
    normalize_exchange,
    normalize_exchanges,
)
from handlers.auth import authorized

LOGGER = logging.getLogger(__name__)
PAGE_SIZE = 10
TOP_LIMIT = 50
CACHE_KEY = "funding_rates_by_exchange"
VIEW_KEY = "funding_view_exchange"
CHECK_INPUT_KEY = "waiting_funding_check_symbol"
ALERT_INPUT_KEY = "waiting_funding_alert_value"


def _decimal(item, *keys):
    for key in keys:
        try:
            value = Decimal(str(item.get(key)))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if value.is_finite():
            return value
    return None


def normalize_funding_symbol(value) -> str:
    """Normalize BTC, BTC/USDT, BTC-USDT, or BTC_USDT to BTCUSDT."""
    compact = re.sub(r"[\s/_-]+", "", str(value or "").strip().upper())
    if compact and not compact.endswith("USDT"):
        compact += "USDT"
    if not re.fullmatch(r"[A-Z0-9]{1,20}USDT", compact):
        raise ValueError("Введите инструмент, например BTCUSDT или BTC/USDT.")
    return compact


def top_funding_rates(rates, limit=TOP_LIMIT):
    parsed = []
    for item in rates:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        rate = _decimal(item, "fundingRate", "funding_rate", "rate")
        change = _decimal(item, "priceChange24h")
        if rate is not None:
            parsed.append((str(item["symbol"]), rate, change))
    positive = sorted(
        (item for item in parsed if item[1] > 0),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]
    negative = sorted(
        (item for item in parsed if item[1] < 0),
        key=lambda item: item[1],
    )[:limit]
    return positive, negative


def page_count(rates):
    positive, negative = top_funding_rates(rates)
    longest = max(len(positive), len(negative))
    return max(1, (longest + PAGE_SIZE - 1) // PAGE_SIZE)


def _table(title, items, sign, start):
    lines = [title]
    if not items:
        return "\n".join((*lines, "Нет данных"))
    lines.append("<code> #  Инструмент    Фандинг    Цена 24ч</code>")
    for index, (symbol, rate, change) in enumerate(items, start + 1):
        change_text = "н/д" if change is None else f"{change:+.2f}%"
        lines.append(
            f"<code>{index:>2}. {escape(symbol[:16]):<12} "
            f"{sign}{abs(rate):.4f}% {change_text:>9}</code>"
        )
    return "\n".join(lines)


def format_funding_rates(rates, page=0, exchange=DEFAULT_EXCHANGE):
    exchange = normalize_exchange(exchange)
    positive, negative = top_funding_rates(rates)
    pages = page_count(rates)
    page = min(max(int(page), 0), pages - 1)
    start = page * PAGE_SIZE
    return "\n\n".join((
        f"💸 <b>Фандинг {escape(exchange_label(exchange))}</b>\n"
        "Текущая ставка и изменение цены за 24 часа.\n"
        f"Страница {page + 1} из {pages} · топ-50 в каждую сторону",
        _table(
            "🟢 <b>Положительный фандинг</b>",
            positive[start:start + PAGE_SIZE],
            "+",
            start,
        ),
        _table(
            "🔴 <b>Отрицательный фандинг</b>",
            negative[start:start + PAGE_SIZE],
            "−",
            start,
        ),
    ))


def _symbol_item(rates, symbol):
    if not isinstance(rates, list):
        return None
    return next(
        (
            item
            for item in rates
            if isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol
        ),
        None,
    )


def format_symbol_funding(symbol, snapshot):
    symbol = normalize_funding_symbol(symbol)
    lines = [
        f"🔎 <b>Проверка фандинга {escape(symbol)}</b>",
        "Текущая ставка по подключённым биржам:",
        "",
    ]
    for exchange in EXCHANGE_ORDER:
        label = escape(EXCHANGE_LABELS[exchange])
        if exchange not in snapshot:
            lines.append(f"⚪ <b>{label}</b>: API временно недоступен")
            continue
        item = _symbol_item(snapshot.get(exchange), symbol)
        if item is None:
            lines.append(f"▫️ <b>{label}</b>: контракт не найден")
            continue
        rate = _decimal(item, "fundingRate", "funding_rate", "rate")
        if rate is None:
            lines.append(f"▫️ <b>{label}</b>: ставка недоступна")
            continue
        icon = "🟢" if rate > 0 else "🔴" if rate < 0 else "⚪"
        sign = "+" if rate > 0 else ""
        line = f"{icon} <b>{label}</b>: <code>{sign}{rate:.4f}%</code>"
        change = _decimal(item, "priceChange24h")
        if change is not None:
            line += f" · 24ч {change:+.2f}%"
        lines.append(line)
    return "\n".join(lines)


def build_funding_menu(page, pages, exchange=DEFAULT_EXCHANGE):
    exchange = normalize_exchange(exchange)
    exchange_buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if key == exchange else ''}{EXCHANGE_LABELS[key]}",
            callback_data=f"menu:funding-exchange:{key}",
        )
        for key in EXCHANGE_ORDER
    ]
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "◀️",
                callback_data=f"menu:funding-page:{page - 1}",
            )
        )
    navigation.append(
        InlineKeyboardButton(
            f"{page + 1}/{pages}",
            callback_data="menu:funding-page:current",
        )
    )
    if page < pages - 1:
        navigation.append(
            InlineKeyboardButton(
                "▶️",
                callback_data=f"menu:funding-page:{page + 1}",
            )
        )
    return InlineKeyboardMarkup([
        exchange_buttons[:3],
        exchange_buttons[3:],
        navigation,
        [InlineKeyboardButton("🔎 Проверка фандинга", callback_data="menu:funding-check")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data="funding-alert:open")],
        [InlineKeyboardButton("🔄 Показать актуальные", callback_data="menu:funding-refresh")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
    ])


def build_funding_check_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Проверить другой", callback_data="menu:funding-check")],
        [InlineKeyboardButton("📈 Топ ставок", callback_data="menu:funding")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
    ])


async def load_funding_rates(exchange=DEFAULT_EXCHANGE):
    client = PublicFundingClient()
    return await asyncio.to_thread(client.load, normalize_exchange(exchange))


async def load_funding_snapshot(exchanges=None):
    selected = normalize_exchanges(exchanges or EXCHANGE_ORDER)

    async def one(exchange):
        try:
            return exchange, await load_funding_rates(exchange), None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return exchange, None, error

    snapshot = {}
    results = await asyncio.gather(*(one(value) for value in selected))
    for exchange, rates, error in results:
        if error is not None:
            LOGGER.warning("Failed to load %s funding rates: %s", exchange, error)
        else:
            snapshot[exchange] = rates or []
    if not snapshot:
        raise RuntimeError("No funding exchange returned data")
    return snapshot


def _cache(context):
    value = context.application.bot_data.get(CACHE_KEY, {})
    return value if isinstance(value, dict) else {DEFAULT_EXCHANGE: value}


def _clear_check_input(context):
    context.user_data.pop(CHECK_INPUT_KEY, None)
    context.chat_data.pop(CHECK_INPUT_KEY, None)


def _set_check_input(context):
    context.user_data.pop(ALERT_INPUT_KEY, None)
    context.chat_data.pop(ALERT_INPUT_KEY, None)
    state = {"kind": "funding-check"}
    context.user_data[CHECK_INPUT_KEY] = state
    context.chat_data[CHECK_INPUT_KEY] = state


async def _edit(message, text, markup):
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def show_funding(
    message,
    context,
    *,
    exchange=None,
    page=0,
    refresh=False,
    edit=True,
):
    exchange = normalize_exchange(exchange or context.user_data.get(VIEW_KEY))
    context.user_data[VIEW_KEY] = exchange
    cache = _cache(context)
    rates = None if refresh else cache.get(exchange)
    if rates is None:
        try:
            rates = await load_funding_rates(exchange)
            cache[exchange] = rates
            context.application.bot_data[CACHE_KEY] = cache
        except Exception:
            LOGGER.exception("Failed to load %s funding", exchange)
            text = (
                f"⚠️ Не удалось загрузить фандинг {exchange_label(exchange)}. "
                "Попробуйте позже."
            )
            markup = build_funding_menu(0, 1, exchange)
            if edit:
                await _edit(message, text, markup)
            else:
                await message.reply_text(text, reply_markup=markup)
            return
    pages = page_count(rates)
    page = min(max(page, 0), pages - 1)
    text = format_funding_rates(rates, page, exchange)
    markup = build_funding_menu(page, pages, exchange)
    if edit:
        await _edit(message, text, markup)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def receive_funding_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get(CHECK_INPUT_KEY) or context.chat_data.get(CHECK_INPUT_KEY)
    if not state:
        return
    try:
        symbol = normalize_funding_symbol(update.effective_message.text)
    except ValueError as error:
        await update.effective_message.reply_text(f"Не получилось: {error}\nПопробуйте ещё раз.")
        return
    try:
        snapshot = await load_funding_snapshot()
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("Failed to check funding for %s", symbol)
        await update.effective_message.reply_text(
            "⚠️ Не удалось получить ставки ни с одной биржи. Попробуйте позже.",
            reply_markup=build_funding_check_menu(),
        )
        return
    cache = _cache(context)
    cache.update(snapshot)
    context.application.bot_data[CACHE_KEY] = cache
    _clear_check_input(context)
    await update.effective_message.reply_text(
        format_symbol_funding(symbol, snapshot),
        reply_markup=build_funding_check_menu(),
        parse_mode="HTML",
    )


@authorized
async def funding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_check_input(context)
    await show_funding(update.effective_message, context, edit=False)


@authorized
async def funding_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()
    action = query.data.removeprefix("menu:")
    if action == "funding-check":
        _set_check_input(context)
        await query.message.edit_text(
            "🔎 <b>Проверка фандинга</b>\n\n"
            "Введите инструмент, например <code>BTCUSDT</code>, "
            "<code>BTC/USDT</code> или просто <code>BTC</code>.\n\n"
            "Бот покажет текущую ставку на всех подключённых биржах.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Топ ставок", callback_data="menu:funding")],
                [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
            ]),
            parse_mode="HTML",
        )
        return
    _clear_check_input(context)
    if action == "funding-back":
        from handlers.menu import build_main_menu
        await query.message.edit_text(
            "Панель управления FVG:",
            reply_markup=build_main_menu(update.effective_chat.id),
        )
        return
    exchange = normalize_exchange(context.user_data.get(VIEW_KEY))
    page = 0
    refresh = action == "funding-refresh"
    if action.startswith("funding-exchange:"):
        exchange = normalize_exchange(action.split(":", 1)[1])
    elif action.startswith("funding-page:"):
        value = action.split(":", 1)[1]
        if value == "current":
            return
        try:
            page = int(value)
        except ValueError:
            return
    elif action not in {"funding", "funding-refresh"}:
        return
    await show_funding(
        query.message,
        context,
        exchange=exchange,
        page=page,
        refresh=refresh,
    )
