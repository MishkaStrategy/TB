# Telegram delivery status rollout

Этот этап добавляет отдельное состояние Telegram-доставки, не меняя модель доступа пользователя и не вводя Outbox V2.

## Разделение состояний

- `database/access_control.py` продолжает отвечать только за право пользоваться ботом.
- `telegram_delivery_profiles.status` описывает только возможность доставлять сообщения в Telegram.
- состояние конкретного FVG-сообщения по-прежнему определяется существующими таблицами `outbox` и `deliveries`.
- временная или постоянная причина хранится в `last_error_code` и `last_error_message`.

## Статусы доставки

- `active` — доставка разрешена;
- `temporarily_unavailable` — последняя ошибка временная, новые FVG-записи пока разрешены и используют текущий retry;
- `blocked` — пользователь заблокировал бота;
- `deactivated` — аккаунт или чат недоступен;
- `suspended` — доставка невозможна из-за прав или другого административного ограничения Telegram.

`rate_limited` не является отдельным постоянным статусом. Он хранится как `temporarily_unavailable` с кодом `rate_limited` и Telegram `retry_after`.

## Permanent errors

К permanent относятся:

- `bot was blocked by the user`;
- удалённый или деактивированный аккаунт;
- отсутствующий чат;
- исключение бота из группы;
- недостаточные права;
- окончательно недоступное для редактирования сообщение.

Retry для текущей permanent-ошибки не создаётся. Полное подавление будущих уведомлений и атомарная очистка существующего FVG backlog выполняются только при `USER_BLOCK_STATUS_ENABLED=true`.

При включённом только `DELIVERY_STATUS_TRACKING_ENABLED` профиль и причина ошибки сохраняются, но текущая логика выбора будущих получателей и funding schedule не изменяется. Это позволяет сначала наблюдать реальные статусы без влияния на доставку.

## Temporary errors

К temporary относятся:

- `RetryAfter`;
- timeout;
- network errors;
- Telegram 5xx и gateway errors;
- пока не классифицированные исключения.

На этом этапе временные ошибки сохраняют существующий FVG backoff. Ограничение попыток, jitter, expiration и dead-letter входят в следующий этап Outbox V2.

## Ignorable errors

`message is not modified`, устаревший callback и отсутствие уже удалённого сообщения считаются завершёнными без retry.

## Восстановление

Любой новый входящий update пользователя выполняет `TelegramDeliveryRegistry.record_interaction()`:

1. статус становится `active`;
2. сбрасывается `consecutive_failures`;
3. очищается последняя ошибка;
4. записываются `last_interaction_at` и `recovered_at`;
5. при включённом suppression старый backlog после permanent-состояния не восстанавливается.

Новые уведомления после восстановления доставляются штатно.

## Funding

Funding пока не переведён в общий outbox. При `USER_BLOCK_STATUS_ENABLED=true` и permanent-состоянии:

- сообщение не отправляется;
- текущий crossing-state сохраняется;
- расписание продвигается дальше;
- после восстановления crossing, возникший во время блокировки, не отправляется задним числом.

При tracking-only permanent funding error записывается в профиль, но schedule остаётся due, как в прежнем поведении. Временная funding-ошибка также не продвигает расписание и будет повторно обработана текущим scheduler.

## Feature flags

```env
DELIVERY_STATUS_TRACKING_ENABLED=false
USER_BLOCK_STATUS_ENABLED=false
```

Флаги независимы:

- `DELIVERY_STATUS_TRACKING_ENABLED` включает только запись профиля, ошибок, успехов и восстановления;
- `USER_BLOCK_STATUS_ENABLED` дополнительно включает suppression, очистку backlog и consumption funding crossing без последующей массовой отправки.

Рекомендуемый rollout:

1. Выпустить код с обоими флагами `false`.
2. Включить `DELIVERY_STATUS_TRACKING_ENABLED=true` и проверить создание таблицы и запись успешных/неуспешных доставок.
3. Включить `USER_BLOCK_STATUS_ENABLED=true` и проверить suppression blocked/deactivated/suspended chats.
4. Наблюдать `delivery_suppressed_inactive_users`, `delivery_permanent_failures`, `delivery_rate_limited` и размер outbox.

При выключенных флагах FVG и funding используют прежний путь доставки.

## Rollback

Оба флага можно выключить без миграции назад. Таблица `telegram_delivery_profiles` является additive и не влияет на прежние запросы. Удалять таблицу при rollback не требуется.
