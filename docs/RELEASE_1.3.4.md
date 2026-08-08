# FVG Alert Bot 1.3.4

`1.3.4` — patch-релиз, исправляющий мультибиржевой FVG runtime и восстанавливающий подтверждённые FVG на `15m`, `1h`, `4h`, `1d` при единственном биржевом источнике `15m`.

## Исправлено

- устранена регрессия, из-за которой после перехода на облегчённый источник данных активный FVG runtime фактически сводился к `15m`;
- для всех активов с бирж загружаются только закрытые `15m` свечи, а `1h`, `4h`, `1d` строятся локально по UTC-границам;
- `1h` агрегируется из 4 последовательных `15m`, `4h` — из 16, `1d` — из 96;
- пред-FVG и минутные `1m` свечи остаются удалёнными из runtime и Telegram UI;
- сохранённые `1h/4h/1d` больше не нормализуются принудительно в `15m`;
- исправлен Gate Futures candle parser для объектного ответа `t/o/h/l/c`;
- `MAX_ACTIVE_SYMBOLS` применяется к уникальным `exchange + symbol`, а не к отдельным строкам таймфреймов;
- один набор `15m` переиспользуется для всех закрывшихся таймфреймов одного рынка;
- пустой candle source для активного рынка теперь считается operational failure и попадает в health counters вместо молчаливого пропуска;
- сбой одной биржи или инструмента не останавливает обработку остальных рынков;
- Bitunix дневной lookback использует пагинацию истории `15m` при необходимости более 200 свечей.

## Telegram UI

- возвращён выбор подтверждённых таймфреймов `15m / 1h / 4h / 1d`;
- пред-FVG не возвращён;
- команда `/fvg_pre_alert` отсутствует;
- FAQ объясняет, что биржевой источник всегда `15m`, а старшие таймфреймы строятся локально.

## Диагностика

Повторный аудит показал, почему на production могла наблюдаться картина «BTC/Bitunix работает, остальные инструменты молчат»: Bitunix имел отдельный WebSocket/REST fallback, а другие биржи зависели от общего multi-exchange control job. В `1.3.4` пустые/неразобранные данные общего пути больше не маскируются под отсутствие FVG.

После обновления нужно проверить фактический `/opt/fvg-alert-bot/BUILD_COMMIT`, активные пользовательские инструменты и первые multi-exchange control cycles в journal.

## Release safety

- release tag и assets должны быть immutable;
- публикация существующего version tag на другом commit должна завершаться ошибкой вместо `--clobber` существующего архива;
- production deployment выполняется отдельно по `v1.3.4` и точному audited SHA;
- `/etc/fvg-alert-bot.env` и `/var/lib/fvg-alert-bot` сохраняются;
- Telegram Mini App и Telegram user-session credentials не входят в релиз.

## Проверка релиза

Обязательны:

- dependency audit;
- Python compilation;
- полный unit suite;
- payload-contract tests для Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- non-BTC end-to-end test `15m source -> FVG -> recipient`;
- multi-timeframe aggregation tests;
- bounded pipeline smoke и notification soak;
- VDS candidate isolation;
- production systemd render/verify.
