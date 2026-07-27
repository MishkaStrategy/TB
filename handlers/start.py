from telegram import Update
from telegram.ext import ContextTypes

from alerts.fvg_store import FvgAlertSettings
from handlers.auth import authorized
from handlers.menu import show_menu


def _enable_confirmed_fvg_for_new_user(chat_id: int, settings: FvgAlertSettings | None = None) -> bool:
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
        "\n\n✅ Уведомления о подтверждённых FVG включены автоматически для BTCUSDT. "
        "Пред-FVG остаются выключенными — их можно включить командой /fvg_pre_alert on."
        if auto_enabled
        else ""
    )
    await update.effective_message.reply_text(
        "🤖 FVG Alert Bot запущен!\n\n"
        "Бот отслеживает FVG на Bitunix и ставки фандинга на нескольких биржах.\n"
        "Поддерживаются Bitunix, Binance, Bybit, Bitget, Gate и BingX.\n\n"
        "Команды:\n"
        "/fvg_alert on|off — FVG 15m уведомления\n"
        "/fvg_pre_alert on|off — пред-FVG за 3 минуты\n"
        "/fvg_symbol add ETHUSDT — добавить инструмент\n"
        "/fvg_price BTCUSDT 50000 90000 both — фильтр цены\n"
        "/fvg_size — фильтр размера FVG\n"
        "/fvg_stats — статистика FVG-событий\n"
        "/funding — мультибиржевой топ ставок и уведомления\n"
        "/donate — поддержать проект\n"
        "/menu — открыть нижнее меню\n\n"
        "/admin — админ-панель.\n\n"
        "Основные разделы всегда доступны на клавиатуре под полем сообщения."
        f"{activation_note}"
    )
    await show_menu(update.effective_message, chat_id)
