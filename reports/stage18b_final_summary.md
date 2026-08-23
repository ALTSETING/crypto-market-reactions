# Stage 18B — Corrected Full Rebuild

Overall status: **SHORT_BIAS_REMAINS__NO_TRUE_UNTOUCHED_TEST**.

## PATTERN A

- Predictions: 176.
- LONG: 17.05%; SHORT: 82.95%.
- Accuracy: 44.32%; strongest same-timestamp test baseline: 49.43%.
- Mean gross: +0.2571%; mean net: +0.0571%.
- Net PF: 1.0940254890497267; maximum drawdown: -28.41%.
- Profitable folds: 2/5; folds above baseline: 1/5.
- Bootstrap P(net expectancy > 0): 66.03%.
- Reliability Score: 36.0/100.
- Status: **SHORT_BIAS_REMAINS**.

## PATTERN B

- Predictions: 1110.
- LONG: 16.67%; SHORT: 83.33%.
- Accuracy: 50.72%; strongest same-timestamp test baseline: 52.07%.
- Mean gross: +0.3416%; mean net: +0.1416%.
- Net PF: 1.2517046183710048; maximum drawdown: -66.37%.
- Profitable folds: 1/5; folds above baseline: 2/5.
- Bootstrap P(net expectancy > 0): 99.69%.
- Reliability Score: 58.3/100.
- Status: **SHORT_BIAS_REMAINS**.

## Direct answers

- The Stage 18 scale bug is corrected; all normalized semantics are in 0..1 (signed valence -1..1).
- Erroneous >80% directional bias remains: yes.
- Shadow mode is allowed only when explicitly marked as a shadow candidate below; real trading remains prohibited.
- Pattern A shadow candidate: False; Pattern B: False.
- Real trading readiness: **NO**. There is no true untouched forward test.

Integrity: protected unchanged=True; database unchanged=True; API calls=0; trading actions=0; pytest=344 passed.
