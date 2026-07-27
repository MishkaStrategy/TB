# FVG Alert Bot

Telegram-бот для отслеживания Fair Value Gap (FVG) на Bitunix и ставок фандинга
на нескольких фьючерсных биржах. Бот отправляет уведомления и показывает
статистику, но не открывает сделки и не является финансовой рекомендацией.

Текущая версия ветки `main`: **1.1.0**.

## Возможности

- предварительные FVG-уведомления в точке T−3;
- подтверждённые FVG на 15-минутном таймфрейме;
- индивидуальные символы, направления, ценовые диапазоны и размеры зоны;
- автоматическое включение подтверждённых FVG для `BTCUSDT` при первом `/start`;
- рейтинг положительных и отрицательных ставок через `/funding`;
- переключение между Bitunix, Binance, Bybit, Bitget и Gate;
- персональные funding-уведомления с интервалом от 1 до 48 часов;
- выбор бирж, направления и процентного порога отдельными галочками;
- подавление повторных уведомлений до нового пересечения порога;
- приватный и публичный режим из `/admin` без перезапуска;
- общий WebSocket Bitunix, watchdog и REST recovery для FVG;
- SQLite/WAL для событий, доставок, outbox, funding-state и health-метрик;
- атомарное VDS-обновление, автоматический rollback и ежедневные backup;
- event-quality backtest без искусственного P&L.

Подробности:

- [`docs/RELEASE_1.1.0.md`](docs/RELEASE_1.1.0.md);
- [`docs/MULTI_EXCHANGE_FUNDING.md`](docs/MULTI_EXCHANGE_FUNDING.md).

## Мультибиржевой фандинг

В `/funding` над пагинацией находятся переключатели бирж:

- Bitunix;
- Binance;
- Bybit;
- Bitget;
- Gate.

Выбранная биржа помечается галочкой. Кнопка обновления запрашивает свежие данные
только для открытой биржи. Почасовая служебная задача в `HH:50 UTC` получает по
одному общему снимку каждой подключённой биржи и использует его для всех
пользователей — отдельные копии полного рынка на каждого пользователя не создаются.

Все значения приводятся к процентным пунктам. Например, ставка API `0.0001`
отображается как `0.01%`. Bitunix уже возвращает процентные пункты и дополнительно
не умножается.

## Уведомления о фандинге

Откройте `/funding` и нажмите `🔔 Уведомления`. Для каждого Telegram ID можно
настроить:

- частоту от `1` до `48` часов;
- минимальный абсолютный процент фандинга;
- положительное, отрицательное или оба направления;
- одну или несколько бирж отдельными галочками;
- включение и выключение рассылки.

Нельзя снять последнюю галочку направления или биржи. Уведомление приходит только
при новом пересечении порога. Если одна выбранная биржа временно недоступна, бот
продолжает обрабатывать остальные и не считает ошибку API возвратом ставки под
порог.

Настройки и состояние пересечений хранятся в:

```text
data/funding_alerts.sqlite3
```

Существующие настройки Bitunix сохраняются при обновлении. Активные старые
пересечения однократно переносятся в мультибиржевую таблицу, чтобы обновление не
создало повторные сигналы. Полная история снимков не сохраняется. Устаревшие
пересечения удаляются через 7 дней, выключенные неактивные настройки — через
180 дней. Раз в сутки выполняются WAL checkpoint и incremental vacuum.

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

API-ключи бирж для FVG и текущих funding-ставок не требуются.

## Первая установка на Ubuntu/Debian VDS

Поддерживаются Ubuntu 22.04/24.04 и Debian 12. Перед установкой убедитесь, что
на файловой системе `/opt` доступно не менее 1 ГБ и 5000 inode.

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
apt update && apt install -y git
git clone https://github.com/mishkacher/TB.git /root/TB
cd /root/TB
git checkout main
test "$(cat VERSION)" = "1.1.0"
FVG_INSTALL_MIN_FREE_MB=1024 bash scripts/install_vds.sh
```

При первом запуске установщик запросит токен BotFather и Telegram ID
администратора. Он создаёт staging-релиз, новый virtualenv, выполняет компиляцию
и unit-тесты, затем останавливает работающий процесс, делает backup и атомарно
переключает релиз. При ошибке запуска выполняется rollback.

## Обновление существующего VDS до 1.1.0

Используйте подготовленный wrapper:

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
cd /root/TB
git fetch origin --prune
git checkout main
git pull --ff-only origin main
EXPECTED_VERSION=1.1.0 bash scripts/update_vds.sh
```

Скрипт:

1. проверяет root, чистоту Git checkout и наличие существующей установки;
2. выполняет только fast-forward обновление `main`;
3. проверяет целевую версию `1.1.0`;
4. создаёт согласованный pre-update backup runtime-state;
5. запускает атомарный установщик с минимальным запасом 1 ГБ;
6. проверяет systemd, версию и ссылку на runtime-state;
7. выполняет `PRAGMA quick_check` для обеих SQLite-баз;
8. записывает установленный Git commit в `/opt/fvg-alert-bot/BUILD_COMMIT`.

Файл `/etc/fvg-alert-bot.env` и каталог `/var/lib/fvg-alert-bot` сохраняются.
Повторно вводить токен и Telegram ID не требуется.

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

Ожидаемая версия:

```text
1.1.0
```

В Telegram проверьте `/menu`, `/funding` и `/admin`. Переключите несколько бирж
в рейтинге, затем откройте `🔔 Уведомления`, отметьте нужные биржи, задайте порог
и убедитесь, что следующая проверка назначена на `HH:50`.

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

Код и virtualenv принадлежат `root`. Процесс `fvgbot` записывает данные только в
`/var/lib/fvg-alert-bot`.

## Резервные копии и rollback

Ежедневный архив содержит JSON-state и согласованные SQLite-снимки обеих баз.
Live WAL/SHM-файлы в архив не копируются.

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Установщик хранит предыдущий релиз в `/opt/fvg-alert-bot.previous`. Подробные
процедуры восстановления: [`docs/VDS_DEPLOYMENT.md`](docs/VDS_DEPLOYMENT.md).

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
```

Telegram `Conflict` означает, что тот же токен используется другим
polling-процессом.

## Команды Telegram

- `/menu` — панель управления;
- `/fvg_alert on|off` — подтверждённые FVG;
- `/fvg_pre_alert on|off` — пред-FVG T−3;
- `/fvg_symbol add ETHUSDT` — добавить инструмент;
- `/fvg_symbol remove ETHUSDT` — удалить инструмент;
- `/fvg_price BTCUSDT 50000 90000 both` — ценовой фильтр;
- `/fvg_size` — фильтр размера зоны;
- `/fvg_stats` — статистика FVG;
- `/funding` — мультибиржевой рейтинг и funding-уведомления;
- `/admin` — состояние сервиса и режим доступа.

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

## Проверки

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

CI проверяет shell-скрипты, компиляцию Python, unit-тесты, согласованность backup,
funding-scheduler, очистку SQLite, dependency audit, bounded soak,
Linux/systemd units и Bitunix research smoke.
