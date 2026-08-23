# Stage 18 — Unified Pattern Reanalysis

Overall status: **NO_TRUE_UNTOUCHED_TEST**. This is offline research; no paper or real trading was started.

## Data and coverage

- Canonical events: 7,878; event-asset rows: 8,039.
- Dataset A/B/C/D rows: A=6,851, B=862, C=326, D=0.
- Cross-dataset duplicate evidence pairs: 779.
- Fully covered event-assets: 7,947; excluded for missing candles: 92.
- Stored 1-minute path rows: 11,451,627; synthetic/interpolated candles: 0.
- Maximum feature lookback: 24h (derived maximum feature need was 12h; the stricter Stage 18 minimum was used). Maximum reaction path: 24h.

## Pattern A V2

- Status: **NOT_SUPPORTED**; locked-test predictions: 153; accuracy: 45.10%.
- Strongest validation baseline: 52.48%; folds beating baseline: 3/5.
- LONG/SHORT: 26/127; net expectancy: +0.1306%; PF: 1.2375271387747953.

## Pattern B V2

- Status: **PARTIAL_EVIDENCE**; locked-test predictions: 1,110; accuracy: 50.90%.
- Strongest validation baseline: 51.88%; folds beating baseline: 2/5.
- LONG/SHORT: 190/920; net expectancy: +0.1338%; PF: 1.2363195165608407.

## Direct answers

1. Pattern A confirmation: NOT_SUPPORTED.
2. Pattern B confirmation: PARTIAL_EVIDENCE.
3. Accuracy above 55%: A=False, B=False.
4. Better than frozen validation baseline: A=False, B=False.
5. LONG and SHORT were evaluated separately; exact counts and metrics are in pattern reports.
6. Average moves by horizon are in `stage18_horizon_sensitivity.csv`.
7. Median time-to-MFE and MFE/MAE are in `stage18_mfe_mae_analysis.csv`.
8. The old 1h horizon was too short only as retrospective sensitivity; the primary 12h exit was frozen before this test and was not reselected.
9. Post-cost result: A net expectancy +0.1306%, B +0.1338% at 0.20% round-trip cost.
10. Year/fold stability is reported separately; folds beating baseline are shown above.
11. Events excluded for candle coverage: 92.
12. All Stage 18 API calls cost **$0.00**; existing semantic results plus explicit missing flags were sufficient.
13. The $2.00 hard limit was respected; remaining budget is $2.00.

## Integrity

- Leakage: 0; predictive fields used as features: 0; paid requests: 0.
- Protected Stage 8–17 artifacts unchanged: True; controlled DB tables unchanged: True.
- Pytest: 295 passed, return code 0.
- Current chronological test is not truly untouched because all of its events had prior Stage 8–17 exposure: True. Therefore the overall epistemic label is `NO_TRUE_UNTOUCHED_TEST` even where a pattern-level metric is positive.
