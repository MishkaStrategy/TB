# TB Telegram Mini App

Telegram Mini App — дополнительный мобильный интерфейс настроек TB, интегрированный с runtime 1.3.4. Существующий Telegram UI остаётся рабочим резервным путём и не удаляется.

## Текущее состояние

- frontend: `telegram-mini-app/` (React 19, TypeScript, Vite);
- backend: `mini_app_backend/` (aiohttp, запускается внутри процесса бота);
- backend выключен по умолчанию: `MINI_APP_BACKEND_ENABLED=false`;
- backend должен слушать только loopback, рекомендуемый порт `127.0.0.1:18080`;
- production frontend по умолчанию использует same-origin API (`/api/...`);
- `VITE_API_BASE_URL` нужен только для явного API override;
- mock включается только явно через `VITE_MOCK_MODE=true`;
- Mini App не подключается к BotFather и меню автоматически;
- код не содержит production-схемы, которая делит внешний `443` с Amnezia/Xray;
- HTTPS-публикация через внешний туннель/хостинг выполняется отдельным этапом после выбора сервиса.

## FVG 1.3.4

Mini App использует тот же контракт, что и текущий Telegram runtime:

- до 10 уникальных комбинаций `exchange + symbol` на Telegram ID;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- таймфреймы `15m`, `1h`, `4h`, `1d`;
- исходные рыночные данные — только закрытые `15m` свечи;
- `1h/4h/1d` агрегируются локально по UTC-границам;
- пред-FVG/T−3 не используется и не может быть повторно включён через Mini App;
- стабильный instrument key сохраняет одинаковый символ на разных биржах независимо;
- биржа, символ и выбранные таймфреймы проходят полный server-side round-trip;
- фильтры цены и размера сохраняются exchange-aware.

## Funding alerts

Поддерживаются:

- интервал 15–2880 минут с шагом 15;
- абсолютный процентный порог;
- положительное, отрицательное или оба направления;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- минимум одно направление и одна биржа;
- очистка crossing-state при значимых изменениях.

## Общие настройки

- язык `ru` / `en`;
- формат сообщений `compact` / `detailed`;
- защита несохранённых изменений;
- Telegram theme/safe-area/viewport/haptics;
- RU/EN-локализация frontend.

## Администрирование

Административный раздел доступен только после server-side проверки `is_admin`.

Реализованы:

- read-only runtime/SQLite/outbox/resource diagnostics;
- access mode и runtime allowlist через отдельные endpoints;
- одноразовые короткоживущие confirmation challenges, привязанные к admin/action/target;
- replay/retarget/expired challenge rejection;
- защита env allowlist и администраторов от удаления;
- backup/restart adapters fail-closed до подключения проверенных production callbacks.

Общий `PUT /api/mini-app/settings` не выполняет административные записи.

## Backend API

Основные endpoints:

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

Frontend передаёт raw Telegram init data:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend проверяет HMAC-SHA-256, `auth_date`, срок действия, извлекает Telegram ID только из проверенного initData и повторно валидирует payload до записи.

Полный формат: [`API_CONTRACT.md`](API_CONTRACT.md).

## Backend activation

API запускается в процессе существующего бота только при явном флаге:

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://<public-mini-app-host>
```

После изменения production env требуется отдельный контролируемый restart и health-check. Эта операция не выполняется автоматически кодом Mini App.

## Frontend build

Локальный mock:

```bash
cd telegram-mini-app
cp .env.example .env
npm ci
npm run dev
```

Production build:

```bash
cd telegram-mini-app
VITE_MOCK_MODE=false npm ci --no-audit --no-fund
VITE_MOCK_MODE=false npm run typecheck
VITE_MOCK_MODE=false npm run build
```

Если `VITE_API_BASE_URL` пуст, production frontend обращается к `/api/...` на том же HTTPS-origin. Это позволяет публиковать один и тот же build через выбранный HTTPS-туннель или reverse proxy без привязки к DuckDNS.

GitHub Actions выполняет Node.js 22 typecheck/build и сохраняет artifact `tb-mini-app-frontend` с manifest, содержащим commit SHA и `apiMode: same-origin`.

## Тесты

```bash
PUBLIC_ACCESS_ENABLED=true python -m unittest discover -s tests -v

cd telegram-mini-app
npm ci --no-audit --no-fund
npm run typecheck
VITE_MOCK_MODE=false npm run build
```

CI дополнительно выполняет dependency audit, compileall, FVG/funding regression tests, bounded pipeline smoke, systemd verification и release audit.

## Следующий deployment-этап

Интеграция кода и deployment разделены намеренно. Для публикации нужно отдельно:

1. выбрать постоянный HTTPS-туннель/хостинг, не изменяющий Amnezia/Xray и внешний `443` VDS;
2. направить публичный HTTPS origin на frontend и `/api` → `127.0.0.1:18080`;
3. включить backend env и пройти `/healthz`;
4. зарегистрировать проверенный HTTPS URL в BotFather;
5. сначала открыть Mini App ограниченному тестовому кругу и проверить round-trip настроек;
6. только после этого решать вопрос о расширении доступа.

Старый Telegram UI остаётся совместимым и рабочим во всех этих этапах.
