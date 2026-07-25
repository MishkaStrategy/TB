"""Funding-rate leaderboard shown in the Telegram bot interface."""

import asyncio
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from exchanges.bitunix import BitunixClient
from handlers.auth import authorized


PAGE_SIZE = 10
TOP_LIMIT = 50


def _funding_value(item: dict) -> Decimal | None:
    """Extract a funding rate despite small response-field variations."""
    for key in ("fundingRate", "funding_rate", "rate"):
        value = item.get(key)
        if value is None:
            continue
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
    return None


def _price_change_24h(item: dict) -> Decimal | None:
    """Calculate the 24-hour price change from Bitunix ticker values."""
    try:
        current = Decimal(str(item.get("lastPrice", item.get("last"))))
        opening = Decimal(str(item["open"]))
        if opening == 0:
            return None
        return (current / opening - 1) * 100
    except (InvalidOperation, ValueError, KeyError, TypeError):
        return None


def top_funding_rates(rates: list[dict], limit: int = TOP_LIMIT):
    parsed = []
    for item in rates:
        symbol = item.get("symbol")
        rate = _funding_value(item)
        if symbol and rate is not None:
            parsed.append((str(symbol), rate, _price_change_24h(item)))
    positive = sorted((item for item in parsed if item[1] > 0), key=lambda item: item[1], reverse=True)[:limit]
    negative = sorted((item for item in parsed if item[1] < 0), key=lambda item: item[1])[:limit]
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
    lines.append("<code> #  Инструмент    Фандинг     Цена 24ч</code>")
    for index, (symbol, rate, price_change) in enumerate(items, start_index + 1):
        # Bitunix returns fundingRate already in percent units (for example,
        # 0.065357 means 0.065357%), so it must not be multiplied by 100.
        change = "н/д" if price_change is None else f"{price_change:+.2f}%"
        lines.append(
            f"<code>{index:>2}. {symbol:<11} {sign}{abs(rate):.4f}% {change:>9}</code>"
        )
    return "\n".join(lines)


def funding_page_count(rates: list[dict]) -> int:
    positive, negative = top_funding_rates(rates)
    return max(1, (max(len(positive), len(negative)) + PAGE_SIZE - 1) // PAGE_SIZE)


def format_funding_rates(rates: list[dict], page: int = 0) -> str:
    positive, negative = top_funding_rates(rates)
    pages = funding_page_count(rates)
    page = min(max(page, 0), pages - 1)
    start = page * PAGE_SIZE
    return "\n\n".join((
        "💸 <b>Фандинг Bitunix</b>\n"
        "Ставка фандинга и изменение цены за сутки.\n"
        f"Страница {page + 1} из {pages} · топ‑50",
        _format_table("🟢 <b>Положительный фандинг</b>", positive[start:start + PAGE_SIZE], "+", start),
        _format_table("🔴 <b>Отрицательный фандинг</b>", negative[start:start + PAGE_SIZE], "−", start),
    ))


def build_funding_menu(page: int, pages: int) -> InlineKeyboardMarkup:
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("◀️", callback_data=f"menu:funding-page:{page - 1}"))
    navigation.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="menu:funding-page-current"))
    if page < pages - 1:
        navigation.append(InlineKeyboardButton("▶️", callback_data=f"menu:funding-page:{page + 1}"))
    return InlineKeyboardMarkup([
        navigation,
        [InlineKeyboardButton("🔄 Обновить", callback_data="menu:funding-refresh")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:funding-back")],
    ])


async def send_funding(message, *, page: int = 0, rates: list[dict] | None = None, edit: bool = False):
    if rates is None:
        try:
            client = BitunixClient()
            rates, tickers = await asyncio.gather(
                asyncio.to_thread(client.get_all_funding_rates),
                asyncio.to_thread(client.get_all_tickers),
            )
            tickers_by_symbol = {
                ticker.get("symbol"): ticker
                for ticker in tickers
                if ticker.get("symbol")
            }
            rates = [
                {**rate, **tickers_by_symbol.get(rate.get("symbol"), {})}
                for rate in rates
            ]
        except Exception:
            text = "⚠️ Не удалось загрузить ставки фандинга Bitunix. Попробуй обновить чуть позже."
            if edit:
                await message.edit_text(text, reply_markup=build_funding_menu(0, 1))
            else:
                await message.reply_text(text, reply_markup=build_funding_menu(0, 1))
            return None
    pages = funding_page_count(rates)
    page = min(max(page, 0), pages - 1)
    text = format_funding_rates(rates, page)
    if edit:
        await message.edit_text(text, reply_markup=build_funding_menu(page, pages), parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=build_funding_menu(page, pages), parse_mode="HTML")
    return rates


@authorized
async def funding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rates = await send_funding(update.effective_message)
    if rates is not None:
        context.user_data["funding_rates"] = rates
