# Mini App API contract

## Статус реализации

Реализованы:

- `GET /healthz`;
- `GET /api/mini-app/settings`;
- `PUT /api/mini-app/settings`;
- проверка Telegram `initData`;
- проверка срока действия `auth_date`;
- публичный/приватный режим доступа;
- чтение и сохранение общих, FVG и funding-настроек;
- серверная проверка административных прав;
- структурированные ошибки;
- ограничение размера запроса;
- точный CORS allowlist;
- очистка мультибиржевого funding crossing-state.

Опасные административные действия пока не реализованы и не входят в общий `PUT`.

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Заголовок: `X-Telegram-Init-Data`.
- Telegram ID из JSON-body не используется для идентификации.
- Все числовые значения принимаются строками там, где важна точность `Decimal`.
- Ответ всегда содержит нормализованную полную модель настроек.
- Частичные обновления не используются: `PUT` сохраняет полную модель после серверной валидации.
- Поля административного раздела возвращаются только после повторной проверки `is_admin(telegram_id)`.
- Максимальный размер тела запроса по умолчанию — 256 КБ.

## GET `/healthz`

Endpoint не требует Telegram-авторизации и используется только для проверки доступности API.

```json
{
  "status": "ok",
  "service": "telegram-mini-app"
}
```

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
  "limits": {
    "maxFvgSymbols": 20
  },
  "source": "api",
  "updatedAt": "2026-07-29T12:00:00Z"
}
```

`limits.maxFvgSymbols` формируется backend из текущего `MAX_SYMBOLS_PER_USER`. Frontend не должен использовать жёстко заданный лимит.

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

Фактически отправляется полная структура `settings` из GET. Поля `user`, `limits`, `source` и `updatedAt` обратно не отправляются.

Ответ имеет тот же формат, что GET, и содержит значения после серверной нормализации.

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

Серверная валидация:

- максимум `MAX_SYMBOLS_PER_USER` инструментов;
- символ нормализуется в uppercase;
- длина символа — 5–20 латинских букв и цифр;
- дубликаты после нормализации запрещены;
- границы должны быть конечными неотрицательными Decimal;
- минимальная цена не выше максимальной;
- размер использует только минимум;
- `sizeFilter.unit`: `USD` или `PERCENT`.

Полная FVG-модель пользователя записывается одной транзакцией только после успешной валидации всего payload.

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
- threshold — конечное строго положительное число;
- выбрано хотя бы одно направление;
- выбрана хотя бы одна биржа;
- биржи: `bitunix`, `binance`, `bybit`, `bingx`, `bitget`, `gate`;
- после изменений порога, направлений или бирж очищается мультибиржевой crossing-state;
- при отключении рассылки crossing-state также очищается.

### `admin`

Источники:

- `database.runtime_settings.RuntimeSettings`;
- `database.access_control.AccessRegistry`;
- `database.user_activity.UserActivityRegistry`;
- health-данные FVG event store;
- SQLite `PRAGMA quick_check`;
- файл `VERSION`.

`available` вычисляется сервером и не сохраняется из пользовательского payload.

Через общий PUT разрешено изменять только `publicAccessEnabled`, и только подтверждённому администратору. Для обычного пользователя административные значения из payload игнорируются.

Поля `allowedUsers` и `diagnostics` read-only.

Backup, restart и изменение allowlist должны использовать отдельные endpoint с повторным подтверждением:

```text
POST /api/mini-app/admin/backup
POST /api/mini-app/admin/restart/prepare
POST /api/mini-app/admin/restart/confirm
POST /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
```

Backend не доверяет `admin.available` или любым административным значениям, пришедшим от frontend.

## Доступ

В приватном режиме пользователь допускается, если выполняется хотя бы одно условие:

- Telegram ID находится в `ALLOWED_TELEGRAM_IDS`;
- Telegram ID находится в `ADMIN_TELEGRAM_IDS`;
- пользователь разрешён через `AccessRegistry`;
- серверная проверка `is_admin` успешна.

В публичном режиме доступ разрешён всем пользователям с корректным Telegram `initData`.

## CORS

`MINI_APP_ALLOWED_ORIGINS` содержит точный список origins через запятую. Разрешение `*` не используется.

Если frontend и API размещены на одном origin, CORS можно не настраивать.

## Ошибки

Формат:

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
- `401` — отсутствует, просрочен или не прошёл проверку Telegram `initData`;
- `403` — доступ к Mini App или административному действию запрещён;
- `415` — неверный `Content-Type`;
- `500` — внутренняя ошибка сохранения.

## Переменные окружения

```env
MINI_APP_BACKEND_ENABLED=false
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=8080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=
```

API выключен по умолчанию и не изменяет работу production-бота, пока `MINI_APP_BACKEND_ENABLED` не установлен в `true`.
