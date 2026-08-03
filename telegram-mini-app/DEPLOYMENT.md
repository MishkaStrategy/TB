# Поэтапное размещение Telegram Mini App

Эта инструкция разворачивает frontend и API через один HTTPS origin. Она не регистрирует URL в BotFather, не добавляет кнопку в меню бота и не удаляет существующий Telegram UI.

## Целевая схема

```text
https://<subdomain>.duckdns.org/
├── /                 статический frontend
├── /api/mini-app/*   proxy → 127.0.0.1:8080
└── /healthz          proxy → 127.0.0.1:8080
```

Backend остаётся внутри процесса бота и слушает только loopback-интерфейс. Порт `8080` не должен быть открыт во внешнем firewall.

## Требования к VDS

- Ubuntu или Debian с `systemd`;
- открытые входящие TCP-порты `80` и `443`;
- поддомен DuckDNS, указывающий на публичный IPv4 VDS;
- Nginx;
- Certbot с Nginx plugin;
- Node.js `20.19+` или `22.12+`;
- npm, rsync и curl.

Системные пакеты, кроме Node.js:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx rsync curl
```

Скрипт намеренно не устанавливает Node.js автоматически, чтобы не заменять существующий runtime VDS непроверенным репозиторием пакетов.

## Этап 1 — DNS

В DuckDNS создайте hostname, например:

```text
tb-mini-app.duckdns.org
```

Укажите публичный IPv4 VDS и дождитесь разрешения имени:

```bash
getent ahostsv4 tb-mini-app.duckdns.org
```

DuckDNS token не требуется хранить в проекте при постоянном IP. Для динамического IP его следует хранить только на сервере в отдельном root-only файле.

## Этап 2 — frontend и HTTP reverse proxy

Из checkout нужной ветки проекта:

```bash
sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  bash scripts/deploy_mini_app.sh prepare
```

Команда:

1. проверяет домен, порт и версию Node.js;
2. собирает frontend во временной директории с `VITE_API_BASE_URL=https://<domain>`;
3. создаёт immutable release в `/var/www/tb-mini-app/releases/`;
4. атомарно переключает `/var/www/tb-mini-app/current`;
5. устанавливает отдельный Nginx site, если его ещё нет;
6. проверяет `nginx -t` и выполняет reload;
7. сохраняет несколько предыдущих frontend-релизов для rollback.

Скрипт не редактирует `/etc/fvg-alert-bot.env` и не перезапускает бота.

## Этап 3 — HTTPS

После того как DNS указывает на VDS:

```bash
sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  LETSENCRYPT_EMAIL=admin@example.com \
  bash scripts/deploy_mini_app.sh https
```

Certbot выпускает сертификат, включает redirect HTTP → HTTPS и оставляет автоматическое обновление сертификата штатному timer Certbot.

Проверка frontend:

```bash
curl -I https://tb-mini-app.duckdns.org/
```

На этом этапе URL всё ещё не регистрируется в BotFather.

## Этап 4 — включение backend

Добавьте в защищённый `/etc/fvg-alert-bot.env`:

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=8080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tb-mini-app.duckdns.org
```

После изменения env перезапустите штатную службу бота и проверьте локальный endpoint:

```bash
sudo systemctl restart fvg-alert-bot
curl http://127.0.0.1:8080/healthz
```

Порт `8080` не добавляется в UFW/security group.

## Этап 5 — сквозная проверка

```bash
MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  bash scripts/deploy_mini_app.sh verify
```

Проверяются:

- HTTPS frontend и наличие root-элемента приложения;
- HTTPS proxy `/healthz`;
- ответ backend со статусом `ok`.

Затем вручную проверяются заголовки:

```bash
curl -I https://tb-mini-app.duckdns.org/
curl -i https://tb-mini-app.duckdns.org/healthz
```

## Этап 6 — администраторский запуск

Только после успешной сквозной проверки:

1. зарегистрировать HTTPS URL в BotFather;
2. добавить временную кнопку открытия только для `ADMIN_TELEGRAM_IDS`;
3. протестировать Android, iOS и Telegram Desktop;
4. оставить старый Telegram UI рабочим;
5. не открывать Mini App всем пользователям до отдельного подтверждения.

## Повторное обновление frontend

Для нового frontend-релиза снова выполните `prepare` с тем же доменом. Существующая Certbot-конфигурация не перезаписывается, если Nginx site уже существует.

```bash
sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  bash scripts/deploy_mini_app.sh prepare
```

## Rollback frontend

Список релизов:

```bash
ls -1dt /var/www/tb-mini-app/releases/*
```

Переключение на предыдущий релиз:

```bash
sudo ln -sfn /var/www/tb-mini-app/releases/<release> /var/www/tb-mini-app/current.new
sudo mv -Tf /var/www/tb-mini-app/current.new /var/www/tb-mini-app/current
sudo nginx -t
sudo systemctl reload nginx
```

Rollback frontend не изменяет данные бота и настройки пользователей.
