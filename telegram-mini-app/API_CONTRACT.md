# Mini App API contract

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Telegram ID текущего пользователя извлекается сервером и не принимается из JSON-body.
- Backend повторно валидирует полный personal-settings payload до записи.
- Точные десятичные значения передаются строками.
- Общий `PUT /api/mini-app/settings` сохраняет только персональные настройки.
- Access mode, allowlist, backup и restart используют отдельные admin endpoints.
- Каждое административное изменение требует короткоживущего одноразового подтверждения.
- Backend API выключен по умолчанию и должен слушать только loopback.

## Авторизация

Frontend передаёт raw Telegram init data:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend проверяет HMAC-SHA-256, обязательные поля, отсутствие дубликатов, `auth_date`, срок действия и допустимое future skew. `initDataUnsafe` не используется как источник идентичности.

## GET `/api/mini-app/settings`

Сокращённый пример ответа для FVG 1.3.4:

```json
{
  "settings": {
    "general": {
      "language": "ru",
      "messageMode": "detailed"
    },
    "fvg": {
      "enabled": true,
      "notifyConfirmedFvg": true,
      "bullishEnabled": true,
      "bearishEnabled": true,
      "symbols": [
        {
          "key": "binance|BTCUSDT",
          "exchange": "binance",
          "symbol": "BTCUSDT",
          "timeframes": ["15m", "1h", "4h", "1d"],
          "enabled": true,
          "priceFilter": {
            "enabled": false,
            "min": null,
            "max": null,
            "scope": {
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
      "diagnostics": {}
    }
  },
  "user": {
    "id": 123456789,
    "firstName": "Михаил"
  },
  "limits": {
    "maxFvgSymbols": 10
  },
  "source": "api",
  "updatedAt": "2026-08-10T12:00:00+00:00"
}
```

Bitunix сохраняет legacy-compatible key `BTCUSDT`; остальные биржи используют `exchange|symbol`. Клиент должен считать `key` непрозрачным стабильным идентификатором строки и возвращать его без самостоятельной подмены.

`notifyPreFvg` и `scope.preFvg` в API 1.3.4 отсутствуют. Даже если legacy-клиент добавит такие поля, backend не позволяет повторно включить pre-FVG: storage keys нормализуются в `false`.

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

Отправляется полная personal-settings модель из GET. Backend сохраняет `general`, `fvg` и `funding`; production runtime service игнорирует административные записи в общем PUT.

Ответ повторяет GET и содержит значения после server-side нормализации.

## `general`

Источник: `database.user_preferences.UserPreferences`.

| Mini App | Store |
|---|---|
| `language` | `language` |
| `messageMode` | `message_mode` |

Допустимо:

- `language`: `ru`, `en`;
- `messageMode`: `compact`, `detailed`.

## `fvg`

Источник: `alerts.fvg_store.FvgAlertSettings`, schema v3.

| Mini App | Store |
|---|---|
| `enabled` | `enabled` |
| `notifyConfirmedFvg` | `notify_confirmed_fvg` |
| `bullishEnabled` | `bullish_enabled` |
| `bearishEnabled` | `bearish_enabled` |
| `symbols[].key` | stable instrument key |
| `symbols[].exchange` | `symbols[key].exchange` |
| `symbols[].symbol` | `symbols[key].symbol` |
| `symbols[].timeframes` | `symbols[key].timeframes` |
| `symbols[].enabled` | `symbols[key].enabled` |
| `priceFilter.*` | `price_filter.*` |
| `sizeFilter.*` | `size_filter.*` |

Ограничения:

- максимум 10 уникальных `exchange + symbol`;
- биржи: `bitunix`, `binance`, `bybit`, `bingx`, `bitget`, `gate`;
- символ: 5–20 латинских букв/цифр, uppercase после нормализации;
- таймфреймы: `15m`, `1h`, `4h`, `1d`, минимум один;
- stable key обязан соответствовать `exchange + symbol`;
- одинаковый symbol разрешён на разных биржах и хранится независимо;
- price boundaries — конечные неотрицательные Decimal, min ≤ max;
- size unit — `USD` или `PERCENT`;
- pre-FVG отсутствует и storage-compatible pre flags принудительно `false`.

Runtime 1.3.4 получает от бирж только закрытые `15m` свечи; `1h/4h/1d` агрегируются локально. Mini App сохраняет именно выбор целевых таймфреймов, а не меняет источник market data.

## `funding`

Источники:

- `alerts.funding_quarter_hour.FundingAlertStore`;
- `alerts.funding_exchange_store.FundingExchangeStore`.

| Mini App | Store/method |
|---|---|
| `enabled` | `enabled` / `set_enabled` |
| `intervalMinutes` | `interval_minutes` / `set_interval` |
| `threshold` | `threshold` / `set_threshold` |
| `notifyPositive` | `notify_positive` |
| `notifyNegative` | `notify_negative` |
| `exchanges` | `selected` / `set_selected` |
| `nextCheckAt` | read-only |

Ограничения:

- интервал 15–2880 минут с шагом 15;
- threshold — валидный положительный процент;
- минимум одно направление;
- минимум одна поддерживаемая биржа.

При изменении порога, направлений, бирж или отключении рассылки очищается соответствующий crossing-state.

## Admin confirmation flow

### POST `/api/mini-app/admin/confirmations`

Пример:

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

Challenge:

- короткоживущий;
- одноразовый;
- привязан к проверенному admin Telegram ID;
- привязан к точному action и target;
- replay, retarget, неверная фраза и истёкший token отклоняются.

### Admin endpoints

```text
POST   /api/mini-app/admin/confirmations
PUT    /api/mini-app/admin/access
POST   /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
POST   /api/mini-app/admin/backup
POST   /api/mini-app/admin/restart
```

Env allowlist и administrators защищены от удаления. Backup/restart endpoints существуют, но остаются fail-closed, пока application lifecycle не передаст проверенные production callbacks; shell/systemctl fallback отсутствует.

## Health

```text
GET /healthz
```

Не требует Telegram auth и подтверждает только доступность HTTP backend, а не полный end-to-end Telegram flow.

## CORS / origin

Production frontend рассчитан на same-origin `/api` по умолчанию. При публикации на отдельном origin backend должен получить точный `MINI_APP_ALLOWED_ORIGINS=https://<approved-host>`; wildcard не используется.
