# Восстановление после незавершённой установки rc1–rc3

Незавершённая первая установка не активирует релиз и может не создавать
`fvg-alert-bot.service`. Telegram token и admin ID при этом остаются в
`/etc/fvg-alert-bot.env`.

## Ошибка отсутствующего Python

```text
Python executable does not exist: /opt/fvg-alert-bot/.venv/bin/python
```

Эта ошибка исправлена в rc3 и новее.

## Ошибка заполненного диска или временного каталога

```text
sqlite3.OperationalError: database or disk is full
```

Проверьте место и inode:

```bash
df -h / /tmp /opt
df -ih / /tmp /opt
```

Покажите основные потребители места:

```bash
du -xh /root/.cache/pip /opt /var/log --max-depth=1 2>/dev/null | sort -h
```

Безопасно удалите кэш загрузок и остатки незавершённых staging-релизов:

```bash
rm -rf /root/.cache/pip
find /opt -maxdepth 1 -type d -name 'fvg-alert-bot.staging.*' -print -exec rm -rf -- {} +
apt-get clean
```

Не удаляйте `/etc/fvg-alert-bot.env` и `/var/lib/fvg-alert-bot`.

## Повторная установка

Используйте rc4 или более новый тег:

```bash
cd /root/TB
git fetch --tags --prune
git checkout v1.0.0-rc4
bash scripts/install_vds.sh
```

Начиная с rc4 установщик заранее требует не менее 512 МБ свободного места и
5000 inode на файловой системе `/opt`, отключает `pip`-кэш и размещает временные
файлы установки внутри staging-каталога.

После завершения проверьте:

```bash
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
```

Ожидаемые первые две строки: `active` и `enabled`.
