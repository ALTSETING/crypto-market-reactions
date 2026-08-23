# Stage 17 — High-Impact Directional Validation

## LOCKED TEST RESULT

**ЧИ ПЕРЕВИЩУЄ ЧЕСНА LOCKED-TEST ACCURACY 55%? NO**

- Final status: **DIRECTIONAL_PREDICTION_NOT_SUPPORTED**
- Selected horizon: 1h
- Neutral threshold: 0.10%
- Latency: 1m
- Predictions: 66 / 134 (coverage 49.25%)
- UP / DOWN / NO_SIGNAL: 33 / 33 / 68
- Correct / incorrect: 27 / 39
- Accuracy: 40.9091%
- Balanced accuracy: 0.4893899204244032
- Majority baseline: 0.4393939393939394
- Strongest simple market baseline: 0.3787878787878788
- Wilson 95% CI: [29.8674%, 52.9508%]
- Cluster bootstrap 95% CI: [28.1250%, 54.9296%]
- Walk-forward folds beating simple baseline: 0/3
- Locked configuration SHA-256: `5e81bf106834c3a8edf640cad718e2c113106059460198ffc34aa6dfa60831f9`

The model was selected using train + validation only. The locked-test target query occurred after the configuration and model hashes were persisted. Test outcomes were not used for feature, horizon, threshold, subgroup, confidence, or model selection.

Magnitude and volatility findings are secondary and do not affect this final directional status. No OpenAI API, paper trading, real trading, production polling, or automatic trade was run.
