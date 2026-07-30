# Mini App API contract

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Telegram ID текущего пользователя извлекается сервером и не принимается из JSON-body.
- Все значения повторно валидируются backend до первой записи.
- Точные десятичные значения передаются строками.
- Административные данные и операции доступны только после повторной проверки `is_admin(telegram_id)`.
- Общий `PUT /settings` сохраняет только персональные настройки.
- Режим доступа, allowlist, backup и restart выполняются только через отдельные endpoints.
- Каждое административное изменение требует короткоживущего одноразового подтверждения.

## Авторизация

Frontend передаёт исходную строку Telegram:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend проверяет HMAC-SHA-256, обязательные поля, отсутствие дубликатов, `auth_date`, срок действия и допустимое отклонение времени.

## GET `/api/mini-app/settings`

Пример сокращённого ответа:

```json
{
  "settings": {
    "general": {
      "language": "ru",
      "messageMode": "detailed"
    },
    "fvg": {
      "enabled": false,
      "notifyConfirmedFvg": true,
      "notifyPreFvg": false,
      "bullishEnabled": true,
      "bearishEnabled": true,
      "symbols": [
        {
          "symbol": "BTCUSDT",
          "enabled": true,
          "priceFilter": {
            "enabled": false,
            "min": null,
            "max": null,
            "scope": {
              "preFvg": true,
              "confirmedFvg": true,
              "bullish": true,
              "bearish": true
            }
          },
          "sizeFilter": {
            "enabled": false,
            "unit": "USD",
            "min": null,
            "scope": {
              "preFvg": true,
              "confirmedFvg": true,
              "bullish": true,
              "bearish": true
            }
          }
        }
      ]
    },
    "funding": {
      "enabled": false,
      "intervalMinutes": 60,
      "threshold": "0.1",
      "notifyPositive": true,
      "notifyNegative": true,
      "exchanges": ["bitunix"],
      "nextCheckAt": null
    },
    "admin": {
      "available": true,
      "publicAccessEnabled": false,
      "allowedUsers": [],
      "capabilities": {
        "accessWrite": true,
        "allowlistWrite": true,
        "backup": false,
        "restart": false
      },
      "diagnostics": {
        "websocket": "connected",
        "lastWebsocketMessage": "2026-07-29T12:00:00+00:00",
        "lastRestRecovery": "2026-07-29T11:45:00+00:00",
        "lastError": null,
        "outbox": 2,
        "deliveries": 12480,
        "deliveryFailures": 7,
        "deliveryRetries": 19,
        "deliveryPermanentFailures": 1,
        "databases": "ok",
        "fvgDatabaseStatus": "ok",
        "fvgDatabaseBytes": 3420160,
        "fundingDatabaseStatus": "ok",
        "fundingDatabaseBytes": 921600,
        "jsonSettingsBytes": 48128,
        "processMemoryBytes": 118489088,
        "loadAverage": [0.24, 0.31, 0.28],
        "diskFreeBytes": 68719476736,
        "diskTotalBytes": 107374182400,
        "pid": 2481,
        "release": "1.2.0",
        "gitCommit": "abc123",
        "pythonVersion": "3.12.8"
      }
    }
  },
  "user": {
    "id": 123456789,
    "firstName": "Михаил",
    "username": "example"
  },
  "limits": {
    "maxFvgSymbols": 20
  },
  "source": "api",
  "updatedAt": "2026-07-29T12:00:00+00:00"
}
```

Для обычного пользователя `admin.available=false`; все admin capabilities имеют значение `false`, а диагностика сохраняет стабильную безопасную схему.

`capabilities.backup` и `capabilities.restart` становятся `true` только после подключения production callbacks. До этого endpoints существуют, но завершаются fail-closed ошибкой `409`.

## PUT `/api/mini-app/settings`

```json
{
  "settings": {
    "general": {},
    "fvg": {},
    "funding": {},
    "admin": {}
  }
}
```

Отправляется полная структура из GET. Backend сохраняет только `general`, `fvg` и `funding`. Объект `admin` принимается для совместимости модели, но не выполняет административных записей.

Ответ имеет тот же формат и содержит значения после серверной нормализации.

## Маппинг `general`

Источник: `database.user_preferences.UserPreferences`.

| Mini App | Хранилище |
|---|---|
| `language` | `language` |
| `messageMode` | `message_mode` |

Допустимые значения:

- `language`: `ru`, `en`;
- `messageMode`: `compact`, `detailed`.

## Маппинг `fvg`

Источник: `alerts.fvg_store.FvgAlertSettings`.

| Mini App | Хранилище |
|---|---|
| `enabled` | `enabled` |
| `notifyConfirmedFvg` | `notify_confirmed_fvg` |
| `notifyPreFvg` | `notify_pre_fvg` |
| `bullishEnabled` | `bullish_enabled` |
| `bearishEnabled` | `bearish_enabled` |
| `symbols[].symbol` | ключ в `symbols` |
| `symbols[].enabled` | `symbols[symbol].enabled` |
| `priceFilter.*` | `price_filter.*` |
| `sizeFilter.*` | `size_filter.*` |

Scope:

| Mini App | Хранилище |
|---|---|
| `preFvg` | `apply_to_pre_fvg` |
| `confirmedFvg` | `apply_to_confirmed_fvg` |
| `bullish` | `apply_to_bullish` |
| `bearish` | `apply_to_bearish` |

Ограничения:

- максимум `MAX_SYMBOLS_PER_USER` инструментов;
- символ из 5–20 латинских букв и цифр, нормализованный в uppercase;
- отсутствие дубликатов после нормализации;
- границы — конечные неотрицательные Decimal;
- минимальная цена не выше максимальной;
- размер FVG использует только минимум;
- единица размера: `USD` или `PERCENT`.

## Маппинг `funding`

Источники:

- `alerts.funding_quarter_hour.FundingAlertStore`;
- `alerts.funding_exchange_store.FundingExchangeStore`.

| Mini App | Хранилище/метод |
|---|---|
| `enabled` | `enabled` / `set_enabled` |
| `intervalMinutes` | `interval_minutes` / `set_interval` |
| `threshold` | `threshold` / `set_threshold` |
| `notifyPositive` | `notify_positive` |
| `notifyNegative` | `notify_negative` |
| `exchanges` | `selected` / `set_selected` |
| `nextCheckAt` | `next_check_at`, read-only |

Ограничения:

- интервал 15–2880 минут с шагом 15 минут;
- threshold — конечное положительное число;
- выбрано хотя бы одно направление;
- выбрана хотя бы одна поддерживаемая биржа;
- биржи: `bitunix`, `binance`, `bybit`, `bingx`, `bitget`, `gate`.

При изменении порога, направлений, бирж или отключении рассылки очищается legacy и мультибиржевой crossing-state.

## Одноразовое подтверждение admin-действия

### POST `/api/mini-app/admin/confirmations`

```json
{
  "action": "allowlist.add",
  "telegramId": 123456789
}
```

Поддерживаемые действия:

- `allowlist.add`;
- `allowlist.remove`;
- `access.public`;
- `access.private`;
- `backup.create`;
- `bot.restart`.

Для allowlist-действий `telegramId` обязателен. Ответ:

```json
{
  "token": "one-time-random-token",
  "action": "allowlist.add",
  "confirmationText": "ALLOW 123456789",
  "expiresAt": "2026-07-30T00:02:00+00:00"
}
```

Токен:

- действует 120 секунд по умолчанию;
- привязан к проверенному Telegram ID администратора;
- привязан к точному действию и целевому Telegram ID;
- удаляется при первой попытке использования;
- не может быть повторно использован или перенесён на другую цель.

## Режим доступа

### PUT `/api/mini-app/admin/access`

```json
{
  "publicAccessEnabled": true,
  "confirmationToken": "one-time-random-token",
  "confirmationText": "PUBLIC ACCESS"
}
```

Режим сохраняется через существующий `RuntimeSettings`.

## Allowlist

### POST `/api/mini-app/admin/allowlist`

```json
{
  "telegramId": 123456789,
  "name": "Михаил",
  "username": "example",
  "confirmationToken": "one-time-random-token",
  "confirmationText": "ALLOW 123456789"
}
```

Создаёт или заменяет runtime-запись со статусом `allowed`. При отсутствии имени backend использует данные `UserActivityRegistry`, если пользователь уже взаимодействовал с ботом.

### DELETE `/api/mini-app/admin/allowlist/{telegram_id}`

```json
{
  "confirmationToken": "one-time-random-token",
  "confirmationText": "REMOVE 123456789"
}
```

Env-allowlist и администраторов нельзя удалить через Mini App. Удаляются только runtime-записи `AccessRegistry`.

## Backup

### POST `/api/mini-app/admin/backup`

```json
{
  "confirmationToken": "one-time-random-token",
  "confirmationText": "CREATE BACKUP"
}
```

Endpoint вызывает только переданный production callback. Mini App backend не запускает shell или `systemctl` самостоятельно. Пока callback не подключён, capability равна `false`, а endpoint возвращает `409 BACKUP_ACTION_UNAVAILABLE`.

## Restart

### POST `/api/mini-app/admin/restart`

```json
{
  "confirmationToken": "one-time-random-token",
  "confirmationText": "RESTART BOT"
}
```

Endpoint вызывает только переданный production restart callback. До интеграции с graceful restart/restart-guard capability равна `false`, а endpoint возвращает `409 RESTART_ACTION_UNAVAILABLE`.

## Ошибки

```json
{
  "error": {
    "code": "CONFIRMATION_MISMATCH",
    "message": "Подтверждение не соответствует действию или пользователю.",
    "field": "confirmationToken"
  }
}
```

Основные коды подтверждения:

- `CONFIRMATION_TOKEN_REQUIRED`;
- `CONFIRMATION_INVALID`;
- `CONFIRMATION_EXPIRED`;
- `CONFIRMATION_MISMATCH`;
- `CONFIRMATION_TEXT_MISMATCH`;
- `ADMIN_REQUIRED`;
- `PROTECTED_ACCESS_RECORD`;
- `BACKUP_ACTION_UNAVAILABLE`;
- `RESTART_ACTION_UNAVAILABLE`.

Коды HTTP:

- `200` — операция выполнена;
- `201` — challenge или allowlist-запись создана;
- `202` — production callback принял backup/restart;
- `400` — формат или валидация;
- `401` — отсутствует или не прошёл проверку Telegram `initData`;
- `403` — нет доступа или административных прав;
- `404` — runtime allowlist-запись не найдена;
- `409` — истёкшее/повторное/несоответствующее подтверждение или отключённый adapter;
- `415` — неверный Content-Type;
- `500` — внутренняя ошибка без раскрытия секретов.
