# TB Telegram Mini App

Отдельный frontend-модуль для персональных и административных настроек Telegram-бота TB.

## Граница текущего этапа

Mini App развивается параллельно с существующим Telegram-интерфейсом:

- текущие команды, кнопки и формы настроек в боте не удаляются;
- Mini App пока не добавляется в меню бота;
- используются существующие JSON/SQLite-хранилища;
- опасные административные действия backup/restart остаются заблокированными;
- backend API выключен по умолчанию и запускается только через переменную окружения;
- без `VITE_API_BASE_URL` frontend работает на локальных mock-данных.

Интеграция и очистка старых графических элементов бота выполняются только после завершения и отдельного решения о выпуске Mini App.

## Реализованные разделы

### Главная

- состояние FVG и funding alerts;
- количество инструментов и бирж;
- текущая частота;
- быстрые переключатели;
- индикатор несохранённых изменений.

### Общие настройки

- русский или английский язык как пользовательская настройка;
- компактный или подробный формат уведомлений.

### Сводка уведомлений

- общий формат сообщений;
- статус и типы FVG-сигналов;
- направления FVG;
- количество ценовых и размерных фильтров;
- статус, частота и порог funding alerts;
- направления и выбранные биржи;
- быстрые переходы к соответствующим настройкам.

### FVG

- включение всего модуля;
- подтверждённые FVG;
- предварительные FVG T−3;
- бычьи и медвежьи направления;
- добавление и удаление инструментов;
- лимит инструментов, получаемый от backend;
- включение отдельного инструмента;
- ценовой диапазон для каждого инструмента;
- минимальный размер FVG;
- единицы размера: USD или проценты;
- область применения каждого фильтра: T−3, подтверждённые, бычьи и медвежьи сигналы.

### Funding alerts

- включение рассылки;
- частота от 15 до 2880 минут с шагом 15 минут;
- минимальный абсолютный процент;
- положительный и отрицательный фандинг;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- защита от отключения всех направлений или всех бирж;
- очистка мультибиржевого crossing-state при изменениях, влияющих на срабатывания.

### Администрирование

- раздел показывается только подтверждённому администратору;
- публичный или приватный режим;
- представление allowlist;
- WebSocket, outbox, ошибки доставки, базы и версия;
- подготовленные, но заблокированные действия backup и restart.

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

Интерфейс адаптирован под Telegram WebView, safe-area, светлую/тёмную системную тему Telegram и haptic feedback.

## Локальный запуск frontend

```bash
cd telegram-mini-app
cp .env.example .env
npm install
npm run dev
```

Открыть `http://localhost:5173`. При пустом `VITE_API_BASE_URL` используется mock-режим.

Проверка:

```bash
npm run typecheck
npm run build
```

Эти команды также выполняются отдельным job в GitHub Actions.

## Backend API

Реализованы endpoint:

```text
GET /healthz
GET /api/mini-app/settings
PUT /api/mini-app/settings
```

Telegram `initData` отправляется в заголовке:

```text
X-Telegram-Init-Data: <window.Telegram.WebApp.initData>
```

Backend:

1. проверяет HMAC-SHA-256 подпись `initData` токеном бота;
2. отклоняет просроченный и будущий `auth_date`;
3. получает Telegram ID только из проверенного `initData`;
4. повторяет правила публичного/приватного доступа бота;
5. загружает данные из текущих хранилищ;
6. валидирует полный payload до первой записи;
7. не принимает Telegram ID из JSON-body;
8. повторно проверяет административные права;
9. ограничивает размер тела запроса;
10. возвращает структурированные ошибки с кодом и путём поля.

Полное отображение полей описано в [`API_CONTRACT.md`](API_CONTRACT.md).

Постоянные требования и критерии завершения находятся в [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md).

## Включение backend в процессе бота

API размещается в том же процессе, что и бот. Это исключает второго конкурирующего писателя для JSON-хранилищ.

В `.env`:

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=8080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=http://localhost:5173
```

После перезапуска:

```bash
curl http://127.0.0.1:8080/healthz
```

Для production endpoint должен быть опубликован через HTTPS reverse proxy. Сам aiohttp listener рекомендуется оставлять на `127.0.0.1`.

`MINI_APP_ALLOWED_ORIGINS` требуется только при размещении frontend и API на разных origins. Значения перечисляются через запятую и должны совпадать полностью.

## Тесты backend

```bash
python -m unittest -v \
  tests.test_mini_app_auth \
  tests.test_mini_app_service \
  tests.test_mini_app_runtime_service \
  tests.test_mini_app_web
```

Также все тесты автоматически входят в общий запуск:

```bash
python -m unittest discover -s tests -v
```

CI дополнительно выполняет:

- compileall всего Python-кода;
- аудит Python-зависимостей;
- bounded pipeline soak;
- funding storage verification;
- frontend typecheck;
- production frontend build;
- Linux systemd verification;
- release audit.

## Оставшиеся этапы

1. Добавить полноценную локализацию всего интерфейса Mini App на русский и английский.
2. Расширить read-only административную диагностику до полного набора текущей панели.
3. Реализовать отдельные подтверждаемые admin endpoint для backup, restart и allowlist.
4. Разместить frontend и API за HTTPS.
5. Зарегистрировать URL в BotFather.
6. Добавить тестовую кнопку открытия только для администратора.
7. Провести параллельный тест с текущим Telegram UI.
8. После полного принятия переключить настройки на Mini App и удалить только ставшие лишними элементы бота.
