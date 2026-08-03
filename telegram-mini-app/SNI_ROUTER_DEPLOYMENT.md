# TLS SNI router deployment

This runbook shares the single public `188.137.236.73:443` listener without
terminating or modifying Xray Reality traffic.

```text
public :443 (Nginx stream ssl_preread)
├── SNI tbbot.duckdns.org -> 127.0.0.1:8443 (Nginx HTTPS)
└── default               -> 127.0.0.1:2443 (amnezia-xray container :443)
```

The backend remains disabled at `127.0.0.1:18080`. The procedure does not
change UFW, `/etc/fvg-alert-bot.env`, `fvg-alert-bot`, BotFather, or the
`doh-socks-files.service` listener on port 8080.

## Guarded workflow

Run from the exact audited checkout as root. Never store the Let's Encrypt
email in Git.

```bash
sudo LETSENCRYPT_EMAIL='<real-email>' scripts/manage_tbbot_sni_router.sh preflight
sudo LETSENCRYPT_EMAIL='<real-email>' scripts/manage_tbbot_sni_router.sh prepare
```

`prepare` creates a root-only snapshot under
`/var/backups/tbbot-sni-router/<UTC_TIMESTAMP>/`. On Amnezia installations
whose live Xray configuration resides in the writable container layer, the
snapshot includes a paused `docker commit`, the complete Docker inspect data,
the Xray configuration, Nginx/Certbot state, and a strict SHA-256 manifest.

The HTTP site serves `/.well-known/acme-challenge/` from
`/var/www/letsencrypt`. Issue the certificate before moving port 443:

```bash
sudo LETSENCRYPT_EMAIL='<real-email>' scripts/manage_tbbot_sni_router.sh certificate <snapshot>
```

After checking the certificate, arm the 30-minute rollback and switch:

```bash
sudo scripts/manage_tbbot_sni_router.sh apply <snapshot>
sudo scripts/manage_tbbot_sni_router.sh status <snapshot>
sudo scripts/manage_tbbot_sni_router.sh verify <snapshot>
```

`apply` never cancels the timer. If any step fails, it immediately invokes the
same idempotent rollback routine. Manual rollback is:

```bash
sudo scripts/manage_tbbot_sni_router.sh rollback <snapshot>
```

Before commit, verify Amnezia/VPN from an external device. Record that explicit
confirmation using the root-only marker documented in the deployment log, then
run:

```bash
sudo scripts/manage_tbbot_sni_router.sh commit <snapshot>
```

Without the external confirmation marker, `commit` refuses to cancel the
automatic rollback.
