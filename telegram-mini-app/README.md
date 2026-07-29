# TB Telegram Mini App

Отдельный frontend-модуль и защищённый backend для персональных и административных настроек Telegram-бота TB.

## Граница текущего этапа

Mini App развивается параллельно существующему Telegram-интерфейсу:

- текущие команды, кнопки и формы настроек в боте не удаляются;
- Mini App пока не добавляется в боевое меню;
- используются существующие JSON/SQLite-хранилища;
- backend API выключен по умолчанию;
- backup, restart и изменение allowlist остаются заблокированными;
- без `VITE_API_BASE_URL` frontend работает на mock-данных.

Интеграция и очистка старых элементов бота выполняются только после полного тестирования и отдельного решения о выпуске.

## Реализовано

### Общие настройки

- русский или английский язык бота;
- компактный или подробный формат уведомлений.

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

Реализованы:

- публичный и приватный режим доступа;
- read-only allowlist;
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

При пустом `VITE_API_BASE_URL` используется mock-режим.

Проверка:

```bash
npm run typecheck
npm run build
```

## Backend API

Реализованы:

```text
GET /healthz
GET /api/mini-app/settings
PUT /api/mini-app/settings
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
6. повторно проверяет административные права;
7. ограничивает размер тела запроса;
8. использует точный CORS allowlist;
9. возвращает структурированные ошибки;
10. не создаёт второй источник пользовательских настроек.

Полная схема: [`API_CONTRACT.md`](API_CONTRACT.md).

## Включение backend

API запускается в процессе бота только при явном флаге. Это исключает второго конкурирующего писателя для JSON-хранилищ.

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=8080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=http://localhost:5173
```

Проверка после запуска:

```bash
curl http://127.0.0.1:8080/healthz
```

Production endpoint должен публиковаться через HTTPS reverse proxy. aiohttp listener рекомендуется оставлять на `127.0.0.1`.

## Тесты

```bash
python -m unittest -v \
  tests.test_mini_app_auth \
  tests.test_mini_app_service \
  tests.test_mini_app_runtime_service \
  tests.test_mini_app_diagnostics \
  tests.test_mini_app_web
```

Все тесты входят в общий запуск:

```bash
python -m unittest discover -s tests -v
```

CI дополнительно выполняет frontend typecheck/build, dependency audit, compileall, bounded soak, funding storage verification, Linux systemd verification и release audit.

## Оставшиеся этапы

1. Полная RU/EN-локализация самого Mini App.
2. Отдельные подтверждаемые admin endpoints для backup, restart и allowlist.
3. HTTPS-размещение frontend и API.
4. Регистрация URL в BotFather.
5. Тестовая кнопка открытия только для администратора.
6. Параллельное тестирование со старым Telegram UI.
7. После полного принятия — переключение настроек на Mini App и удаление только подтверждённо лишних элементов бота.
