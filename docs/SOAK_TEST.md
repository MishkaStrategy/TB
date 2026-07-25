# Нагрузочная проверка FVG pipeline

`run_fvg_soak.py` генерирует синтетические FVG-события и проводит их через
реальные `FvgAlertService`, SQLite/WAL и persistent outbox. Внешние запросы к
Telegram и Bitunix не выполняются: вместо Telegram используется считающий bot
stub.

Проверяются инварианты:

- каждое событие сохранено ровно один раз;
- каждый получатель имеет ровно одну delivery-запись;
- после успешного прогона outbox пуст;
- число вызовов bot stub равно ожидаемому числу доставок;
- фиксируются duration, deliveries/sec, peak Python memory и размер SQLite;
- optional thresholds превращают деградацию в ненулевой exit code.

Пример smoke-прогона:

```bash
.venv/bin/python run_fvg_soak.py \
  --database data/soak/fvg-soak.sqlite3 \
  --events 1000 \
  --recipients 10 \
  --batch-size 100 \
  --reset \
  --output data/reports/fvg-soak-1000x10.json
```

Более длительная проверка перед VDS-запуском:

```bash
.venv/bin/python run_fvg_soak.py \
  --database data/soak/fvg-soak.sqlite3 \
  --events 10000 \
  --recipients 25 \
  --batch-size 100 \
  --max-seconds 900 \
  --max-peak-memory-mb 512 \
  --reset \
  --output data/reports/fvg-soak-10000x25.json
```

Порог времени зависит от VDS и не зафиксирован в коде. Сначала сохраните baseline
на целевой машине, затем используйте его как regression threshold. База soak
должна быть отдельной от production-state; существующий файл без `--reset`
никогда не перезаписывается.

Harness не заменяет сетевой soak. После установки дополнительно наблюдайте
реальный процесс через `journalctl`, `systemctl show` и health-метрики минимум
несколько торговых сессий, но не включайте реальные массовые Telegram-доставки
ради теста.
