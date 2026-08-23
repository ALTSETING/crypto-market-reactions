# Stage 18A — Forensic Reconciliation and SHORT-Bias Audit

## SHORT BIAS RESULT

- Pattern A SHORT: **83.01%**.
- Pattern B SHORT: **82.88%**.
- Pattern A test target SHORT rate: 51.82%; raw directional model SHORT rate: 76.65%.
- Pattern B test target SHORT rate: 51.40%; raw directional model SHORT rate: 83.22%.
- The funnel is quantified in `stage18a_signal_funnel.csv`; neutral removal and the 0.40 directional confidence rule expose/amplify the skew.
- Main cause: A shared probability/model tendency toward DOWN after UP-vs-DOWN comparison; the confidence filter amplifies it. Separately, Dataset B has a confirmed mixed-scale semantic mapping defect (unconditional ×10 on values already in 0–100).
- Technical error found: **YES** — mixed 0–10/0–100 Stage 16 semantic values were all multiplied by 10, producing canonical values up to 1,000.

## RECONCILIATION

- Original Stage 17 frozen model replay: 100.00% exact signal agreement.
- Stage 17 vs Stage 17C persisted signal: 100.00%.
- Stage 17 → Stage 18 V2 same signal: 3/66; LONG→SHORT: 0; SHORT→LONG: 3; signal→NO_SIGNAL: 60.
- These V2 changes are model/version changes, not a nondeterministic replay: frozen Stage 18 replay matches persisted predictions 100%.
- Return mismatch: 0; target mismatch: 0; probability/signal mapping mismatch: 0.

## BASELINE CHECK

- Pattern A Stage 18 net expectancy: +0.1306%; Always SHORT: +0.3624%.
- Pattern B Stage 18 net expectancy: +0.1338%; Always SHORT: +0.2167%.
- Signal inversion is included as `opposite_stage18_signal`; it is diagnostic only.

## TECHNICAL FINDINGS

- `model.classes_` for both models is `[DOWN, NEUTRAL, UP]`; probability columns are accessed by class name, not assumed index. No LONG/SHORT inversion.
- Target formula, 0.10% units, latency, UTC timestamps, gross/net signs, and costs reconcile row by row.
- Feature names/order and bundled scaler/encoder/imputer match the frozen artifacts.
- Deterministic replay: 3/3 identical probability hashes for both models and 100% persisted signal match.
- Pattern A uses balanced class weights; Pattern B uses none. No resampling or sample weights were used.
- Missing values are explicitly flagged and median/mode imputed; their bias is quantified separately and is not the sole shared cause.
- Pattern B V2 is not identical to old Pattern B because the old fitted model and row-level predictions were unavailable.

## FINAL STATUS

**CRITICAL_BUG_CONFIRMED**

Forensic checklist PASS: **True**. Stage 18 predictive and economic conclusions are marked **INVALIDATED** because a critical semantic scale defect exists. No controlled refit was run. A corrected Stage 18B must be separately authorized and versioned; old reports remain untouched.

Integrity: protected artifacts unchanged=True; database unchanged=True; fit calls=0; OpenAI calls=0; trading actions=0; pytest=314 passed.
