# Stage 17B — Bidirectional LONG/SHORT Pattern Discovery

## Final status

`INSUFFICIENT_NEW_DATA`

Stage 17 remains unchanged with status `DIRECTIONAL_PREDICTION_NOT_SUPPORTED`. Its opened 134-row test was not queried or reused. The database contains **0** eligible events after `2026-07-01T00:00:00+00:00`, so no new locked confirmation is scientifically possible. The configuration below is locked only for a future shadow period.

## Discovery boundary

- Discovery rows: 534 event-asset rows / 434 events (original train + validation only).
- Opened Stage 17 test outcomes read: 0.
- Generated explicit rules: 500 (maximum 500); maximum conditions: 2.
- LONG validation shortlist: 57.
- SHORT validation shortlist: 4.
- Combined validation shortlist: 6.
- Best separate LONG validation pattern: 68.89% / 45 signals / ALL / 12h.
- Best separate SHORT validation pattern: 59.09% / 22 signals / ETH / 5h.
- Selected experimental config: `gradient_boosting` / `semantic_plus_market` / `ETH` / `12h` / neutral ±0.10% / confidence 0.40.
- Validation gate passed: True.
- Nested walk-forward folds above both 55% and strongest baseline: 1/3.
- Leakage: 0; OpenAI requests: 0; paper/real trades: 0.
- Base cost includes 0.05% entry fee + 0.05% exit fee + 0.05% entry slippage + 0.05% exit slippage. Funding data is unavailable and shown as 0, not silently estimated.
- Selected combined candidate is directionally uneven: LONG 65.38%, SHORT 50.00%.
- Primary gross expectancy: +0.1573% per signal; Base-cost expectancy: -0.0427%, profit factor 0.9417.
- Pytest: PASS (231 passed).
- Stage 17 artifact integrity: PASS (61 files, aggregate SHA-256 `e59dafb6e1634164ff514b4ee49cd6369657ec1b4e5db10aa6f8bc28592a0404`).

## Required answers

1. **LONG patterns found?** Validation candidates exist (57), but none is confirmed on new OOS.
2. **SHORT patterns found?** Validation candidates exist (4), but none is confirmed on new OOS.
3. **Best feature set?** `semantic_plus_market` on train+validation only; not an OOS conclusion.
4. **Best asset?** `ETH` on train+validation only.
5. **Best horizon?** `12h` on train+validation only.
6. **LONG accuracy?** Best separate pattern: 68.89% (45 validation signals). Locked combined candidate LONG leg: 65.38% (26).
7. **SHORT accuracy?** Best separate pattern: 59.09% (22 validation signals). Locked combined candidate SHORT leg: 50.00% (20).
8. **Combined accuracy?** 58.70% (46 validation signals; coverage 95.83%).
9. **Above 55%?** Yes on validation only; this does not satisfy the new-OOS success criterion.
10. **New shadow period needed?** Yes. At least 50 untouched predictions are required with the locked SHA `509a91b2d6fda0991eba012cf273ad54ef9b2f711a49a6891a7ba0a7277f900e`.

No ML/pattern claim is promoted to trading. No next stage was started.
