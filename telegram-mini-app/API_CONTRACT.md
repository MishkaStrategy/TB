# Mini App API contract

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Все числовые значения принимаются строками там, где важна точность `Decimal`.
- Ответ всегда содержит нормализованную полную модель настроек.
- Частичные обновления на первом этапе не используются: `PUT` сохраняет полную модель после серверной валидации.
- Поля административного раздела возвращаются только после повторной проверки `is_admin(telegram_id)`.

## GET `/api/mini-app/settings`

Пример ответа:

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
      "available": false,
      "publicAccessEnabled": false,
      "allowedUsers": [],
      "diagnostics": {
        "websocket": "unknown",
        "outbox": 0,
        "deliveryFailures": 0,
        "databases": "unknown",
        "release": "1.2.0"
      }
    }
  },
  "user": {
    "id": 123456789,
    "firstName": "Михаил",
    "username": "example"
  },
  "source": "api",
  "updatedAt": "2026-07-29T12:00:00Z"
}
```

## PUT `/api/mini-app/settings`

Body:

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

Фактически отправляется полная структура из GET. Ответ имеет тот же формат, что GET, и содержит значения после серверной нормализации.

## Маппинг на текущий Python-код

### `general`

Источник: `database.user_preferences.UserPreferences`.

| Mini App | Текущее поле |
|---|---|
| `language` | `language` |
| `messageMode` | `message_mode` |

Допустимые значения:

- `language`: `ru`, `en`;
- `messageMode`: `compact`, `detailed`.

### `fvg`

Источник: `alerts.fvg_store.FvgAlertSettings`.

| Mini App | Текущее поле |
|---|---|
| `enabled` | `enabled` |
| `notifyConfirmedFvg` | `notify_confirmed_fvg` |
| `notifyPreFvg` | `notify_pre_fvg` |
| `bullishEnabled` | `bullish_enabled` |
| `bearishEnabled` | `bearish_enabled` |
| `symbols[].symbol` | ключ в `symbols` |
| `symbols[].enabled` | `symbols[symbol].enabled` |
| `priceFilter.enabled` | `price_filter.enabled` |
| `priceFilter.min` | `price_filter.min` |
| `priceFilter.max` | `price_filter.max` |
| `sizeFilter.enabled` | `size_filter.enabled` |
| `sizeFilter.unit` | `size_filter.unit` |
| `sizeFilter.min` | `size_filter.min` |

Маппинг scope:

| Mini App | Текущее поле фильтра |
|---|---|
| `preFvg` | `apply_to_pre_fvg` |
| `confirmedFvg` | `apply_to_confirmed_fvg` |
| `bullish` | `apply_to_bullish` |
| `bearish` | `apply_to_bearish` |

Серверная валидация должна повторно использовать текущие ограничения:

- максимум `MAX_SYMBOLS_PER_USER` инструментов;
- символ нормализуется в uppercase;
- границы должны быть конечными неотрицательными Decimal;
- минимальная цена не выше максимальной;
- размер использует только минимум;
- `sizeFilter.unit`: `USD` или `PERCENT`.

### `funding`

Источники:

- `alerts.funding_quarter_hour.FundingAlertStore`;
- `alerts.funding_exchange_store.FundingExchangeStore`.

| Mini App | Текущее поле/метод |
|---|---|
| `enabled` | `enabled` / `set_enabled` |
| `intervalMinutes` | `interval_minutes` / `set_interval` |
| `threshold` | `threshold` / `set_threshold` |
| `notifyPositive` | `notify_positive` |
| `notifyNegative` | `notify_negative` |
| `exchanges` | `FundingExchangeStore.selected/set_selected` |
| `nextCheckAt` | `next_check_at`, read-only |

Ограничения:

- интервал от 15 до 2880 минут;
- шаг интервала 15 минут;
- threshold — конечное неотрицательное число;
- выбрано хотя бы одно направление;
- выбрана хотя бы одна биржа;
- биржи: `bitunix`, `binance`, `bybit`, `bingx`, `bitget`, `gate`;
- после изменений порога, направлений или бирж очищается crossing-state.

### `admin`

Источники:

- `database.runtime_settings.RuntimeSettings`;
- `database.access_control.AccessRegistry`;
- `database.user_activity.UserActivityRegistry`;
- health-данные из `handlers.admin_settings`.

`available` вычисляется сервером и не сохраняется из пользовательского payload.

На первом этапе через общий PUT разрешено изменять только `publicAccessEnabled`. Поля `allowedUsers` и `diagnostics` считаются read-only. Backup, restart и изменение allowlist должны использовать отдельные endpoint с повторным подтверждением:

```text
POST /api/mini-app/admin/backup
POST /api/mini-app/admin/restart/prepare
POST /api/mini-app/admin/restart/confirm
POST /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
```

Backend не должен доверять `admin.available` или любым административным значениям, пришедшим от frontend.

## Ошибки

Рекомендуемый формат:

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

- `400` — ошибка формата или валидации;
- `401` — отсутствует или не прошёл проверку Telegram `initData`;
- `403` — нет административных прав;
- `409` — конфликт версии настроек при добавлении optimistic locking;
- `500` — внутренняя ошибка сохранения.
