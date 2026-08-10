# Mini App API contract

## Общие правила

- Авторизация выполняется только по проверенному Telegram `initData`.
- Telegram ID текущего пользователя извлекается сервером и не принимается из JSON-body.
- Backend повторно валидирует полный personal-settings payload до записи.
- Точные десятичные значения настроек передаются строками.
- Общий `PUT /api/mini-app/settings` сохраняет только персональные настройки.
- Volatile market state не смешивается с mutable settings и читается отдельным endpoint.
- Access mode, allowlist, backup и restart используют отдельные admin endpoints.
- Каждое административное изменение требует короткоживущего одноразового подтверждения.
- Backend API выключен по умолчанию и должен слушать только loopback.

## Авторизация

Frontend передаёт raw Telegram init data:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend проверяет HMAC-SHA-256, обязательные поля, отсутствие дубликатов, `auth_date`, срок действия и допустимый future skew. `initDataUnsafe` используется только для необязательного отображения пользователя во frontend и не является источником server-side identity.

## GET `/api/mini-app/settings`

Сокращённый пример ответа:

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

Bitunix сохраняет legacy-compatible key `BTCUSDT`; остальные биржи используют `exchange|symbol`. Клиент считает `key` непрозрачным стабильным идентификатором строки и возвращает его без самостоятельной подмены.

`notifyPreFvg` и `scope.preFvg` отсутствуют. Даже если legacy-клиент добавит такие поля, backend не позволяет повторно включить pre-FVG: storage keys нормализуются в `false`.

## GET `/api/mini-app/market-overview`

Read-only endpoint для volatile market state. Он не принимает `exchange`, `symbol` или Telegram ID из query/body. Backend сначала проходит Telegram auth/access control и формирует список только из уже сохранённых FVG-инструментов пользователя.

Пример:

```json
{
  "instruments": [
    {
      "key": "binance|BTCUSDT",
      "exchange": "binance",
      "symbol": "BTCUSDT",
      "price": null,
      "priceChange24hPct": 1.42,
      "source": "ticker"
    },
    {
      "key": "bybit|ETHUSDT",
      "exchange": "bybit",
      "symbol": "ETHUSDT",
      "price": null,
      "priceChange24hPct": null,
      "source": "unavailable"
    }
  ],
  "updatedAt": "2026-08-10T12:00:00+00:00"
}
```

### Определение `priceChange24hPct`

`priceChange24hPct` — процент изменения цены за 24 часа для конкретной пары `exchange + symbol`. Это не FVG percentage и не funding rate.

Backend переиспользует существующие public market adapters проекта:

- Bitunix: 24h ticker, изменение из `last/open`;
- Binance: futures 24h ticker `priceChangePercent`;
- Bybit: linear ticker `price24hPcnt`;
- Bitget: futures ticker `change24h`;
- Gate: futures ticker `change_percentage`;
- если текущий exchange adapter не предоставляет 24h change (в частности BingX), применяется fallback по закрытым `15m` свечам: последняя закрытая цена сравнивается с закрытой ценой 24 часа назад.

Внешние запросы используют существующие public REST adapters и их bounded request timeout; API keys не требуются. Exchange groups обрабатываются в ограниченном thread pool, поэтому сетевые вызовы не блокируют aiohttp event loop. Ошибка одной биржи изолируется и не ломает остальные строки. Бесконечных retry нет.

Результат кешируется backend на короткий TTL (по умолчанию 30 секунд) с ограниченным числом cache entries. Cache key включает Telegram ID и точный набор сохранённых `key + exchange + symbol`, поэтому изменения списка инструментов не получают stale snapshot прежнего набора.

Если market value получить нельзя, `priceChange24hPct` возвращается как `null`; frontend обязан показывать `—`, а не `0%`.

Поле `price` зарезервировано для read-only текущей цены и сейчас возвращается `null`; frontend не должен вычислять 24h change самостоятельно.

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

Отправляется полная personal-settings модель из GET. Backend сохраняет `general`, `fvg` и `funding`; production runtime service игнорирует административные записи в общем PUT. Ответ повторяет GET и содержит значения после server-side нормализации.

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

Runtime получает от бирж только закрытые `15m` свечи; `1h/4h/1d` агрегируются локально. Mini App сохраняет именно выбор целевых таймфреймов, а не меняет источник market data.

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
