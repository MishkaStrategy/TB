# TB Telegram Mini App

TB Telegram Mini App — mobile-first trading control center внутри Telegram. Он работает поверх существующих TB stores/runtime и не заменяет резервный Telegram UI бота.

## UI / UX

Текущий интерфейс использует собственную тёмную trading design system TB, а не копирует Telegram UI:

- почти чёрный фон `#070b12` / `#09101a`;
- компактные surfaces `#101722` / `#121b28`;
- primary blue `#2F9BFF`, cyan `#32D5FF`;
- bullish `#26D99A`, bearish `#FF5D6C`;
- тонкие borders, минимальные shadows, без декоративного glow;
- единый лёгкий SVG icon set;
- mobile-first layout 360–430 px, safe-area и fixed 5-tab navigation;
- desktop/tablet layout ограничен примерно 960 px и использует дополнительные columns там, где это полезно;
- `prefers-reduced-motion` отключает необязательные transitions/animations.

Основная навигация:

1. Главная
2. FVG
3. Funding
4. Уведомления
5. Настройки

Admin остаётся secondary destination и показывается только при server-provided `admin.available`.

## Главная

Overview — trading dashboard, а не settings page. Он показывает:

- статус FVG, активные инструменты и число выбранных timeframe;
- статус Funding, число бирж, threshold и interval;
- список сохранённых FVG-инструментов;
- exchange + symbol + timeframes;
- active/paused и число активных per-instrument filters;
- реальный exchange-aware `24h price change %`, когда market data доступны;
- `—`, если конкретный market snapshot временно недоступен.

Нажатие на market row открывает редактор конкретного FVG-инструмента.

## FVG

Mini App использует тот же FVG v3 contract, что и основной runtime:

- до 10 уникальных комбинаций `exchange + symbol` на Telegram ID;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- таймфреймы `15m`, `1h`, `4h`, `1d`, минимум один;
- одинаковый symbol на разных биржах хранится независимо;
- stable instrument key сохраняется server-side;
- global FVG enable, confirmed FVG, bullish и bearish;
- per-instrument enable;
- price filter и FVG size filter со scope;
- pre-FVG/T−3 не экспонируется и не может быть повторно включён legacy payload.

Исходные FVG market data runtime остаются прежними: закрытые `15m` свечи; `1h/4h/1d` агрегируются локально.

## Funding alerts

Funding screen сохраняет текущую существующую семантику:

- enable/disable;
- интервал 15–2880 минут с шагом 15;
- абсолютный percentage threshold;
- Positive / Negative, минимум одно направление;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate, минимум одна биржа;
- `nextCheckAt` read-only;
- crossing-state очищается backend при значимых изменениях.

## Уведомления и общие настройки

Alerts screen — read-only operational summary текущих правил FVG/Funding с быстрым переходом в соответствующий editor.

Settings содержит только общие параметры и профиль:

- RU / EN;
- compact / detailed;
- Telegram user / ID;
- admin badge и переход в Administration только при наличии server-side capability.

## 24h market overview

Volatile market state отделён от mutable settings:

```text
GET /api/mini-app/market-overview
```

Backend не принимает произвольные `exchange`/`symbol` из клиента. После Telegram auth/access check он строит snapshot только по уже сохранённым FVG-инструментам пользователя.

Поле называется однозначно:

```json
{
  "key": "binance|BTCUSDT",
  "exchange": "binance",
  "symbol": "BTCUSDT",
  "price": null,
  "priceChange24hPct": 1.42,
  "source": "ticker"
}
```

Источники переиспользуют существующие public market adapters TB, API keys не нужны:

- Bitunix 24h ticker;
- Binance futures 24h ticker;
- Bybit linear ticker;
- Bitget futures ticker;
- Gate futures ticker;
- для exchange adapter без готового 24h field (сейчас BingX) — fallback по закрытым `15m` свечам, сравнение цены сейчас и 24 часа назад.

Robustness:

- существующие HTTP adapters имеют bounded request timeout;
- exchange loads выполняются через bounded thread pool вне aiohttp event loop;
- одна упавшая биржа не ломает остальные market rows;
- бесконечных retry нет;
- результат кешируется на короткий TTL (по умолчанию 30 секунд) с bounded cache size;
- unavailable value возвращается `null`, frontend показывает `—`, а не `0%`;
- market endpoint является вторичным read-only API и не влияет на settings writes/runtime alerts.

Полный формат: [`API_CONTRACT.md`](API_CONTRACT.md).

## Telegram integration

Сохранены:

- raw `Telegram.WebApp.initData` для server auth;
- `ready()` и `expand()`;
- Telegram viewport;
- safe-area через CSS env variables;
- haptic feedback;
- closing confirmation при unsaved changes;
- дополнительный browser `beforeunload` guard;
- Telegram user context для отображения;
- RU/EN.

TB намеренно удерживает собственный dark trading surface независимо от Telegram light/dark theme; Telegram header/background синхронизируются с `#070b12`.

## Admin

Administrative UI использует ту же design system и сохраняет существующую security model:

- runtime;
- WebSocket / REST state;
- SQLite;
- outbox/delivery counters;
- resources;
- access mode;
- allowlist;
- backup;
- restart.

Все writes идут через отдельные admin endpoints и одноразовые confirmation challenges. Frontend `admin.available` — только presentation gate; окончательная авторизация всегда server-side.

Backup/restart остаются fail-closed, если production callbacks не подключены. Shell/systemctl fallback в Mini App отсутствует.

## Архитектура

- frontend: `telegram-mini-app/` — React 19 + TypeScript + Vite;
- backend: `mini_app_backend/` — aiohttp внутри процесса бота;
- existing stores/adapters переиспользуются, второй market stack не создаётся;
- backend по умолчанию выключен: `MINI_APP_BACKEND_ENABLED=false`;
- рекомендуемый listener: `127.0.0.1:18080`;
- production frontend по умолчанию использует same-origin `/api/...`;
- `VITE_API_BASE_URL` нужен только для явного override;
- mock включается только явно через `VITE_MOCK_MODE=true`.

Frontend декомпозирован на `TradingApp.tsx`, `ui.tsx`, `screens/*`, API clients и design stylesheet. Legacy `App.tsx` и старые styles пока могут оставаться в repository history/source для безопасной миграции, но production entrypoint их не монтирует.

## Backend API

```text
GET    /healthz
GET    /api/mini-app/settings
PUT    /api/mini-app/settings
GET    /api/mini-app/market-overview
POST   /api/mini-app/admin/confirmations
PUT    /api/mini-app/admin/access
POST   /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
POST   /api/mini-app/admin/backup
POST   /api/mini-app/admin/restart
```

Frontend передаёт:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend проверяет HMAC-SHA-256, `auth_date`, срок действия и получает Telegram ID только из verified initData.

## Backend activation

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://<public-mini-app-host>
```

Production env/restart/deployment остаются отдельным контролируемым этапом.

## Frontend build

Mock development:

```bash
cd telegram-mini-app
cp .env.example .env
npm ci
npm run dev
```

Production verification:

```bash
cd telegram-mini-app
npm ci --no-audit --no-fund
npm run typecheck
VITE_MOCK_MODE=false npm run build
```

## Backend / regression tests

```bash
PUBLIC_ACCESS_ENABLED=true python -m unittest discover -s tests -v
```

Mini App-specific coverage включает settings/auth regressions, market overview exchange-awareness/cache/partial failure/null handling, market endpoint auth, navigation/design contracts и existing admin/runtime regressions.

## Deployment boundary

Код Mini App не меняет BotFather/menu button, внешний `443`, Amnezia/Xray или production reverse proxy автоматически. Публикация HTTPS URL и включение backend выполняются отдельным deployment workflow после merge/release и smoke-check.
