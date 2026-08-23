# Stage 17C — Current return formula

- Source: `high_impact_sources/analysis/reaction_calculator.py`
- Function: `calculate_event_reaction`; timestamp helper: `baseline_minute` / `next_full_minute`.
- Formula: **endpoint return**, not a median or average: `return_h = (open_at(entry + horizon) / open_at(entry) - 1) * 100`.
- Entry timestamp: first full UTC minute strictly after `published_at`, plus `latency_minutes`.
- Locked latency: 1 minute for both configurations.
- Candle selection: exact `market_candles.open_time` at entry and entry+horizon; a missing exact candle means missing coverage. No interpolation or synthetic candles.
- Pattern A locked current horizon: 1h. Pattern B locked current horizon: 12h.
- LONG trade return: raw endpoint return. SHORT trade return: negative raw endpoint return.
