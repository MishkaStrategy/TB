"""Funding-rate leaderboard shown in the Telegram bot interface."""

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from exchanges.bitunix import BitunixClient
from handlers.auth import authorized


LOGGER = logging.getLogger(__name__)
PAGE_SIZE = 10
TOP_LIMIT = 50
CACHE_KEY = "funding_rates"


def _decimal_value(item: dict, *keys: str) -> Decimal | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return None


def _funding_value(item: dict) -> Decimal | None:
    """Return the funding rate in Bitunix percentage-point units."""
    return _decimal_value(item, "fundingRate", "funding_rate", "rate")


def _price_change_24h(item: dict) -> Decimal | None:
    """Calculate the 24-hour price change from Bitunix ticker values."""
    current = _decimal_value(item, "lastPrice", "last")
    opening = _decimal_value(item, "open")
    if current is None or opening in (None, Decimal("0")):
        return None
    return (current / opening - 1) * 100


def top_funding_rates(
    rates: list[dict],
    limit: int = TOP_LIMIT,
) -> tuple[
    list[tuple[str, Decimal, Decimal | None]],
    list[tuple[str, Decimal, Decimal | None]],
]:
    parsed: list[tuple[str, Decimal, Decimal | None]] = []
    for item in rates:
        symbol = item.get("symbol")
        rate = _funding_value(item)
        if symbol and rate is not None:
            parsed.append((str(symbol), rate, _price_change_24h(item)))

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


def _format_table(
    title: str,
    items: list[tuple[str, Decimal, Decimal | None]],
    sign: str,
    start_index: int,
) -> str:
    lines = [title]
    if not items:
        return "\n".join([*lines, "Нет данных"])

    lines.append("<code> #  Инструмент    Фандинг    Цена 24ч</code>")
    for index, (symbol, rate, price_change) in enumerate(items, start_index + 1):
        # Live Bitunix funding values are already percentage points:
        # -1.514051 must be displayed as -1.5141%, not -151.4051%.
        percent = abs(rate)
        change = "н/д" if price_change is None else f"{price_change:+.2f}%"
        safe_symbol = escape(symbol[:16])
        lines.append(
            f"<code>{index:>2}. {safe_symbol:<12} {sign}{percent:.4f}% {change:>9}</code>"
        )
    return "\n".join(lines)


def funding_page_count(rates: list[dict]) -> int:
    positive, negative = top_funding_rates(rates)
    longest = max(len(positive), len(negative))
    return max(1, (longest + PAGE_SIZE - 1) // PAGE_SIZE)


def format_funding_rates(rates: list[dict], page: int = 0) -> str:
    positive, negative = top_funding_rates(rates)
    pages = funding_page_count(rates)
    page = min(max(page, 0), pages - 1)
    start = page * PAGE_SIZE

    return "\n\n".join(
        (
            "💸 <b>Фандинг Bitunix</b>\n"
            "Текущая ставка и изменение цены за 24 часа.\n"
            f"Страница {page + 1} из {pages} · топ-50 в каждую сторону",
            _format_table(
                "🟢 <b>Положительный фандинг</b>",
                positive[start : start + PAGE_SIZE],
                "+",
                start,
            ),
            _format_table(
                "🔴 <b>Отрицательный фандинг</b>",
                negative[start : start + PAGE_SIZE],
                "−",
                start,
            ),
        )
    )


def build_funding_menu(page: int, pages: int) -> InlineKeyboardMarkup:
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton("◀️", callback_data=f"menu:funding-page:{page - 1}")
        )
    navigation.append(
        InlineKeyboardButton(
            f"{page + 1}/{pages}",
            callback_data="menu:funding-page:current",
        )
    )
    if page < pages - 1:
        navigation.append(
            InlineKeyboardButton("▶️", callback_data=f"menu:funding-page:{page + 1}")
        )

    return InlineKeyboardMarkup(
        [
            navigation,
            [InlineKeyboardButton("🔄 Обновить", callback_data="menu:funding-refresh")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
        ]
    )


def enrich_funding_rates(rates: list[dict], tickers: list[dict]) -> list[dict]:
    """Add ticker prices without allowing ticker fields to replace funding data.

    Only price fields are copied from tickers, so the batch endpoint remains the
    source of truth for funding rate, sign, interval, and settlement metadata.
    """
    tickers_by_symbol = {
        ticker.get("symbol"): ticker
        for ticker in tickers
        if isinstance(ticker, dict) and ticker.get("symbol")
    }
    enriched_rates: list[dict] = []
    for rate in rates:
        if not isinstance(rate, dict):
            continue
        enriched = dict(rate)
        ticker = tickers_by_symbol.get(rate.get("symbol"), {})
        for key in ("open", "lastPrice", "last"):
            if key in ticker:
                enriched[key] = ticker[key]
        enriched_rates.append(enriched)
    return enriched_rates


async def load_funding_rates() -> list[dict]:
    """Fetch funding rates and enrich them with optional 24-hour ticker data."""
    client = BitunixClient()
    rates_result, tickers_result = await asyncio.gather(
        asyncio.to_thread(client.get_all_funding_rates),
        asyncio.to_thread(client.get_all_tickers),
        return_exceptions=True,
    )

    if isinstance(rates_result, BaseException):
        raise rates_result

    tickers: list[dict]
    if isinstance(tickers_result, BaseException):
        LOGGER.warning("Failed to load Bitunix tickers for funding view", exc_info=tickers_result)
        tickers = []
    else:
        tickers = tickers_result

    return enrich_funding_rates(rates_result, tickers)


async def _edit_text_safely(message, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def send_funding(
    message,
    *,
    page: int = 0,
    rates: list[dict] | None = None,
    edit: bool = False,
) -> list[dict] | None:
    if rates is None:
        try:
            rates = await load_funding_rates()
        except Exception:
            LOGGER.exception("Failed to load Bitunix funding rates")
            text = "⚠️ Не удалось загрузить ставки фандинга Bitunix. Попробуй обновить чуть позже."
            markup = build_funding_menu(0, 1)
            if edit:
                await _edit_text_safely(message, text, markup)
            else:
                await message.reply_text(text, reply_markup=markup)
            return None

    pages = funding_page_count(rates)
    page = min(max(page, 0), pages - 1)
    text = format_funding_rates(rates, page)
    markup = build_funding_menu(page, pages)

    if edit:
        await _edit_text_safely(message, text, markup)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return rates


@authorized
async def funding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rates = await send_funding(update.effective_message)
    if rates is not None:
        context.user_data[CACHE_KEY] = rates
