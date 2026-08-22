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
from database.operations_status import OperationsStatusReader
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from operations.process_restart import request_sigterm_restart

_RUNTIME_SETTINGS = RuntimeSettings()
PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
MANUAL_BACKUP_DIR = DATA_DIR / ".manual_backups"

_STATUS_LABELS = {
    "starting": "запускается",
    "running": "работает",
    "stopping": "останавливается",
    "stopped": "остановлен",
    "failed": "ошибка",
    "shutdown_timeout": "тайм-аут остановки",
    "interrupted": "предыдущий запуск прерван",
    "idle": "ожидает",
    "success": "успешно",
    "cancelled": "отменено",
    "skipped": "пропущено",
    "stale": "lease истёк",
    "requested": "запрошен",
    "blocked": "заблокирован",
}
_DECISION_LABELS = {
    "allowed": "разрешён",
    "limit_reached": "достигнут лимит",
    "cooldown": "активен cooldown",
}
_DATABASE_LABELS = {"fvg": "FVG", "funding": "Funding"}


def public_access_enabled() -> bool:
    return _RUNTIME_SETTINGS.public_access_enabled(default=PUBLIC_ACCESS_ENABLED)


def admin_keyboard(public_access=None) -> InlineKeyboardMarkup:
    if public_access is None:
        public_access = public_access_enabled()
    access = "🌐 Доступ: публичный" if public_access else "🔐 Доступ: приватный"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(access, callback_data="admin:toggle_access")],
        [InlineKeyboardButton("👥 Разрешённые пользователи", callback_data="admin:allowed")],
        [InlineKeyboardButton("📡 WebSocket", callback_data="admin:websocket"), InlineKeyboardButton("📨 Очередь уведомлений", callback_data="admin:queue")],
        [InlineKeyboardButton("⚙️ Операции", callback_data="admin:operations")],
        [InlineKeyboardButton("🗄 Базы данных", callback_data="admin:databases"), InlineKeyboardButton("🖥 Память и нагрузка", callback_data="admin:resources")],
        [InlineKeyboardButton("💾 Резервная копия", callback_data="admin:backup"), InlineKeyboardButton("🏷 Версия релиза", callback_data="admin:version")],
        [InlineKeyboardButton("♻️ Перезапустить бота", callback_data="admin:restart")],
        [InlineKeyboardButton("⬅️ Настройки", callback_data="settings:open")],
    ])


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


def _format_signed_bytes(value) -> str:
    if value is None:
        return "—"
    value = int(value)
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{_format_bytes(abs(value))}"


def _format_duration(value) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if seconds or not parts:
        parts.append(f"{seconds} с")
    return " ".join(parts)


def _short(value, limit: int = 180) -> str:
    text = str(value or "—").replace("\n", " ").strip() or "—"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_error(error_class, error_message) -> str:
    return _short(f"{error_class or 'Error'}: {error_message or '—'}")


def _status_label(value) -> str:
    value = str(value or "неизвестно")
    return _STATUS_LABELS.get(value, value)


def _decision_label(value) -> str:
    value = str(value or "неизвестно")
    return _DECISION_LABELS.get(value, value)


def format_allowed_users() -> str:
    runtime = AccessRegistry().users(status="allowed")
    activity = UserActivityRegistry().users()
    ids = sorted(set(ALLOWED_TELEGRAM_IDS) | {int(value) for value in runtime})
    lines = ["👥 Разрешённые пользователи", "", f"Всего: {len(ids)}"]
    if not ids:
        return "\n".join([*lines, "", "Список пуст."])
    lines.append("")
    for user_id in ids:
        record, tracked = runtime.get(str(user_id), {}), activity.get(str(user_id), {})
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
    return "\n".join([
        "📡 WebSocket Bitunix", "", f"Статус: {status}",
        f"Последняя свеча: {_format_time(health.get('last_ws_message'))}",
        f"Последний REST recovery: {_format_time(health.get('last_rest_recovery'))}",
        f"Последняя ошибка: {health.get('last_error') or '—'}",
    ])


def format_queue_status() -> str:
    health = get_fvg_service().event_store.health()
    return "\n".join([
        "📨 Очередь уведомлений", "",
        f"Сообщений в outbox: {int(health.get('outbox') or 0)}",
        f"Успешных доставок: {int(health.get('deliveries') or 0)}",
        f"Ошибок доставки: {int(health.get('delivery_failures') or 0)}",
        f"Повторных доставок: {int(health.get('delivery_retries') or 0)}",
        f"Навсегда отклонено Telegram: {int(health.get('delivery_permanent_failures') or 0)}",
    ])


def format_operations_status(snapshot=None) -> str:
    if snapshot is None:
        path = get_fvg_service().event_store.path
        snapshot = OperationsStatusReader(path).snapshot()

    lines = ["⚙️ Операционное состояние", ""]
    if not snapshot.get("available"):
        error = snapshot.get("error_message") or "неизвестная ошибка"
        lines.extend(["Runtime SQLite недоступна.", f"Причина: {error}"])
        return "\n".join(lines)

    lifecycle = snapshot.get("lifecycle", {})
    lines.append("Процесс")
    state = lifecycle.get("state") if lifecycle.get("available") else None
    if state is None:
        lines.append("• lifecycle history: нет данных")
    else:
        lines.extend([
            f"• Статус: {_status_label(state.get('status'))}",
            f"• PID: {int(state.get('pid') or 0)}",
            f"• Фаза: {state.get('last_phase') or '—'}",
            f"• Обновлено: {_format_time(state.get('updated_at'))}",
            f"• Результат остановки: {state.get('shutdown_outcome') or '—'}",
        ])
        if state.get("last_error_message"):
            lines.append(
                f"• Ошибка: {_format_error(state.get('last_error_class'), state.get('last_error_message'))}"
            )

    guard = snapshot.get("restart_guard", {})
    lines.extend(["", "Защита перезапуска"])
    if not guard.get("available"):
        lines.append("• circuit breaker: нет данных")
    else:
        blocked = bool(guard.get("blocked"))
        lines.extend([
            f"• Статус: {'заблокирован' if blocked else 'разрешён'}",
            f"• Окно: {int(guard.get('requests_in_window') or 0)}/{int(guard.get('max_requests') or 0)} за {_format_duration(guard.get('window_seconds'))}",
            f"• Срабатываний: {int(guard.get('trip_count') or 0)}",
        ])
        if blocked or guard.get("blocked_until"):
            lines.append(f"• Cooldown до: {_format_time(guard.get('blocked_until'))}")
        latest = guard.get("latest_request")
        if latest:
            lines.append(
                "• Последний запрос: "
                f"{_status_label(latest.get('status'))} · "
                f"{_decision_label(latest.get('decision_reason'))} · "
                f"{_format_time(latest.get('requested_at'))}"
            )
            if latest.get("reason"):
                lines.append(f"  — Причина: {_short(latest.get('reason'))}")
            if latest.get("error_message"):
                lines.append(
                    f"  — Ошибка: {_format_error(latest.get('error_class'), latest.get('error_message'))}"
                )

    archive = snapshot.get("fvg_archive", {})
    lines.extend(["", "Архив FVG"])
    health = archive.get("runtime_health", {})
    if not archive.get("exists"):
        lines.append("• Файл: не создан")
    else:
        file_status = "доступен" if archive.get("available") else "ошибка"
        lines.append(
            f"• Файл: {file_status} · {_format_bytes(archive.get('total_bytes'))}"
        )
    if archive.get("error_message"):
        lines.append(f"• Ошибка чтения: {_short(archive.get('error_message'))}")
    latest_run = archive.get("latest_run")
    if latest_run:
        lines.extend([
            f"• Последний перенос: {_format_time(latest_run.get('archived_at'))}",
            "• Batch: "
            f"событий {int(latest_run.get('event_count') or 0)}, "
            f"доставок {int(latest_run.get('delivery_count') or 0)}, "
            f"удалено {int(latest_run.get('source_deleted_count') or 0)}",
            f"• Cutoff: {_format_time(latest_run.get('cutoff_at'))}",
        ])
    elif archive.get("available"):
        lines.append("• Переносов пока нет")
    if health:
        lines.extend([
            "• Всего: "
            f"событий {int(health.get('events_archived') or 0)}, "
            f"доставок {int(health.get('deliveries_archived') or 0)}",
            f"• Ошибок архивирования: {int(health.get('fvg_archive_failures') or 0)}",
            f"• Backlog возможен: {'да' if health.get('fvg_archive_backlog_possible') else 'нет'}",
        ])
        if health.get("last_archive_at"):
            lines.append(f"• Health update: {_format_time(health.get('last_archive_at'))}")
        if health.get("last_archive_error"):
            lines.append(f"• Последняя ошибка: {_short(health.get('last_archive_error'))}")

    tasks = snapshot.get("tasks", {})
    lines.extend(["", "Фоновые задачи"])
    if not tasks.get("available"):
        lines.append("• registry: нет данных")
    else:
        counts = tasks.get("counts", {})
        counts_text = ", ".join(
            f"{_status_label(status)}: {count}"
            for status, count in sorted(counts.items())
        ) or "нет зарегистрированных задач"
        lines.extend([
            f"• Всего: {int(tasks.get('total') or 0)}",
            f"• Статусы: {counts_text}",
            f"• Просрочено: {int(tasks.get('overdue_count') or 0)}",
            f"• Истёк lease: {int(tasks.get('expired_lease_count') or 0)}",
        ])
        problems = tasks.get("problems", [])
        if problems:
            lines.append("• Требуют внимания:")
            for item in problems[:5]:
                flags = []
                if item.get("expired_lease"):
                    flags.append("lease")
                if item.get("overdue"):
                    flags.append("overdue")
                if item.get("consecutive_failures"):
                    flags.append(f"ошибок подряд {item['consecutive_failures']}")
                suffix = f" · {', '.join(flags)}" if flags else ""
                error_code = item.get("last_error_code")
                error_suffix = f" · {error_code}" if error_code else ""
                lines.append(
                    f"  — {item['task_name']}: {_status_label(item.get('status'))}{suffix}{error_suffix}"
                )

    databases = snapshot.get("databases", {})
    lines.extend(["", "Снимки баз данных"])
    if not databases.get("available"):
        lines.append("• observability: нет данных")
    else:
        latest = databases.get("latest", [])
        if not latest:
            lines.append("• снимков пока нет")
        for item in latest:
            label = _DATABASE_LABELS.get(item.get("database_key"), item.get("database_key"))
            total = (
                int(item.get("main_bytes") or 0)
                + int(item.get("wal_bytes") or 0)
                + int(item.get("shm_bytes") or 0)
            )
            availability = "доступна" if item.get("available") else "ошибка"
            lines.append(
                f"• {label}: {availability} · {_format_bytes(total)} · {_format_time(item.get('captured_at'))}"
            )
            if item.get("error_message"):
                lines.append(f"  — {_short(item['error_message'])}")

        growth = databases.get("growth_24h", [])
        if growth:
            lines.append("• Изменение за 24 часа:")
            for item in growth:
                label = _DATABASE_LABELS.get(item.get("database_key"), item.get("database_key"))
                lines.append(
                    f"  — {label}: файл {_format_signed_bytes(item.get('main_bytes_delta'))}, used {_format_signed_bytes(item.get('used_bytes_delta'))}"
                )

    lines.extend(["", f"Снимок: {_format_time(snapshot.get('captured_at'))}"])
    return "\n".join(lines)


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
        DATA_DIR / name
        for name in (
            "fvg_alert_settings.json",
            "user_preferences.json",
            "runtime_settings.json",
            "access_control.json",
            "user_activity.json",
        )
    ]
    json_size = sum(path.stat().st_size for path in json_files if path.exists())
    return "\n".join([
        "🗄 Состояние баз данных", "",
        f"FVG SQLite: {event_status} · {_format_bytes(event_size)}",
        f"Funding SQLite: {funding_status} · {_format_bytes(funding_size)}",
        f"JSON-настройки: {_format_bytes(json_size)}",
    ])


def _memory_bytes() -> int:
    path = Path("/proc/self/status")
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def format_resource_status() -> str:
    try:
        load = " / ".join(f"{value:.2f}" for value in os.getloadavg())
    except (AttributeError, OSError):
        load = "—"
    disk = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else PROJECT_DIR)
    return "\n".join([
        "🖥 Память и нагрузка", "", f"Память процесса: {_format_bytes(_memory_bytes())}",
        f"Load average 1/5/15: {load}",
        f"Свободно на диске: {_format_bytes(disk.free)} из {_format_bytes(disk.total)}",
        f"PID: {os.getpid()}",
    ])


def format_version() -> str:
    version_path, commit_path = PROJECT_DIR / "VERSION", PROJECT_DIR / "BUILD_COMMIT"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
    commit = commit_path.read_text(encoding="utf-8").strip() if commit_path.exists() else "не записан"
    return "\n".join([
        "🏷 Версия установленного релиза", "", f"Версия: {version}",
        f"Git commit: {commit}", f"Python: {sys.version.split()[0]}"
    ])


def create_manual_backup() -> str:
    MANUAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "INSTALL_DIR": str(PROJECT_DIR),
        "DATA_DIR": str(DATA_DIR.resolve()),
        "BACKUP_DIR": str(MANUAL_BACKUP_DIR.resolve()),
        "PYTHON": sys.executable,
        "RETENTION_DAYS": "14",
    })
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
    query, user = update.callback_query, update.effective_user
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
        enabled = await asyncio.to_thread(
            _RUNTIME_SETTINGS.toggle_public_access,
            PUBLIC_ACCESS_ENABLED,
        )
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
    elif action == "operations":
        await query.edit_message_text(await asyncio.to_thread(format_operations_status), reply_markup=admin_keyboard())
    elif action == "databases":
        await query.edit_message_text(await asyncio.to_thread(format_database_status), reply_markup=admin_keyboard())
    elif action == "resources":
        await query.edit_message_text(await asyncio.to_thread(format_resource_status), reply_markup=admin_keyboard())
    elif action == "version":
        await query.edit_message_text(format_version(), reply_markup=admin_keyboard())
    elif action == "backup":
        try:
            text = f"✅ Резервная копия создана.\n\n{await asyncio.to_thread(create_manual_backup)}"
        except Exception as error:
            text = f"⚠️ Не удалось создать резервную копию.\n\n{error}"
        await query.edit_message_text(text, reply_markup=admin_keyboard())
    elif action == "restart":
        await query.edit_message_text(
            "♻️ Перезапустить бота?\n\nПосле подтверждения бот штатно остановится, а systemd запустит его снова.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, перезапустить", callback_data="admin:restart_confirm")],
                [InlineKeyboardButton("❌ Отмена", callback_data="admin:home")],
            ]),
        )
    elif action == "restart_confirm":
        await query.edit_message_text("♻️ Бот завершает работу для перезапуска…")
        try:
            request_sigterm_restart()
        except OSError as error:
            await query.edit_message_text(
                f"⚠️ Не удалось запросить перезапуск.\n\n{error}",
                reply_markup=admin_keyboard(),
            )
