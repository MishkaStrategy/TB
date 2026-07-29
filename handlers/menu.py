"""Button-based Telegram interface for FVG controls and the main menu."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from alerts.fvg_models import FvgDirection
from alerts.fvg_store import FvgAlertSettings
from exchanges.fvg_candles import is_bitcoin_symbol
from handlers.auth import authorized
from handlers.fvg_alert import build_fvg_stats_period_menu, format_fvg_stats, send_fvg_stats
from handlers.fvg_instruments import show_fvg_instruments


REPLY_MENU_FVG = "📉 FVG"
REPLY_MENU_FUNDING = "💸 Фандинг"
REPLY_MENU_ALERTS = "🔔 Уведомления"
REPLY_MENU_STATS = "📊 Статистика"
REPLY_MENU_SETTINGS = "⚙️ Настройки"
REPLY_MENU_DONATE = "❤️ Донат"


def build_reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [REPLY_MENU_FVG, REPLY_MENU_FUNDING],
            [REPLY_MENU_ALERTS, REPLY_MENU_STATS],
            [REPLY_MENU_SETTINGS, REPLY_MENU_DONATE],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел",
    )


def build_main_menu(chat_id, settings=None):
    settings = settings or FvgAlertSettings()
    fvg_label = "🔔 Настройки FVG" if settings.is_enabled(chat_id) else "🔕 Настройки FVG"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(fvg_label, callback_data="menu:fvg-settings")],
            [InlineKeyboardButton("📊 Статистика FVG", callback_data="menu:fvg-stats")],
            [InlineKeyboardButton("💸 Фандинг", callback_data="menu:funding")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="settings:open")],
        ]
    )


def build_fvg_settings_menu(chat_id, settings=None):
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)

    def mark(enabled):
        return "✅" if enabled else "⏸️"

    instruments = list(user.get("symbols", {}).values())
    price_enabled = any(item.get("price_filter", {}).get("enabled", False) for item in instruments)
    size_enabled = any(item.get("size_filter", {}).get("enabled", False) for item in instruments)
    has_bitcoin = any(is_bitcoin_symbol(item.get("symbol", "")) for item in instruments)

    rows = [
        [InlineKeyboardButton(
            f"{mark(user['enabled'])} Модуль FVG",
            callback_data="menu:fvg-toggle",
        )],
    ]
    notification_row = [InlineKeyboardButton(
        f"{mark(user['notify_confirmed_fvg'])} Подтверждённые",
        callback_data="menu:fvg-confirmed-toggle",
    )]
    if has_bitcoin:
        notification_row.append(InlineKeyboardButton(
            f"{mark(user['notify_pre_fvg'])} Пред-FVG BTC",
            callback_data="menu:pre-fvg-toggle",
        ))
    rows.extend((
        notification_row,
        [
            InlineKeyboardButton(
                f"{mark(user['bullish_enabled'])} 🐮 Бычьи",
                callback_data="menu:fvg-bull-toggle",
            ),
            InlineKeyboardButton(
                f"{mark(user['bearish_enabled'])} 🐻 Медвежьи",
                callback_data="menu:fvg-bear-toggle",
            ),
        ],
        [
            InlineKeyboardButton("📌 Инструменты", callback_data="fvg-inst:open"),
            InlineKeyboardButton(f"{mark(price_enabled)} Цена", callback_data="menu:fvg-price"),
        ],
        [InlineKeyboardButton(f"{mark(size_enabled)} 📏 Размер FVG", callback_data="menu:fvg-size")],
        [InlineKeyboardButton("❓ FAQ по FVG", callback_data="fvg-inst:faq:main")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:fvg-back")],
    ))
    return InlineKeyboardMarkup(rows)


async def show_menu(message, chat_id):
    await message.reply_text("Главное меню закреплено на клавиатуре ниже.", reply_markup=build_reply_menu())
    await message.reply_text("Панель управления:", reply_markup=build_main_menu(chat_id))


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
        await message.edit_text(
            "Настройки применяются отдельно для вашего Telegram ID.",
            reply_markup=build_fvg_settings_menu(chat_id, settings),
        )
    elif action == "fvg-toggle":
        settings = FvgAlertSettings()
        settings.set_enabled(chat_id, not settings.is_enabled(chat_id))
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "fvg-confirmed-toggle":
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        settings.set_confirmed_enabled(chat_id, not user["notify_confirmed_fvg"])
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "pre-fvg-toggle":
        settings = FvgAlertSettings()
        has_bitcoin = any(
            is_bitcoin_symbol(config.get("symbol", ""))
            for config in settings.user(chat_id).get("symbols", {}).values()
        )
        if not has_bitcoin:
            await message.reply_text("Пред-FVG доступен только после добавления Bitcoin-инструмента.")
            return
        settings.set_pre_enabled(chat_id, not settings.user(chat_id)["notify_pre_fvg"])
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action in {"fvg-bull-toggle", "fvg-bear-toggle"}:
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        direction = FvgDirection.BULLISH if action == "fvg-bull-toggle" else FvgDirection.BEARISH
        key = "bullish_enabled" if direction is FvgDirection.BULLISH else "bearish_enabled"
        settings.set_direction_enabled(chat_id, direction, not user[key])
        await message.edit_reply_markup(reply_markup=build_fvg_settings_menu(chat_id, settings))
    elif action == "fvg-symbol-help":
        await show_fvg_instruments(message, chat_id, edit=False)
    elif action == "fvg-back":
        await message.edit_text("Панель управления:", reply_markup=build_main_menu(chat_id))
    elif action == "fvg-stats":
        await send_fvg_stats(message)
    elif action.startswith("fvg-stats:"):
        period = action.split(":", 1)[1]
        days = None if period == "all" else int(period)
        await message.edit_text(format_fvg_stats(days), reply_markup=build_fvg_stats_period_menu(days))
