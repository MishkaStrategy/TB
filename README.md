# FVG Alert Bot

Telegram-бот для отслеживания Fair Value Gap (FVG) на фьючерсном рынке
Bitunix. Он специализируется только на FVG: уведомлениях, настройках и
статистике событий. Бот не открывает сделки и не является финансовой
рекомендацией.

## Возможности

- предварительные FVG-уведомления в точке T−3;
- подтверждённые FVG на 15-минутном таймфрейме;
- настройка инструментов, направлений, цены и размера зоны отдельно для
  каждого Telegram-пользователя;
- статистика бычьих и медвежьих FVG, включая доставленные уведомления;
- админ-панель со статистикой пользователей;
- общий WebSocket Bitunix с REST-восстановлением пропущенных данных;
- bounded delivery queue, REST rate limiting и повторные попытки доставки;
- production-default с закрытым доступом и ограничениями ресурсов;
- атомарное VDS-обновление, rollback и ежедневные резервные копии.

## Локальный запуск

1. Создайте `.env` рядом с `bot.py`, используя `.env.example`:

   ```env
   TELEGRAM_TOKEN=токен_от_BotFather
   ALLOWED_TELEGRAM_IDS=123456789
   ADMIN_TELEGRAM_IDS=123456789
   PUBLIC_ACCESS_ENABLED=false
   ```

2. Создайте virtualenv и установите зависимости:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Запустите бота:

   ```bash
   .venv/bin/python bot.py
   ```

`PUBLIC_ACCESS_ENABLED=false` — безопасный режим по умолчанию. Публичный доступ
нужно включать явно. `BITUNIX_API_KEY` и `BITUNIX_SECRET` для FVG не требуются.

Для локального перезапуска доступен `./restart_bot.py`: он останавливает только
экземпляры `bot.py`, запущенные из текущей папки проекта.

Для постоянной работы на Ubuntu/Debian VDS используйте
[инструкцию по развёртыванию](docs/VDS_DEPLOYMENT.md). Установщик тестирует
staging-релиз до остановки работающего процесса и выполняет rollback при ошибке.

## Команды

- `/menu` — панель настроек FVG;
- `/fvg_alert on|off` — включить или выключить FVG-уведомления;
- `/fvg_pre_alert on|off` — включить или выключить пред-FVG T−3;
- `/fvg_symbol add ETHUSDT` — добавить инструмент в наблюдение;
- `/fvg_symbol remove ETHUSDT` — убрать инструмент;
- `/fvg_price BTCUSDT 50000 90000 both` — настроить ценовой фильтр;
- `/fvg_size` — настроить фильтр размера зоны;
- `/fvg_stats` — показать статистику FVG;
- `/admin` — админ-панель и статистика пользователей.

## Проверки

Текущие handler-тесты используют явно включённый публичный test fixture:

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

Также CI проверяет синтаксис VDS shell-скриптов и компиляцию Python-модулей.
