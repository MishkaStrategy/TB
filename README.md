# FVG Alert Bot

Telegram-бот для отслеживания Fair Value Gap (FVG) на фьючерсном рынке Bitunix.
Бот отправляет уведомления и показывает статистику, но не открывает сделки и не
является финансовой рекомендацией.

Текущая версия ветки `main`: **1.0.0-rc10**.

## Возможности

- предварительные FVG-уведомления в точке T−3;
- подтверждённые FVG на 15-минутном таймфрейме;
- индивидуальные символы, направления, ценовые диапазоны и размеры зоны;
- автоматическое включение подтверждённых FVG для `BTCUSDT` при первом `/start`;
- повторный `/start` не отменяет ручное отключение уведомлений;
- рейтинг ставок фандинга Bitunix через `/funding`;
- переключение приватного и публичного доступа из `/admin` без перезапуска;
- общий WebSocket Bitunix, watchdog зависшего потока и REST recovery;
- SQLite/WAL для событий, доставок, outbox и health-метрик;
- атомарное VDS-обновление, автоматический rollback и ежедневные backup;
- event-quality backtest без выдуманных торговых правил и P&L.

## Локальный запуск

Создайте `.env` рядом с `bot.py`:

```env
TELEGRAM_TOKEN=токен_от_BotFather
ADMIN_TELEGRAM_IDS=123456789
ALLOWED_TELEGRAM_IDS=123456789
PUBLIC_ACCESS_ENABLED=false
```

Установите зависимости и запустите бота:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python bot.py
```

`PUBLIC_ACCESS_ENABLED=false` — безопасный режим по умолчанию. API-ключи Bitunix
для FVG и funding не требуются.

## Установка на Ubuntu/Debian VDS

Поддерживаются Ubuntu 22.04/24.04 и Debian 12. Нужны исходящие HTTPS/WSS
соединения к Telegram и Bitunix. Входящие порты, домен и веб-сервер не требуются.

Перед установкой убедитесь, что на файловой системе `/opt` доступно не менее
512 МБ и 5000 inode. Один Telegram-токен может использовать только один
polling-процесс.

### Первая установка из `main`

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
apt update && apt install -y git
git clone https://github.com/mishkacher/TB.git /root/TB
cd /root/TB
git checkout main
git pull --ff-only origin main
bash scripts/install_vds.sh
```

При первом запуске установщик запросит токен BotFather и Telegram ID
администратора. ID будет добавлен одновременно в `ADMIN_TELEGRAM_IDS` и
`ALLOWED_TELEGRAM_IDS`.

Установщик:

- проверяет свободное место и inode;
- создаёт пользователя `fvgbot` и изолированный virtualenv;
- собирает кандидат в отдельном staging-каталоге;
- выполняет компиляцию Python и unit-тесты до остановки текущей службы;
- сохраняет runtime-state и backup;
- атомарно переключает активный релиз;
- запускает systemd-службу и backup-таймер;
- автоматически возвращает предыдущий релиз, если новый не запускается.

### Обновление VDS после bugfix или новой функции

```bash
cd /root/TB
git fetch origin --prune
git checkout main
git pull --ff-only origin main
bash scripts/install_vds.sh
```

Файл `/etc/fvg-alert-bot.env` и каталог `/var/lib/fvg-alert-bot` при обновлении
сохраняются. Повторно вводить токен и Telegram ID не требуется.

### Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
```

Ожидаемая версия после текущего обновления:

```text
1.0.0-rc10
```

В Telegram проверьте `/menu`, `/funding` и `/admin`. В админ-панели кнопка
`🔐 Доступ: приватный` / `🌐 Доступ: публичный` меняет режим сразу и сохраняет
его в `data/runtime_settings.json`.

## Production-настройки

Основной файл:

```bash
nano /etc/fvg-alert-bot.env
```

Минимальная конфигурация:

```env
TELEGRAM_TOKEN=токен_из_BotFather
ADMIN_TELEGRAM_IDS=123456789
ALLOWED_TELEGRAM_IDS=123456789
PUBLIC_ACCESS_ENABLED=false
```

Несколько ID перечисляются через запятую. При приватном доступе ID
администратора должен присутствовать и в `ALLOWED_TELEGRAM_IDS`.

После ручного редактирования:

```bash
chown root:fvgbot /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
```

Защитные лимиты и operational alerts:

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

## Файлы на VDS

| Назначение | Путь |
|---|---|
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state и SQLite | `/var/lib/fvg-alert-bot` |
| Секреты и production-настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

Код и virtualenv принадлежат `root`. Процесс `fvgbot` записывает данные только в
`/var/lib/fvg-alert-bot`.

## Резервные копии и rollback

Проверьте backup-таймер:

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl status fvg-alert-bot-backup.timer --no-pager
```

Запуск backup вручную:

```bash
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Установщик хранит предыдущий релиз в `/opt/fvg-alert-bot.previous`. Подробные
процедуры восстановления и canary-проверки находятся в
[`docs/VDS_DEPLOYMENT.md`](docs/VDS_DEPLOYMENT.md) и
[`docs/VDS_FIRST_INSTALL_RECOVERY.md`](docs/VDS_FIRST_INSTALL_RECOVERY.md).

## Диагностика

Telegram `Conflict` означает, что тот же токен используется другим
polling-процессом.

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
df -h / /tmp /opt
df -ih / /tmp /opt
getent hosts api.telegram.org
getent hosts fapi.bitunix.com
```

## Команды Telegram

- `/menu` — панель управления;
- `/fvg_alert on|off` — подтверждённые FVG;
- `/fvg_pre_alert on|off` — пред-FVG T−3;
- `/fvg_symbol add ETHUSDT` — добавить инструмент;
- `/fvg_symbol remove ETHUSDT` — удалить инструмент;
- `/fvg_price BTCUSDT 50000 90000 both` — ценовой фильтр;
- `/fvg_size` — фильтр размера зоны;
- `/fvg_stats` — статистика FVG;
- `/funding` — топ положительных и отрицательных ставок;
- `/admin` — админ-панель, состояние сервиса и режим доступа.

## Fibonacci

Подтверждённый профиль уровней TradingView хранится в
[`fibonacci-settings.json`](fibonacci-settings.json). Он является справочным
артефактом и не влияет на FVG-рассылку.

## Историческая проверка FVG

```bash
.venv/bin/python download_bitunix_history.py \
  --symbol BTCUSDT --interval 15m \
  --start 2025-01-01 --end 2026-01-01 \
  --output data/historical/btcusdt_15m_2025.csv

.venv/bin/python run_fvg_quality_backtest.py \
  --data-file data/historical/btcusdt_15m_2025.csv \
  --symbol BTCUSDT \
  --output data/reports/btcusdt_fvg_quality_2025.json
```

Отчёт измеряет touch/full fill, задержку заполнения, MFE/MAE и горизонты
1/4/16/96 свечей. Методология описана в
[`docs/FVG_BACKTEST.md`](docs/FVG_BACKTEST.md).

## Проверки

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

CI проверяет shell-скрипты, компиляцию Python, unit-тесты, dependency audit,
bounded soak, Linux/systemd units и research smoke по публичным данным Bitunix.
