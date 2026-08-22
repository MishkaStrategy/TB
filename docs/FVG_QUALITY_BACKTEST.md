# FVG quality backtest methodology

The historical FVG quality report measures observable outcomes of confirmed
FVG alerts. It does not invent entry, stop-loss, take-profit or P&L rules that
do not exist in the production alert contract.

## Detection boundary

An event is detected from exactly three closed, complete candles A/B/C using the
same confirmed-FVG detector as the production 15-minute path.

Only candles strictly after closed candle C may affect:

- first touch latency;
- full fill latency;
- MFE;
- MAE;
- horizon eligibility and touch/fill rates.

Future candles cannot alter the event ID, direction, zone or signal price.

## 15-minute continuity invariant

A bar-count horizon represents elapsed consecutive 15-minute bars, not merely
the next N rows present in a CSV file.

For every detected event, the evaluator expects the first future candle at
`candle C open time + 15 minutes`, then advances in exact 15-minute steps.

If the next available row does not have the expected timestamp:

1. the first mismatch is treated as a hard data-quality boundary;
2. no missing candle is synthesized;
3. rows after the boundary are not used for latency, MFE/MAE or horizon metrics;
4. only the contiguous prefix before the gap remains eligible;
5. the event records the number of valid bars before the gap plus the expected
   and actual timestamps.

This prevents a missing 15-minute row from compressing 30+ minutes of elapsed
time into `1 bar`.

## End-of-data versus data gaps

The report distinguishes two reasons why an event may not have a complete
maximum horizon:

- `events_truncated_by_gap` — a timestamp discontinuity was observed before the
  requested maximum horizon;
- `events_truncated_by_end_of_data` — the dataset ended before the requested
  maximum horizon, without an observed gap.

`events_with_complete_max_horizon` counts events with enough consecutive future
bars to evaluate the full maximum horizon.

Input metadata also reports `continuity_gaps`, the number of non-15-minute
transitions after CSV sorting and deterministic timestamp de-duplication.

## CSV handling

The loader:

- accepts the supported timestamp column aliases;
- normalizes timestamps to UTC;
- sorts candles chronologically;
- de-duplicates identical open timestamps deterministically with the last row
  winning;
- repairs the OHLC envelope so high/low contain open and close;
- emits closed, complete 15-minute candles for research analysis.

De-duplication does not fill missing intervals.

## Reproducibility

For a fixed input CSV, symbol, horizon set and code revision, event detection and
quality metrics are deterministic. `generated_at` is report metadata and is not
part of the trading calculation.

When comparing historical quality results, record at least:

- repository commit SHA;
- input dataset identity/hash where available;
- symbol;
- requested horizons;
- input candle count and time range;
- `continuity_gaps`;
- the report `data_quality` section.

## Scope boundary

This methodology changes research-quality measurement only. It does not change
production FVG detection, exchange adapters, scheduler timing, user filters or
notification delivery.

Related issue: #119.
