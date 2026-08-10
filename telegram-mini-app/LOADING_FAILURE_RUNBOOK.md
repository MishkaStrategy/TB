# Telegram Mini App loading failure runbook

Use this runbook when the frontend renders but remains on `Загружаем настройки`.

## What this state means

The static frontend has loaded and React has mounted, but the initial `GET /api/mini-app/settings` has not completed. The request must never be allowed to wait forever; the frontend aborts it after 10 seconds and surfaces a visible error.

## Production checks

Run these checks on the VDS without printing Telegram tokens or other secrets.

```bash
sudo systemctl is-active fvg-alert-bot
sudo systemctl show fvg-alert-bot -p NRestarts -p ExecMainStatus
sudo ss -ltnp | grep -F '127.0.0.1:18080' || true
curl -fsS --max-time 5 http://127.0.0.1:18080/healthz
```

Expected local health response is HTTP 200 from the Telegram Mini App backend. If the listener is missing, verify only the Mini App environment keys by name/value where non-secret:

```bash
sudo grep -E '^(MINI_APP_BACKEND_ENABLED|MINI_APP_BACKEND_HOST|MINI_APP_BACKEND_PORT|MINI_APP_AUTH_MAX_AGE_SECONDS|MINI_APP_ALLOWED_ORIGINS)=' /etc/fvg-alert-bot.env
```

Expected production shape:

```dotenv
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru
```

Then verify the public reverse proxy/tunnel separately:

```bash
curl -i --max-time 8 https://tbbot.mstrategy.com.ru/healthz
curl -i --max-time 8 https://tbbot.mstrategy.com.ru/api/mini-app/settings
```

`/healthz` must return HTTP 200. A settings request made without Telegram `initData` is expected to fail quickly with an authentication response; it must not hang. Never paste real `X-Telegram-Init-Data` into shell history or logs.

## Fault isolation

- local `healthz` fails: Mini App backend/lifecycle problem;
- local `healthz` succeeds but public `healthz` fails or hangs: reverse proxy/tunnel problem;
- public `healthz` succeeds and unauthenticated settings responds quickly, but Telegram still fails: inspect Telegram `initData` authentication and allowed origin;
- all checks succeed after a frontend update: close and reopen the Telegram Mini App to discard a stale WebView instance.

Do not modify Amnezia/Xray or the VDS external port 443 while diagnosing this path.
