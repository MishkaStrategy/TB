"""Administrator-only settings and operational actions."""

from __future__ import annotations

import asyncio
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from alerts.funding_alerts import FundingAlertStore
from alerts.scheduler_multi import get_fvg_service
from config import ALLOWED_TELEGRAM_IDS, PUBLIC_ACCESS_ENABLED, is_admin
from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry


_RUNTIME_SETTINGS = RuntimeSettings()
PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
MANUAL_BACKUP_DIR = DATA_DIR / ".manual_backups"


def public_access_enabled() -> bool:
    return _RUNTIME_SETTINGS.public_access_enabled(default=PUBLIC_ACCESS_ENABLED)


def admin_keyboard(public_access=None) -> InlineKeyboardMarkup:
    if public_access is None:
        public_access = public_access_enabled()
    access = "🌐 Доступ: публичный" if public_access else "🔐 Доступ: приватный"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(access, callback_data="admin:toggle_access")],
            [InlineKeyboardButton("👥 Разрешённые пользователи", callback_data="admin:allowed")],
            [
                InlineKeyboardButton("📡 WebSocket", callback_data="admin:websocket"),
                InlineKeyboardButton("📨 Очередь уведомлений", callback_data="admin:queue"),
            ],
            [
                InlineKeyboardButton("🗄 Базы данных", callback_data="admin:databases"),
                InlineKeyboardButton("🖥 Память и нагрузка", callback_data="admin:resources"),
            ],
            [
                InlineKeyboardButton("💾 Резервная копия", callback_data="admin:backup"),
                InlineKeyboardButton("🏷 Версия релиза", callback_data="admin:version"),
            ],
            [InlineKeyboardButton("♻️ Перезапустить бота", callback_data="admin:restart")],
            [InlineKeyboardButton("⬅️ Настройки", callback_data="settings:open")],
        ]
    )


def _format_time(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError):
        return "—"


def _format_bytes(value) -> str:
    amount = float(max(0, int(value or 0)))
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if amount < 1024 or unit == "ТБ":
            return f"{amount:.1f} {unit}" if unit != "Б" else f"{int(amount)} {unit}"
        amount /= 1024
    return "0 Б"


def format_allowed_users() -> str:
    runtime = AccessRegistry().users(status="allowed")
    activity = UserActivityRegistry().users()
    ids = sorted(set(ALLOWED_TELEGRAM_IDS) | {int(value) for value in runtime})
    lines = ["👥 Разрешённые пользователи", "", f"Всего: {len(ids)}"]
    if not ids:
        return "\n".join([*lines, "", "Список пуст."])
    lines.append("")
    for user_id in ids:
        record = runtime.get(str(user_id), {})
        tracked = activity.get(str(user_id), {})
        name = record.get("name") or tracked.get("name") or "Без имени"
        username = record.get("username") or tracked.get("username")
        suffix = f" @{username}" if username else ""
        source = "env" if user_id in ALLOWED_TELEGRAM_IDS else "runtime"
        lines.append(f"• {user_id} · {name}{suffix} · {source}")
    return "\n".join(lines)


def format_websocket_status() -> str:
    health = get_fvg_service().event_store.health()
    connected = health.get("ws_connected")
    status = "подключён" if connected is True else "отключён" if connected is False else "неизвестно"
    return "\n".join(
        [
            "📡 WebSocket Bitunix",
            "",
            f"Статус: {status}",
            f"Последняя свеча: {_format_time(health.get('last_ws_message'))}",
            f"Последний REST recovery: {_format_time(health.get('last_rest_recovery'))}",
            f"Последняя ошибка: {health.get('last_error') or '—'}",
        ]
    )


def format_queue_status() -> str:
    health = get_fvg_service().event_store.health()
    return "\n".join(
        [
            "📨 Очередь уведомлений",
            "",
            f"Сообщений в outbox: {int(health.get('outbox') or 0)}",
            f"Успешных доставок: {int(health.get('deliveries') or 0)}",
            f"Ошибок доставки: {int(health.get('delivery_failures') or 0)}",
            f"Повторных доставок: {int(health.get('delivery_retries') or 0)}",
            f"Навсегда отклонено Telegram: {int(health.get('delivery_permanent_failures') or 0)}",
        ]
    )


def _sqlite_status(path: Path) -> tuple[str, int]:
    if not path.exists():
        return "не создана", 0
    try:
        with sqlite3.connect(path, timeout=5) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        status = result[0] if result else "unknown"
    except (OSError, sqlite3.Error) as error:
        status = f"ошибка: {error}"
    return status, path.stat().st_size if path.exists() else 0


def format_database_status() -> str:
    event_status, event_size = _sqlite_status(get_fvg_service().event_store.path)
    funding_status, funding_size = _sqlite_status(FundingAlertStore().path)
    json_files = [
        DATA_DIR / "fvg_alert_settings.json",
        DATA_DIR / "user_preferences.json",
        DATA_DIR / "runtime_settings.json",
        DATA_DIR / "access_control.json",
        DATA_DIR / "user_activity.json",
    ]
    json_size = sum(path.stat().st_size for path in json_files if path.exists())
    return "\n".join(
        [
            "🗄 Состояние баз данных",
            "",
            f"FVG SQLite: {event_status} · {_format_bytes(event_size)}",
            f"Funding SQLite: {funding_status} · {_format_bytes(funding_size)}",
            f"JSON-настройки: {_format_bytes(json_size)}",
        ]
    )


def _memory_bytes() -> int:
    status_path = Path("/proc/self/status")
    if status_path.exists():
        for line in status_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def format_resource_status() -> str:
    try:
        load = " / ".join(f"{value:.2f}" for value in os.getloadavg())
    except (AttributeError, OSError):
        load = "—"
    disk = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else PROJECT_DIR)
    return "\n".join(
        [
            "🖥 Память и нагрузка",
            "",
            f"Память процесса: {_format_bytes(_memory_bytes())}",
            f"Load average 1/5/15: {load}",
            f"Свободно на диске: {_format_bytes(disk.free)} из {_format_bytes(disk.total)}",
            f"PID: {os.getpid()}",
        ]
    )


def format_version() -> str:
    version_path = PROJECT_DIR / "VERSION"
    commit_path = PROJECT_DIR / "BUILD_COMMIT"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
    commit = commit_path.read_text(encoding="utf-8").strip() if commit_path.exists() else "не записан"
    return "\n".join(
        [
            "🏷 Версия установленного релиза",
            "",
            f"Версия: {version}",
            f"Git commit: {commit}",
            f"Python: {sys.version.split()[0]}",
        ]
    )


def create_manual_backup() -> str:
    MANUAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "INSTALL_DIR": str(PROJECT_DIR),
            "DATA_DIR": str(DATA_DIR.resolve()),
            "BACKUP_DIR": str(MANUAL_BACKUP_DIR.resolve()),
            "PYTHON": sys.executable,
            "RETENTION_DAYS": "14",
        }
    )
    result = subprocess.run(
        ["bash", str(PROJECT_DIR / "scripts" / "backup_data.sh")],
        cwd=PROJECT_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = (result.stdout or result.stderr).strip()
    if result.returncode:
        raise RuntimeError(output or f"backup exited with code {result.returncode}")
    return output.splitlines()[-1] if output else "Backup created"


async def show_admin_panel(message, chat_id: int, *, edit=False) -> None:
    method = message.edit_text if edit else message.reply_text
    if not is_admin(chat_id):
        await method("Эта панель доступна только администраторам.")
        return
    await method("🛠 Админ-настройки", reply_markup=admin_keyboard())


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.effective_message.reply_text("Эта панель доступна только администраторам.")
        return
    await show_admin_panel(update.effective_message, user.id)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if not is_admin(user.id):
        await query.answer("Эта панель доступна только администраторам.", show_alert=True)
        return
    action = query.data.removeprefix("admin:")
    await query.answer()
    if action in {"home", "open"}:
        await show_admin_panel(query.message, user.id, edit=True)
    elif action == "toggle_access":
        enabled = await asyncio.to_thread(_RUNTIME_SETTINGS.toggle_public_access, PUBLIC_ACCESS_ENABLED)
        text = (
            "🌐 Публичный доступ включён.\n\nБот теперь принимает команды от всех Telegram-пользователей."
            if enabled
            else "🔐 Приватный доступ включён.\n\nБот принимает команды только от пользователей из allowlist и одобренных заявок."
        )
        await query.edit_message_text(text, reply_markup=admin_keyboard(enabled))
    elif action == "allowed":
        await query.edit_message_text(await asyncio.to_thread(format_allowed_users), reply_markup=admin_keyboard())
    elif action == "websocket":
        await query.edit_message_text(await asyncio.to_thread(format_websocket_status), reply_markup=admin_keyboard())
    elif action == "queue":
        await query.edit_message_text(await asyncio.to_thread(format_queue_status), reply_markup=admin_keyboard())
    elif action == "databases":
        await query.edit_message_text(await asyncio.to_thread(format_database_status), reply_markup=admin_keyboard())
    elif action == "resources":
        await query.edit_message_text(await asyncio.to_thread(format_resource_status), reply_markup=admin_keyboard())
    elif action == "version":
        await query.edit_message_text(format_version(), reply_markup=admin_keyboard())
    elif action == "backup":
        try:
            result = await asyncio.to_thread(create_manual_backup)
            text = f"✅ Резервная копия создана.\n\n{result}"
        except Exception as error:
            text = f"⚠️ Не удалось создать резервную копию.\n\n{error}"
        await query.edit_message_text(text, reply_markup=admin_keyboard())
    elif action == "restart":
        await query.edit_message_text(
            "♻️ Перезапустить бота?\n\nПроцесс завершится с ошибкой, после чего systemd запустит его снова.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Да, перезапустить", callback_data="admin:restart_confirm")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="admin:home")],
                ]
            ),
        )
    elif action == "restart_confirm":
        await query.edit_message_text("♻️ Бот перезапускается…")
        asyncio.get_running_loop().call_later(1.0, lambda: os._exit(1))
