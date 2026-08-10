# FVG Alert Bot 1.3.7

`1.3.7` is an immutable patch release that preserves the externally configured Telegram Mini App Menu Button across bot restarts and production updates.

## Root cause and fix

`configure_bot_interface()` refreshed localized commands and then unconditionally called `setChatMenuButton(MenuButtonCommands)`. Every service start therefore replaced the persistent Web App Menu Button configured through Bot API/BotFather.

The bot now refreshes only its localized command lists. It does not mutate the persistent Menu Button. The Mini App URL remains an external deployment setting rather than a domain hard-coded into runtime code.

## Regression coverage

- command configuration is executed against a Bot API mock that has no Menu Button mutation method;
- the release contract rejects `set_chat_menu_button` and `MenuButtonCommands` in `bot.py`;
- the complete Python suite, dependency audit, frontend build, backup tests, bounded soak and systemd verification remain required by release CI.

## Production safety

- Telegram uses only the BotFather token; API ID/hash, Telethon, Pyrogram and user sessions are not used;
- `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot`, SQLite databases and user settings are preserved;
- operational flags are not enabled automatically;
- Xray, Nginx, UFW, port 8080 and the Mini App frontend artifact are not changed by the bot updater;
- `v1.3.6` and all earlier tags remain immutable.

## Release archive

The release workflow creates `fvg-alert-bot-1.3.7.tar.gz` and its SHA-256 checksum only from the reviewed two-parent merge commit on `main` after required checks pass.
