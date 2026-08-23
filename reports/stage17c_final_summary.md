# Stage 17C — Optimal Reaction Window Audit

Overall status: **PARTIAL_DIAGNOSTIC**

## Pattern A — persisted locked-test signals

- Pattern ID: `stage17_directional_lock_v1:5e81bf106834c3a8edf640cad718e2c113106059460198ffc34aa6dfa60831f9`
- Available signals: 66/66 (100%).
- Current locked horizon: 1h; current accuracy: 40.91%.
- Найчастіше рух починався через: median 1 хв.
- Найкраща ціна зазвичай була через: median 316 хв.
- 12h exit зберігав median 34.08% MFE; average giveback 1.326%.
- Best accuracy horizons: 8h, 12h (tie at 57.58%).
- Best gross horizon: 12h (+0.338%).
- Best net horizon: 12h (+0.138%, PF 1.217).
- Any alternative horizon is **RETROSPECTIVE / EXPLORATORY**, not a confirmed locked-test result.
- Current 1h rule beat its fold baseline in 0/3 folds. Candidate 12h fold stability cannot be reconstructed because historical fold prediction rows/models were not persisted.

## Pattern B — incomplete evidence

- Pattern ID: `model:semantic_plus_market:gradient_boosting:12h:0.1:0.4:ETH`
- Prediction-level availability: 0/111 walk-forward and 0/46 validation signals (0%).
- Only aggregate metrics survive; event IDs, LONG/SHORT mappings, confidence and fold prediction rows do not.
- Frozen GradientBoosting artifact: absent.
- Persisted current-12h aggregate beat baseline in 1/3 folds (weak), but path/horizon alternatives are unavailable.
- Status: **INSUFFICIENT_SAMPLE / CANNOT_RECONSTRUCT_WITHOUT_REFIT**.

## Main answers

1. Whether 12h hid an early move is measurable for Pattern A only: median retained MFE at 12h was 34.08%.
2. Pattern A median time to maximum favorable price was 316 minutes.
3. Pattern A average giveback by 12h was 1.326%.
4. Pattern A retrospective best net candidate was 12h; it is not confirmed.
5. Pattern B optimal horizon is not identifiable without forbidden refitting.
6. Pattern A best-net candidate expectancy was +0.138% after Base costs.
7. Pattern A current 1h result was 0/3 versus fold baselines; Pattern B current 12h was 1/3. Candidate-horizon stability is unknown because fold-level signals were not persisted.

No `fit()`, OpenAI API, paper trading, real trading, interpolation or synthetic candles were used. Stage 17/17B statuses and protected artifacts remain unchanged.
