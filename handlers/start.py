from telegram import Update
from telegram.ext import ContextTypes

from alerts.fvg_store import FvgAlertSettings
from handlers.auth import authorized
from handlers.menu import show_menu


def _enable_confirmed_fvg_for_new_user(
    chat_id: int,
    settings: FvgAlertSettings | None = None,
) -> bool:
    """Persist default confirmed-FVG alerts once, without overriding user choice."""
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    user["enabled"] = True
    user["notify_confirmed_fvg"] = True

    def register(data):
        users = data.setdefault("users", {})
        key = str(chat_id)
        if key in users:
            return False
        users[key] = user
        return True

    return bool(settings._transaction(register))


@authorized
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    auto_enabled = _enable_confirmed_fvg_for_new_user(chat_id)
    activation_note = (
        "\n\n✅ Уведомления о подтверждённых FVG включены автоматически "
        "для BTCUSDT. Пред-FVG остаются выключенными — их можно включить "
        "командой /fvg_pre_alert on."
        if auto_enabled
        else ""
    )

    await update.effective_message.reply_text(
        "🤖 FVG Alert Bot запущен!\n\n"
        "Бот специализируется на Fair Value Gap (FVG) для фьючерсов Bitunix.\n"
        "Он отслеживает предварительные FVG в точке T−3 и подтверждённые FVG "
        "на 15-минутном таймфрейме.\n\n"
        "Команды:\n"
        "/fvg_alert on|off — FVG 15m уведомления\n"
        "/fvg_pre_alert on|off — пред-FVG за 3 минуты\n"
        "/fvg_symbol add ETHUSDT — добавить инструмент\n"
        "/fvg_price BTCUSDT 50000 90000 both — фильтр цены\n"
        "/fvg_size — фильтр размера FVG\n"
        "/fvg_stats — статистика FVG-событий\n"
        "/menu — кнопки управления\n\n"
        "/admin — админ-панель и статистика пользователей.\n\n"
        "Кнопка меню рядом с полем сообщения открывает настройки FVG."
        f"{activation_note}"
    )
    await show_menu(update.effective_message, chat_id)
