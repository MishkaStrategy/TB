# Восстановление после незавершённой установки rc1/rc2

Если первая установка остановилась с сообщением:

```text
Python executable does not exist: /opt/fvg-alert-bot/.venv/bin/python
```

релиз не был активирован, а systemd unit ещё не создавался. Сохранённые Telegram token и admin ID остаются в `/etc/fvg-alert-bot.env`.

Повторите установку на исправленном релизе:

```bash
cd /root/TB
git fetch --tags --prune
git checkout v1.0.0-rc3
bash scripts/install_vds.sh
```

После завершения проверьте:

```bash
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
```

Ожидаемые первые две строки: `active` и `enabled`.
