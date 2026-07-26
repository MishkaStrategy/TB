# Changelog

## 1.0.0-rc2 — 2026-07-26

Исправление первой установки на VDS с медленным диском или загруженным CPU.

### Исправлено

- корректностный unit-soak больше не отклоняет установку из-за скорости конкретного сервера;
- строгий performance-порог сохранён в отдельном CI soak `500 × 10` с лимитом 180 секунд;
- повторная установка использует уже сохранённые Telegram token и admin ID из `/etc/fvg-alert-bot.env`.

## 1.0.0-rc1 — 2026-07-26

Первый release candidate FVG Alert Bot.

### Основные возможности

- поток свечей Bitunix через WebSocket с периодическим REST recovery;
- подтверждённые FVG и предварительные сигналы T−3;
- индивидуальные символы, направления и фильтры цены/размера;
- SQLite/WAL вместо перезаписи растущего JSON на горячем пути;
- постоянный Telegram outbox с retry/backoff и восстановлением после рестарта;
- закрытый production-доступ по allow-list, квоты и rate limiting;
- systemd-установка с автозапуском, sandboxing, backup и rollback;
- CI с unit-тестами, bounded soak и исследовательским smoke-тестом;
- исторический анализ качества FVG без выдуманного P&L.

### Эксплуатационные дополнения rc1

- Linux-runner проверяет точные systemd units из установочного скрипта;
- `pip-audit` проверяет закреплённые Python-зависимости;
- админ-панель показывает состояние WebSocket, recovery, SQLite и outbox;
- администраторы получают throttled-уведомления о сбоях и восстановлении;
- Dependabot следит за Python и GitHub Actions зависимостями.

### Перед production

Release candidate должен пройти установку на Ubuntu/Debian VDS, reboot,
backup/restore, имитацию сетевого сбоя и наблюдение 24–72 часа.
