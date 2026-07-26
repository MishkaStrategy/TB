# Проверка release candidate 1.0.0-rc1

## Что проверяет CI

Основной workflow выполняет unit-тесты, компиляцию, bounded soak на 500 событий
и 10 получателей, аудит Python-зависимостей и необязательный smoke-тест свежей
истории Bitunix.

Отдельный Linux job запускается на self-hosted runner с метками
`self-hosted`, `linux`, `fast`. Он извлекает **точные** systemd unit-файлы из
`scripts/install_vds.sh`, подставляет безопасные временные пути и выполняет
`systemd-analyze verify`.

## Операционные уведомления

Бот отправляет сообщения всем ID из `ADMIN_TELEGRAM_IDS`, когда:

- Bitunix WebSocket явно отключён;
- при активных символах давно не было WS-свечей;
- Telegram outbox достиг заданного порога;
- появились новые ошибки REST recovery, контрольной точки или retry-job;
- активная проблема восстановилась.

Настройки:

```env
HEALTH_ALERT_INTERVAL_SECONDS=60
HEALTH_ALERT_STALE_WS_SECONDS=180
HEALTH_ALERT_OUTBOX_THRESHOLD=100
HEALTH_ALERT_COOLDOWN_SECONDS=1800
```

Повторные сообщения об одной продолжающейся проблеме ограничены cooldown.

## Canary-порядок на VDS

1. Остановить все другие polling-процессы с тем же Telegram-токеном.
2. Установить rc1 на Ubuntu 22.04/24.04 или Debian 12.
3. Проверить `is-active`, `is-enabled`, журнал и `/admin → Состояние бота`.
4. Добавить один-два символа и убедиться, что обновляется время WS-свечи.
5. Перезагрузить VDS и подтвердить автоматический старт.
6. Запустить backup вручную и восстановить архив в отдельную тестовую копию.
7. На несколько минут заблокировать исходящий доступ и проверить reconnect,
   REST recovery, outbox и админ-уведомление о восстановлении.
8. Проверить rollback на заведомо неработающем staging-релизе.
9. Наблюдать 24–72 часа: `NRestarts`, `MemoryCurrent`, размер SQLite, outbox,
   `last_error`, recovery failures.
10. После стабильного canary расширить список символов и пользователей.
