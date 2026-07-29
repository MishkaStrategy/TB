# Telegram Outbox V2

Outbox V2 заменяет только слой хранения и повторной доставки FVG-уведомлений. Detector, фильтры, WebSocket, REST recovery и формат сообщений не меняются.

## State machine

```text
pending ───────────────→ processing ───────────────→ delivered
   │                         │
   │                         ├─ temporary ─────────→ retry_scheduled
   │                         ├─ permanent ─────────→ failed_permanent
   │                         ├─ ambiguous timeout ─→ dead_letter
   │                         └─ max attempts ──────→ dead_letter
   │
   ├─ expires_at reached ───→ expired
   └─ unavailable user ─────→ cancelled

retry_scheduled ───────→ processing
```

Terminal states:

- `delivered`;
- `failed_permanent`;
- `expired`;
- `cancelled`;
- `dead_letter`.

## Tables

### `telegram_outbox`

Хранит:

- UUID записи;
- notification/event type;
- event ID, user ID и chat ID;
- operation и payload;
- уникальный idempotency key;
- status;
- attempts и max attempts;
- next/last attempt;
- processing lease и worker ID;
- error class/code/message;
- created/updated/expires/delivered/finalized timestamps;
- Telegram message ID после успеха.

### `telegram_outbox_attempts`

Ограниченная историей самой outbox-записи таблица попыток. Она удаляется каскадно при retention cleanup terminal item.

### `telegram_outbox_domain_sync`

Фиксирует синхронизацию terminal state с прежними таблицами FVG `outbox` и `deliveries`.

## Atomic claim

Worker использует `BEGIN IMMEDIATE`, выбирает due rows и переводит их в `processing` с:

- `worker_id`;
- `processing_started_at`;
- `lease_until`;
- увеличенным `attempts`.

Второй worker не может одновременно claim ту же запись.

## Stale processing после рестарта

Если lease истёк, результат предыдущей отправки неизвестен. Telegram мог принять сообщение до остановки процесса.

Поэтому stale `processing` не возвращается в retry автоматически. Запись переводится в `dead_letter` с кодом:

```text
delivery_outcome_unknown
```

Это сознательная защита от двойной отправки. Позднее администратор сможет проверить и вручную решить судьбу записи.

## Retry policy

Default:

- max attempts: 8;
- base delay: 5 секунд;
- exponential backoff;
- jitter: ±20%;
- max delay: 900 секунд;
- processing lease: 120 секунд;
- terminal retention: 30 дней.

`RetryAfter` Telegram имеет приоритет над локальным backoff.

## Timeout policy

Не все timeout одинаковы:

- connect/pool timeout до установленного соединения безопасно повторяется;
- read/write/unknown timeout может произойти после принятия `sendMessage` Telegram;
- неоднозначный timeout переводится в `dead_letter`, а не повторяется автоматически.

Exactly-once для Telegram `sendMessage` после неоднозначного сетевого результата недостижим без внешней поддержки Telegram. Выбран at-most-once подход для такого узкого случая минимизирует дубли торговых уведомлений.

## Expiration

При `OUTBOX_EXPIRATION_ENABLED=true`:

- PRE-FVG истекает в `candle_c_close_time`;
- confirmed FVG истекает через `OUTBOX_DEFAULT_TTL_SECONDS` после detection;
- expired item не claim-ится и не отправляется.

Expiration включается отдельно после стабилизации retry policy.

## Idempotency

Для FVG используется:

```text
fvg:{event_id}:{chat_id}
```

Unique constraint не позволяет повторной обработке свечи, recovery, scheduler или restart создать вторую логическую доставку.

## Rollback compatibility

При включённом V2 новая FVG-доставка записывается:

1. в `telegram_outbox` как основной item;
2. в старый `outbox` как неактивное rollback-зеркало.

Пока флаг включён, legacy worker не используется. При terminal state compatibility bridge:

- `delivered` вызывает прежний `mark_delivered()`;
- permanent/expired/cancelled/dead-letter вызывает прежний `abandon_delivery()`;
- terminal sync фиксируется идемпотентно.

Pending/retry mirror остаётся доступным, если feature flag потребуется выключить.

## Feature flags

```env
OUTBOX_RETRY_POLICY_ENABLED=false
OUTBOX_EXPIRATION_ENABLED=false
```

Параметры:

```env
OUTBOX_MAX_ATTEMPTS=8
OUTBOX_BASE_BACKOFF_SECONDS=5
OUTBOX_MAX_BACKOFF_SECONDS=900
OUTBOX_JITTER_RATIO=0.2
OUTBOX_PROCESSING_LEASE_SECONDS=120
OUTBOX_TERMINAL_RETENTION_DAYS=30
OUTBOX_DEFAULT_TTL_SECONDS=3600
```

`OUTBOX_JITTER_RATIO` принимает значение от `0` до `1`. Значение `0.2` означает случайное отклонение задержки в пределах ±20%.

## Rollout

1. Сначала стабилизировать delivery status из предыдущего PR.
2. Выпустить код с `OUTBOX_RETRY_POLICY_ENABLED=false`.
3. Включить `OUTBOX_RETRY_POLICY_ENABLED=true`, expiration оставить выключенным.
4. Проверить pending/retry/dead-letter, delivery latency и rollback mirror.
5. После стабильного периода включить `OUTBOX_EXPIRATION_ENABLED=true`.

## Rollback

Выключение `OUTBOX_RETRY_POLICY_ENABLED` возвращает scheduler к существующему `FvgAlertService`. Pending и retry rows доступны в старом outbox-зеркале. Terminal rows туда не возвращаются.

Перед rollback желательно выполнить один штатный worker pass, чтобы синхронизировать последние terminal states.

## Не входит в этот этап

- funding через общий outbox;
- admin dead-letter actions;
- ручной retry;
- редактирование Telegram-сообщений;
- database retention dashboard;
- отдельная архивная база.
