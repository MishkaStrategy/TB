"""Button-based Telegram interface and its central feature registry."""

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from alerts.fvg_models import FvgDirection
from alerts.fvg_store import FvgAlertSettings
from handlers.auth import authorized
from handlers.funding import CACHE_KEY as FUNDING_CACHE_KEY, send_funding
from handlers.fvg_alert import (
    build_fvg_stats_period_menu,
    format_fvg_stats,
    send_fvg_stats,
)


@dataclass(frozen=True)
class MenuAction:
    key: str
    label: str


MAIN_ACTIONS: tuple[MenuAction, ...] = ()


def build_main_menu(chat_id, settings=None):
    settings = settings or FvgAlertSettings()
    rows = [
        [InlineKeyboardButton(action.label, callback_data=f"menu:{action.key}")]
        for action in MAIN_ACTIONS
    ]
    fvg_label = "🔔 Настройки FVG 15м" if settings.is_enabled(chat_id) else "🔕 Настройки FVG 15м"
    rows.append([InlineKeyboardButton(fvg_label, callback_data="menu:fvg-settings")])
    rows.append([
        InlineKeyboardButton("📊 Статистика FVG", callback_data="menu:fvg-stats")
    ])
    rows.append([InlineKeyboardButton("💸 Фандинг", callback_data="menu:funding")])
    return InlineKeyboardMarkup(rows)


def build_fvg_settings_menu(chat_id, settings=None):
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    def mark(enabled):
        return "✅" if enabled else "⏸️"
    symbols = user.get("symbols", {}).values()
    price_enabled = any(
        item.get("price_filter", {}).get("enabled", False) for item in symbols
    )
    symbols = user.get("symbols", {}).values()
    size_enabled = any(
        item.get("size_filter", {}).get("enabled", False) for item in symbols
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mark(user['enabled'])} Модуль FVG", callback_data="menu:fvg-toggle")],
        [
            InlineKeyboardButton(f"{mark(user['notify_confirmed_fvg'])} Подтверждённые", callback_data="menu:fvg-confirmed-toggle"),
            InlineKeyboardButton(f"{mark(user['notify_pre_fvg'])} Пред-FVG T−3", callback_data="menu:pre-fvg-toggle"),
        ],
        [
            InlineKeyboardButton(f"{mark(user['bullish_enabled'])} 🐮 Бычьи", callback_data="menu:fvg-bull-toggle"),
            InlineKeyboardButton(f"{mark(user['bearish_enabled'])} 🐻 Медвежьи", callback_data="menu:fvg-bear-toggle"),
        ],
        [
            InlineKeyboardButton("➕ Инструменты", callback_data="menu:fvg-symbol-help"),
            InlineKeyboardButton(
                f"{mark(price_enabled)} Цена", callback_data="menu:fvg-price"
            ),
        ],
        [InlineKeyboardButton(
            f"{mark(size_enabled)} 📏 Размер FVG", callback_data="menu:fvg-size"
        )],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:fvg-back")],
    ])


async def show_menu(message, chat_id):
    await message.reply_text(
        "Панель управления FVG:",
        reply_markup=build_main_menu(chat_id),
    )


@authorized
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update.effective_message, update.effective_chat.id)


@authorized
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith("menu:"):
        return
    await query.answer()
    action = query.data.removeprefix("menu:")
    message = query.message
    chat_id = update.effective_chat.id

    if action == "fvg-settings":
        settings = FvgAlertSettings()
        await message.edit_text("Настройки применяются отдельно для твоего Telegram ID.", reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "fvg-toggle":
        settings = FvgAlertSettings()
        enabled = not settings.is_enabled(chat_id)
        settings.set_enabled(chat_id, enabled)
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "fvg-confirmed-toggle":
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        settings.set_confirmed_enabled(chat_id, not user["notify_confirmed_fvg"])
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "pre-fvg-toggle":
        settings = FvgAlertSettings()
        enabled = not settings.user(chat_id)["notify_pre_fvg"]
        settings.set_pre_enabled(chat_id, enabled)
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action in {"fvg-bull-toggle", "fvg-bear-toggle"}:
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        direction = FvgDirection.BULLISH if action == "fvg-bull-toggle" else FvgDirection.BEARISH
        key = "bullish_enabled" if direction is FvgDirection.BULLISH else "bearish_enabled"
        settings.set_direction_enabled(chat_id, direction, not user[key])
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "fvg-symbol-help":
        await message.reply_text(
            "Инструменты: /fvg_symbol add ETHUSDT или /fvg_symbol remove ETHUSDT\n"
            "После добавления настрой «💰 Фильтр цены» и «📏 Размер FVG»."
        )
    elif action == "fvg-back":
        await message.edit_text("Панель управления FVG:", reply_markup=build_main_menu(chat_id))
    elif action == "fvg-stats":
        await send_fvg_stats(message)
    elif action in {"funding", "funding-refresh"}:
        rates = await send_funding(message, edit=True)
        if rates is not None:
            context.user_data[FUNDING_CACHE_KEY] = rates
    elif action.startswith("funding-page:"):
        page_value = action.removeprefix("funding-page:")
        if page_value == "current":
            return
        try:
            page = int(page_value)
        except ValueError:
            return
        rates = context.user_data.get(FUNDING_CACHE_KEY)
        rates = await send_funding(message, page=page, rates=rates, edit=True)
        if rates is not None:
            context.user_data[FUNDING_CACHE_KEY] = rates
    elif action == "funding-back":
        await message.edit_text("Панель управления FVG:", reply_markup=build_main_menu(chat_id))
    elif action.startswith("fvg-stats:"):
        period = action.split(":", 1)[1]
        days = None if period == "all" else int(period)
        await message.edit_text(
            format_fvg_stats(days),
            reply_markup=build_fvg_stats_period_menu(days),
        )
