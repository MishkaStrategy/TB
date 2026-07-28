# FVG Alert Bot

Telegram-бот для отслеживания Fair Value Gap (FVG) на Bitunix и ставок фандинга на нескольких фьючерсных биржах. Бот отправляет уведомления и показывает статистику, но не открывает сделки и не является финансовой рекомендацией.

Текущая версия релизной ветки: **1.2.0**.

## Возможности

- предварительные FVG-уведомления в точке T−3;
- подтверждённые FVG на 15-минутном таймфрейме;
- индивидуальные инструменты, направления, ценовые диапазоны и размеры зоны;
- автоматическое включение подтверждённых FVG для `BTCUSDT` при первом `/start`;
- общий WebSocket Bitunix, stale-watchdog, process watchdog и REST recovery;
- мультибиржевой рейтинг фандинга: Bitunix, Binance, Bybit, Bitget, Gate и BingX;
- персональные funding-уведомления с частотой 1–48 часов;
- выбор бирж, направления и процентного порога;
- подавление повторов до нового пересечения порога;
- постоянное нижнее Telegram-меню;
- русский и английский интерфейс отдельно для каждого Telegram ID;
- компактный и подробный формат FVG/funding-уведомлений;
- приватный и публичный режим без перезапуска;
- расширенная админ-панель с backup, SQLite, очередью, ресурсами и restart;
- донат-раздел для USDT, ETH и BNB;
- SQLite/WAL для событий, доставок, outbox, funding-state и health-метрик;
- атомарное VDS-обновление, rollback и ежедневные backup.

Подробности релиза: [`docs/RELEASE_1.2.0.md`](docs/RELEASE_1.2.0.md).

## Telegram-интерфейс

После `/start` бот закрепляет нижнее меню:

- `📉 FVG`;
- `💸 Фандинг`;
- `🔔 Уведомления`;
- `📊 Статистика`;
- `⚙️ Настройки`;
- `❤️ Донат`.

В пользовательских настройках доступны:

- язык: русский или английский;
- формат уведомлений: компактный или подробный;
- переход к FVG и funding alerts;
- админ-настройки для Telegram ID администратора.

Настройки языка и формата хранятся в `data/user_preferences.json`. В production каталог `data` является ссылкой на `/var/lib/fvg-alert-bot`.

## Мультибиржевой фандинг

Команда `/funding` показывает положительные и отрицательные ставки по шести биржам:

- Bitunix;
- Binance;
- Bybit;
- Bitget;
- Gate;
- BingX.

Выбранная биржа отмечается галочкой. Почасовая задача в `HH:50 UTC` получает один общий снимок каждой подключённой биржи и использует его для всех пользователей.

Для funding alerts можно настроить:

- частоту от `1` до `48` часов;
- минимальный абсолютный процент;
- положительное, отрицательное или оба направления;
- одну или несколько бирж;
- включение и выключение рассылки.

Настройки и состояние пересечений хранятся в `data/funding_alerts.sqlite3`. Ошибка одной биржи не останавливает обработку остальных.

## Админ-панель

Команда `/admin` доступна только ID из `ADMIN_TELEGRAM_IDS`. Панель позволяет:

- переключать публичный и приватный доступ;
- просматривать allowlist;
- проверять WebSocket и REST recovery;
- видеть состояние outbox и доставок;
- выполнять `PRAGMA quick_check` баз;
- смотреть память, load average и свободное место;
- создать ручной backup;
- увидеть VERSION, BUILD_COMMIT и Python;
- подтвердить перезапуск процесса через systemd.

Административные права проверяются заново при каждом callback.

## Локальный запуск

Создайте `.env` рядом с `bot.py`:

```env
TELEGRAM_TOKEN=токен_от_BotFather
ADMIN_TELEGRAM_IDS=123456789
ALLOWED_TELEGRAM_IDS=123456789
PUBLIC_ACCESS_ENABLED=false
```

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python bot.py
```

API-ключи бирж для FVG и текущих funding-ставок не требуются.

## Первая установка на Ubuntu/Debian VDS

Поддерживаются Ubuntu 22.04/24.04 и Debian 12. Требуется не менее 1 ГБ свободного места на файловой системе `/opt` и 5000 inode.

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
apt update && apt install -y git
git clone https://github.com/MishkaStrategy/TB.git /root/TB
cd /root/TB
git checkout main
test "$(cat VERSION)" = "1.2.0"
FVG_INSTALL_MIN_FREE_MB=1024 bash scripts/install_vds.sh
```

Установщик собирает staging-релиз и выполняет unit-тесты до остановки работающего процесса. Затем он создаёт backup, атомарно переключает релиз и автоматически возвращает предыдущую версию при ошибке запуска.

## Обновление существующего VDS до 1.2.0

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main
EXPECTED_VERSION=1.2.0 bash scripts/update_vds.sh
```

`scripts/update_vds.sh`:

1. проверяет root, чистоту checkout и существующую установку;
2. выполняет только fast-forward обновление `main`;
3. проверяет `VERSION=1.2.0`;
4. создаёт согласованный pre-update backup runtime-state;
5. запускает атомарный установщик с запасом не менее 1 ГБ;
6. проверяет systemd, версию и ссылку на runtime-state;
7. выполняет `PRAGMA quick_check` обеих SQLite-баз;
8. записывает Git SHA в `/opt/fvg-alert-bot/BUILD_COMMIT`.

Сохраняются `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot` и пользовательские настройки. Повторно вводить токен и Telegram ID не требуется.

## Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Ожидается:

```text
1.2.0
active
enabled
```

В Telegram проверьте `/start`, `/menu`, `/funding`, `/admin` и `/donate`, переключение языка и оба формата уведомлений.

## Production-настройки

Основной файл:

```bash
nano /etc/fvg-alert-bot.env
```

Защитные лимиты:

```env
MAX_ACTIVE_SYMBOLS=100
MAX_SYMBOLS_PER_USER=20
FVG_DELIVERY_QUEUE_SIZE=1000
HEALTH_WRITE_INTERVAL_SECONDS=30
BITUNIX_REQUESTS_PER_SECOND=8
HEALTH_ALERT_INTERVAL_SECONDS=60
HEALTH_ALERT_STALE_WS_SECONDS=180
HEALTH_ALERT_OUTBOX_THRESHOLD=100
HEALTH_ALERT_COOLDOWN_SECONDS=1800
```

После ручного изменения:

```bash
chown root:fvgbot /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
```

## Файлы на VDS

| Назначение | Путь |
|---|---|
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state и SQLite | `/var/lib/fvg-alert-bot` |
| Секреты и production-настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

Код и virtualenv принадлежат `root`. Процесс `fvgbot` записывает данные только в `/var/lib/fvg-alert-bot`.

## Backup и rollback

Ежедневный архив содержит JSON-state и согласованные SQLite-снимки обеих баз. Live WAL/SHM и каталог `.manual_backups` в архив не копируются.

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Установщик хранит предыдущий релиз в `/opt/fvg-alert-bot.previous`. Подробные процедуры: [`docs/VDS_DEPLOYMENT.md`](docs/VDS_DEPLOYMENT.md).

## Диагностика

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
df -h / /tmp /opt
df -ih / /tmp /opt
getent hosts api.telegram.org
getent hosts fapi.bitunix.com
getent hosts fapi.binance.com
getent hosts api.bybit.com
getent hosts api.bitget.com
getent hosts api.gateio.ws
getent hosts open-api.bingx.com
```

Telegram `Conflict` означает, что тот же токен используется другим polling-процессом.

## Команды

- `/menu` — открыть меню;
- `/fvg_alert on|off` — подтверждённые FVG;
- `/fvg_pre_alert on|off` — пред-FVG T−3;
- `/fvg_symbol add ETHUSDT` — добавить инструмент;
- `/fvg_symbol remove ETHUSDT` — удалить инструмент;
- `/fvg_price BTCUSDT 50000 90000 both` — ценовой фильтр;
- `/fvg_size` — фильтр размера зоны;
- `/fvg_stats` — статистика FVG;
- `/funding` — мультибиржевой рейтинг и funding alerts;
- `/admin` — админ-панель;
- `/donate` — поддержать проект.

## Проверки

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

CI проверяет shell-скрипты, компиляцию Python, dependency audit, unit-тесты, backup/SQLite, bounded soak, Linux/systemd units, Bitunix research smoke и self-hosted runner labels.
