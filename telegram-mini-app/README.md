# TB Telegram Mini App

Отдельный frontend-модуль и защищённый backend для персональных и административных настроек Telegram-бота TB.

## Граница текущего этапа

Mini App развивается параллельно существующему Telegram-интерфейсу:

- текущие команды, кнопки и формы настроек в боте не удаляются;
- Mini App пока не добавляется в боевое меню;
- используются существующие JSON/SQLite-хранилища;
- backend API выключен по умолчанию;
- без `VITE_API_BASE_URL` frontend работает на mock-данных;
- access mode и runtime allowlist доступны только через подтверждаемые admin endpoints;
- backup и restart остаются fail-closed, пока не подключены production callbacks;
- HTTPS deploy подготовлен отдельными файлами и не изменяет штатный `install_vds.sh`.

Интеграция и очистка старых элементов бота выполняются только после полного тестирования и отдельного решения о выпуске.

## Реализовано

### Общие настройки

- русский или английский язык бота и Mini App;
- компактный или подробный формат уведомлений.

### RU/EN-локализация

- интерфейс переключается мгновенно без перезагрузки и без дублирования экранов;
- сохранённый язык загружается из production backend или mock-настроек;
- переводятся все основные разделы, карточки, навигация, кнопки, подсказки и placeholders;
- локализуются динамические значения: интервалы, даты, размеры хранилищ, статусы и счётчики;
- известные backend-ошибки показываются на выбранном языке;
- атрибут `lang` документа синхронизируется с выбранным языком;
- переключение языка остаётся несохранённым изменением до нажатия кнопки сохранения.

### Сводка уведомлений

- общий формат сообщений;
- состояние FVG;
- типы FVG-сигналов и направления;
- состояние funding alerts;
- частота, порог, направления и выбранные биржи;
- быстрые переходы к соответствующим настройкам.

### FVG

- включение всего модуля;
- подтверждённые FVG;
- предварительные FVG T−3;
- бычьи и медвежьи направления;
- добавление, удаление и отключение инструментов;
- backend-лимит количества инструментов;
- ценовой диапазон для каждого инструмента;
- минимальный размер FVG в USD или процентах;
- отдельный scope фильтров: T−3, подтверждённые, бычьи и медвежьи.

### Funding alerts

- включение рассылки;
- частота 15–2880 минут с шагом 15 минут;
- минимальный абсолютный процент;
- положительное, отрицательное или оба направления;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- защита от отключения всех направлений или всех бирж;
- очистка мультибиржевого crossing-state при значимых изменениях.

### Администрирование

Раздел доступен только после серверной проверки `is_admin`.

Read-only диагностика:

- статус WebSocket;
- последняя свеча и REST recovery;
- последняя операционная ошибка;
- outbox, успешные доставки, ошибки, retries и permanent failures;
- `PRAGMA quick_check` и размеры FVG/Funding SQLite;
- общий размер JSON-настроек;
- память процесса;
- load average 1/5/15;
- свободное и общее место на диске;
- PID;
- VERSION, BUILD_COMMIT и версия Python.

Подтверждаемые записи:

- переключение публичного/приватного режима;
- добавление runtime-записи allowlist;
- удаление runtime-записи allowlist;
- защита env-allowlist и администраторов от удаления;
- отдельные capabilities для access, allowlist, backup и restart.

Каждая административная запись использует короткоживущий одноразовый challenge, привязанный к проверенному Telegram ID администратора, точному действию и цели. Повторное использование, изменение цели и просроченный challenge отклоняются.

Backup и restart endpoints реализованы как безопасные адаптеры. Они не выполняют shell-команды или `systemctl` самостоятельно и остаются выключенными, пока lifecycle не передаст проверенные production callbacks.

Недоступные показатели не ломают endpoint: backend возвращает стабильную схему с безопасными значениями `unknown`, `null` и `0`.

## Стек

Frontend:

- React 19;
- TypeScript;
- Vite;
- Telegram WebApp API без внешней UI-библиотеки.

Backend:

- Python 3.12;
- aiohttp;
- существующие `UserPreferences`, `FvgAlertSettings`, `FundingAlertStore`, `FundingExchangeStore`, `RuntimeSettings`, `AccessRegistry` и `UserActivityRegistry`.

## Локальный запуск frontend

```bash
cd telegram-mini-app
cp .env.example .env
npm install
npm run dev
```

При пустом `VITE_API_BASE_URL` используется mock-режим. В mock-режиме административные записи намеренно недоступны.

Проверка:

```bash
npm run typecheck
npm run build
```

## Backend API

Реализованы:

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

Telegram `initData` передаётся в заголовке:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend:

1. проверяет HMAC-SHA-256 подпись;
2. отклоняет просроченный и будущий `auth_date`;
3. извлекает Telegram ID только из проверенного `initData`;
4. повторяет правила публичного/приватного доступа бота;
5. валидирует полный payload до первой записи;
6. повторно проверяет административные права на каждом admin-запросе;
7. требует одноразовое подтверждение для каждой admin-записи;
8. ограничивает размер тела запроса;
9. использует точный CORS allowlist;
10. возвращает структурированные ошибки;
11. не создаёт второй источник пользовательских настроек.

Полная схема: [`API_CONTRACT.md`](API_CONTRACT.md).

## Включение backend

API запускается в процессе бота только при явном флаге. Это исключает второго конкурирующего писателя для JSON-хранилищ.

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=8080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tb-mini-app.duckdns.org
```

Проверка после запуска:

```bash
curl http://127.0.0.1:8080/healthz
```

Production endpoint публикуется через HTTPS reverse proxy. aiohttp listener должен оставаться на `127.0.0.1`.

## Поэтапный HTTPS deploy

Подготовлены:

- `scripts/deploy_mini_app.sh` — команды `prepare`, `https` и `verify`;
- `deploy/mini-app/nginx-site.conf.template` — отдельный Nginx site;
- атомарные frontend-релизы в `/var/www/tb-mini-app/releases/`;
- rollback через symlink `/var/www/tb-mini-app/current`;
- Let’s Encrypt через Certbot;
- proxy только на локальный backend;
- SPA routing, безопасное кэширование и security headers.

Базовый запуск для DuckDNS:

```bash
sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  bash scripts/deploy_mini_app.sh prepare

sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  LETSENCRYPT_EMAIL=admin@example.com \
  bash scripts/deploy_mini_app.sh https
```

Скрипт не редактирует env бота, не перезапускает службу бота, не обращается к BotFather и не добавляет кнопку в меню.

Полная инструкция: [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Тесты

```bash
python -m unittest -v \
  tests.test_mini_app_auth \
  tests.test_mini_app_service \
  tests.test_mini_app_runtime_service \
  tests.test_mini_app_diagnostics \
  tests.test_mini_app_web \
  tests.test_mini_app_admin_actions \
  tests.test_mini_app_admin_web \
  tests.test_mini_app_deployment
```

Все тесты входят в общий запуск:

```bash
python -m unittest discover -s tests -v
```

CI дополнительно выполняет frontend typecheck/build, dependency audit, compileall, bounded soak, funding storage verification, Linux systemd verification и release audit.

## Оставшиеся этапы

1. Выполнить подготовленный DuckDNS/HTTPS deploy на VDS.
2. Включить backend в production env и пройти сквозной health-check.
3. Подключить backup callback после принятия production backup-ветки.
4. Подключить restart callback после принятия graceful restart/restart-guard веток.
5. Зарегистрировать проверенный HTTPS URL в BotFather.
6. Добавить тестовую кнопку открытия только для администратора.
7. Провести параллельное тестирование со старым Telegram UI.
8. После полного принятия — переключить настройки на Mini App и удалить только подтверждённо лишние элементы бота.
