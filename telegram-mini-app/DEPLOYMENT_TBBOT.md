# Production-профиль `tbbot.duckdns.org`

Этот документ фиксирует утверждённую цель первого тестового размещения Telegram Mini App:

```text
Домен:       tbbot.duckdns.org
Публичный IP: 188.137.236.73
Backend:     127.0.0.1:18080
```

Профиль не содержит секретов. DuckDNS token, Telegram token и email для Let's Encrypt не должны добавляться в GitHub.

## Ограничения этапа

На этом этапе:

- frontend и API размещаются через HTTPS;
- Mini App не регистрируется в BotFather;
- кнопка не добавляется пользователям;
- существующее меню и настройки бота не изменяются;
- backend port `18080` не открывается наружу;
- backup/restart callbacks остаются выключенными до принятия соответствующих operational веток.

## 1. Подготовка VDS

На VDS должны быть открыты входящие TCP-порты `80` и `443`.

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx rsync curl unzip
```

Production frontend собирается только в GitHub Actions на Node.js 22. На VDS
Node.js и npm не требуются и не обновляются. Проверка серверных инструментов:

```bash
nginx -v
certbot --version
```

## 2. DNS preflight

Из checkout ветки `agent/telegram-mini-app-foundation`:

```bash
bash scripts/deploy_tbbot_mini_app.sh preflight
```

Команда должна вывести:

```text
DNS preflight пройден: tbbot.duckdns.org → 188.137.236.73
```

Если DuckDNS возвращает другой IP или имя ещё не резолвится, дальнейшее HTTPS-развёртывание автоматически останавливается.

## 3. Frontend и HTTP reverse proxy

```bash
sudo MINI_APP_ARTIFACT=/root/tb-mini-app-artifacts/<commit>/tb-mini-app-frontend \
  MINI_APP_EXPECTED_COMMIT=<full-commit-sha> \
  bash scripts/deploy_tbbot_mini_app.sh prepare-artifact
```

Команда:

1. повторно проверяет DNS;
2. безопасно проверяет готовый CI artifact, manifest, commit, domain и API URL;
3. создаёт атомарный релиз в `/var/www/tb-mini-app/releases/`;
4. переключает `/var/www/tb-mini-app/current`;
5. устанавливает отдельный Nginx site;
6. проксирует `/api/` и `/healthz` на `127.0.0.1:18080`;
7. выполняет `nginx -t` и reload.

Скрипт не изменяет `/etc/fvg-alert-bot.env` и не перезапускает бота.

## 4. Выпуск HTTPS-сертификата

Email нужно передать только в командной строке на VDS:

```bash
sudo LETSENCRYPT_EMAIL=<ваш-email> \
  bash scripts/deploy_tbbot_mini_app.sh https
```

Перед Certbot снова выполняется строгая проверка:

```text
tbbot.duckdns.org → 188.137.236.73
```

После успеха:

```bash
curl -I https://tbbot.duckdns.org/
```

На этом этапе frontend уже доступен по HTTPS, но API ещё может возвращать `502`, пока backend выключен.

## 5. Включение backend

Добавить в `/etc/fvg-alert-bot.env`:

```env
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tbbot.duckdns.org
```

После отдельной проверки env:

```bash
sudo systemctl restart fvg-alert-bot
sudo systemctl --no-pager --full status fvg-alert-bot
curl http://127.0.0.1:18080/healthz
```

Ожидается JSON со статусом `ok`.

Порт `18080` не добавлять в UFW или security group.

## 6. Сквозная проверка

```bash
bash scripts/deploy_tbbot_mini_app.sh verify
```

Проверяются:

- DNS указывает на утверждённый IP;
- HTTPS frontend содержит root-элемент Mini App;
- `/healthz` доступен через Nginx;
- backend возвращает `status=ok`.

Дополнительно:

```bash
curl -I https://tbbot.duckdns.org/
curl -i https://tbbot.duckdns.org/healthz
sudo ss -lntp | grep -E ':(80|443|18080)\b'
```

Ожидаемая сетевая схема:

```text
0.0.0.0:80/443       Nginx
127.0.0.1:18080       Python backend
```

Не должно быть:

```text
0.0.0.0:18080
```

## 7. Следующий этап

Только после успешного `verify`:

1. зарегистрировать `https://tbbot.duckdns.org` в BotFather;
2. добавить временную кнопку открытия только для `ADMIN_TELEGRAM_IDS`;
3. протестировать Android, iOS и Telegram Desktop;
4. оставить старый Telegram UI полностью рабочим;
5. не открывать Mini App всем пользователям без отдельного подтверждения.
