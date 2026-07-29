# Mini App API contract

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Telegram ID извлекается сервером и не принимается из JSON-body.
- Все значения повторно валидируются backend до первой записи.
- Ответ содержит нормализованную полную модель настроек.
- Точные десятичные значения передаются строками.
- Административные поля возвращаются только после повторной проверки `is_admin(telegram_id)`.
- Общий `PUT` не выполняет backup, restart и изменение allowlist.

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

Для обычного пользователя `admin.available=false`, allowlist пуст, а `diagnostics` сохраняет ту же полную схему с безопасными значениями `unknown`, `null` и `0`.

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

Отправляется полная структура из GET. Ответ имеет тот же формат и содержит значения после серверной нормализации.

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

## Административные данные

Источники:

- `RuntimeSettings`;
- `AccessRegistry`;
- `UserActivityRegistry`;
- health-метрики FVG event store;
- `PRAGMA quick_check` SQLite;
- `/proc/self/status` или `resource.getrusage`;
- `os.getloadavg`;
- `shutil.disk_usage`;
- `VERSION`, `BUILD_COMMIT` и версия Python.

Через общий PUT администратор может менять только `publicAccessEnabled`. `available`, `allowedUsers` и `diagnostics` являются server-owned и read-only.

Будущие опасные операции используют отдельные endpoint:

```text
POST /api/mini-app/admin/backup
POST /api/mini-app/admin/restart/prepare
POST /api/mini-app/admin/restart/confirm
POST /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
```

## Ошибки

```json
{
  "error": {
    "code": "INVALID_FUNDING_INTERVAL",
    "message": "Частота должна быть от 15 минут до 48 часов с шагом 15 минут.",
    "field": "settings.funding.intervalMinutes"
  }
}
```

Коды HTTP:

- `400` — формат или валидация;
- `401` — отсутствует или не прошёл проверку Telegram `initData`;
- `403` — нет доступа;
- `415` — неверный Content-Type;
- `500` — внутренняя ошибка без раскрытия секретов.
