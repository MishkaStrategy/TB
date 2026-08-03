# Поэтапное размещение Telegram Mini App

Эта инструкция разворачивает frontend и API через один HTTPS origin. Она не регистрирует URL в BotFather, не добавляет кнопку в меню бота и не удаляет существующий Telegram UI.

## Целевая схема

```text
https://<subdomain>.duckdns.org/
├── /                 статический frontend
├── /api/mini-app/*   proxy → 127.0.0.1:18080
└── /healthz          proxy → 127.0.0.1:18080
```

Backend остаётся внутри процесса бота и слушает только loopback-интерфейс. Порт `18080` не должен быть открыт во внешнем firewall.

## Требования к VDS

- Ubuntu или Debian с `systemd`;
- открытые входящие TCP-порты `80` и `443`;
- поддомен DuckDNS, указывающий на публичный IPv4 VDS;
- Nginx;
- Certbot с Nginx plugin;
- Python 3, rsync и curl;
- проверенный frontend artifact из GitHub Actions.

Системные пакеты, кроме Node.js:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx rsync curl
```

Node.js 22 используется только в GitHub Actions: `npm ci`, typecheck и Vite build
создают artifact `tb-mini-app-frontend`. Production VDS не собирает frontend и
не требует Node.js/npm.

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
  MINI_APP_ARTIFACT=/root/tb-mini-app-artifacts/<commit>/tb-mini-app-frontend \
  MINI_APP_EXPECTED_COMMIT=<full-commit-sha> \
  bash scripts/deploy_mini_app.sh prepare-artifact
```

Команда:

1. проверяет домен, порт и полный commit SHA;
2. безопасно извлекает artifact и проверяет `index.html` и `manifest.json`;
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
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tb-mini-app.duckdns.org
```

После изменения env перезапустите штатную службу бота и проверьте локальный endpoint:

```bash
sudo systemctl restart fvg-alert-bot
curl http://127.0.0.1:18080/healthz
```

Порт `18080` не добавляется в UFW/security group.

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

Для нового frontend-релиза снова выполните `prepare-artifact` с тем же доменом. Существующая Certbot-конфигурация не перезаписывается, если Nginx site уже существует.

```bash
sudo MINI_APP_DOMAIN=tb-mini-app.duckdns.org \
  MINI_APP_ARTIFACT=/root/tb-mini-app-artifacts/<commit>/tb-mini-app-frontend \
  MINI_APP_EXPECTED_COMMIT=<full-commit-sha> \
  bash scripts/deploy_mini_app.sh prepare-artifact
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
