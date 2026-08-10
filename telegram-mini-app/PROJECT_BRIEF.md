# Telegram Mini App — основной бриф проекта

## Цель

Telegram Mini App — дополнительный mobile-first интерфейс персональных и административных настроек TB. После интеграции в кодовую базу он не заменяет существующий Telegram UI: старые команды, кнопки и настройки остаются рабочим резервным путём.

## Архитектура

- Frontend: `telegram-mini-app/`.
- Backend: `mini_app_backend/`.
- Backend запускается внутри основного bot process, чтобы существующие JSON/SQLite stores не получили второго конкурирующего writer.
- API выключен по умолчанию (`MINI_APP_BACKEND_ENABLED=false`).
- Рекомендуемый listener: `127.0.0.1:18080`.
- Frontend production build по умолчанию использует same-origin `/api/...`.
- `VITE_API_BASE_URL` — только опциональный override.
- Mock включается только явно: `VITE_MOCK_MODE=true`.
- HTTPS hosting/tunnel, BotFather и пользовательская кнопка не активируются автоматически и являются отдельным deployment-этапом.
- Экспериментальный SNI-router, который мог затрагивать Amnezia/Xray на внешнем `443`, в интегрируемый код не входит.

## Совместимость с runtime 1.3.4

Mini App использует актуальный FVG schema v3:

- до 10 уникальных комбинаций `exchange + symbol`;
- Bitunix, Binance, Bybit, BingX, Bitget, Gate;
- таймфреймы `15m`, `1h`, `4h`, `1d`;
- market-data source — только закрытые `15m` свечи;
- `1h/4h/1d` строятся локально по UTC-границам;
- pre-FVG/T−3 удалён из API и frontend;
- legacy pre flags при сохранении принудительно нормализуются в `false`;
- stable instrument key позволяет независимо хранить одинаковый symbol на разных биржах;
- exchange, symbol и timeframes проходят полный backend round-trip без потери данных.

## Реализованные пользовательские разделы

### Главная и сводка

Показывают состояние FVG/funding, число инструментов и бирж, выбранные таймфреймы, формат сообщений, направления, порог и частоту.

### Общие настройки

- язык `ru` / `en`;
- message mode `compact` / `detailed`;
- сохранение через существующий `UserPreferences`;
- локализация интерфейса и динамических значений.

### FVG

- статус модуля;
- confirmed FVG;
- bullish/bearish;
- exchange + symbol instruments;
- `15m/1h/4h/1d` selection;
- pause/delete;
- backend limit;
- price filter min/max;
- size filter min + USD/PERCENT;
- confirmed/bullish/bearish filter scopes.

### Funding

- status;
- 15–2880 minute interval, step 15;
- threshold;
- positive/negative directions;
- six exchanges;
- crossing-state reset on significant changes.

## Администрирование

Server-side admin check обязателен на каждом административном запросе.

Реализованы:

- read-only FVG/funding/SQLite/outbox/process diagnostics;
- public/private access endpoint;
- runtime allowlist add/remove;
- env/admin deletion protection;
- short-lived one-time confirmation challenges bound to admin/action/target;
- replay, retarget, wrong phrase and expiry rejection;
- backup/restart adapters without shell fallback.

Backup/restart остаются fail-closed до подключения verified production callbacks.

## Безопасность

- Идентичность определяется только raw `Telegram.WebApp.initData` после HMAC-SHA-256 verification.
- Проверяются `auth_date`, срок действия и future skew.
- Telegram ID из JSON body не считается источником identity.
- Payload полностью валидируется до первой записи.
- Общий settings PUT не выполняет admin writes.
- Runtime/private access использует существующие project stores.
- Backend listener остаётся loopback-only.
- Секреты и production env не возвращаются frontend.
- CORS использует точный allowlist.

## API

```text
GET    /healthz
GET    /api/mini-app/settings
PUT    /api/mini-app/settings
POST   /api/mini-app/admin/confirmations
PUT    /api/mini-app/admin/access
POST   /api/mini-app/admin/allowlist
DELETE /api/mini-app/admin/allowlist/{telegram_id}
POST   /api/mini-app/admin/backup
POST   /api/mini-app/admin/restart
```

Авторизация personal/admin API:

```text
X-Telegram-Init-Data: <raw Telegram.WebApp.initData>
```

Полная модель: `telegram-mini-app/API_CONTRACT.md`.

## Lifecycle

`bot.py` сохраняет текущий 1.3.4 lifecycle и дополнительно:

1. после старта FVG stream/watchdog вызывает `start_mini_app_backend(application)`;
2. функция ничего не делает при `MINI_APP_BACKEND_ENABLED=false`;
3. при shutdown Mini App runner очищается через `stop_mini_app_backend(application)`;
4. существующие graceful shutdown/runtime lifecycle механизмы сохраняются.

## Frontend delivery model

GitHub Actions:

- Node.js 22;
- `npm ci`;
- typecheck;
- production build с `VITE_MOCK_MODE=false`;
- artifact `tb-mini-app-frontend`;
- manifest привязан к точному commit SHA и `apiMode: same-origin`.

Этот merge намеренно не фиксирует конкретный публичный hostname. Один и тот же frontend artifact можно опубликовать через выбранный постоянный HTTPS tunnel/hosting, который не требует изменения Amnezia/Xray или внешнего `443` VDS.

## Проверки

Обязательны:

- Python compileall;
- полный `unittest discover`;
- Mini App auth/service/runtime/web/admin tests;
- FVG 1.3.4 multi-exchange/timeframe regression tests;
- same symbol on multiple exchanges round-trip;
- legacy pre-FVG cannot be re-enabled;
- funding crossing-state tests;
- frontend TypeScript typecheck/build;
- dependency audit;
- bounded pipeline smoke;
- systemd verification;
- release audit.

## Что входит в интеграцию кода

- frontend и backend исходники;
- lifecycle hook, выключенный по умолчанию;
- API/auth/admin/diagnostics;
- актуальный FVG 1.3.4 contract;
- CI frontend artifact build;
- тесты и документация.

## Что НЕ входит в интеграцию кода

- изменение production VDS;
- изменение Amnezia/Xray;
- разделение внешнего `443`;
- DuckDNS deployment wrapper;
- включение backend production env;
- BotFather registration;
- добавление Mini App button пользователям;
- удаление старого Telegram UI.

## Следующие этапы после merge

1. Выбрать постоянный HTTPS tunnel/hosting без вмешательства в VPN.
2. Опубликовать verified frontend artifact и same-origin `/api` proxy/tunnel.
3. Включить backend на `127.0.0.1:18080` с точным allowed origin и проверить `/healthz`.
4. Зарегистрировать проверенный URL в BotFather.
5. Провести ограниченный Telegram end-to-end test и проверить round-trip настроек.
6. Расширять доступ только после успешного параллельного тестирования со старым Telegram UI.
