SUCCESSFUL PERIOD

- Дати: 2025-07-14 — 2025-11-17
- Точність моделі: 58.33%
- Baseline: 55.26%
- Сигналів: 36
- LONG accuracy: 63.64%
- SHORT accuracy: 50.00%
- ETH за весь період: +4.06%
- Режим ринку: sideways
- Середня волатильність: 72.40% annualized

AVERAGE MOVES AFTER SIGNALS

- Середній ріст ETH: N/A
- Середнє падіння ETH: N/A
- Середній рух при правильному прогнозі: N/A
- Середній рух проти прогнозу: N/A
- Середній gross результат: +0.20%
- Середній net результат після Base costs: +0.00%
- Беззбиткова необхідна точність (gross): N/A
- Беззбиткова необхідна точність (Base): N/A

PERIOD COMPARISON

- Fold 1: 2024-06-20 — 2025-02-13, accuracy 51.35%, falling/normal_volatility
- Fold 2: 2025-02-13 — 2025-07-07, accuracy 39.47%, sideways/highly_volatile
- Fold 3: 2025-07-14 — 2025-11-17, accuracy 58.33%, sideways/normal_volatility


FINAL DIAGNOSTIC ANSWER

1. Модель перевищила 55% і strongest baseline лише у Fold 3: 2025-07-14 — 2025-11-17.
2. ETH за цей evaluation period змінився на +4.06% (sideways).
3. Середній фактичний 12h ETH move після 36 walk-forward сигналів Fold 3: -0.28%; середній trade-signed gross: +0.20%.
4. У Fold 3 LONG accuracy була 63.64%, SHORT — 50.00%; описово сильнішою була LONG leg.
5. Gross winners перекривали losers (profit factor 1.306); після Base costs profit factor був 1.006.
6. Успішний fold описово відрізнявся ринковим режимом, source/event mix і pre-event context, наведеними у `stage17b_period_comparison.csv`; причинний висновок на трьох folds не робиться.

DATA AVAILABILITY LIMITATION

Stage 17B не зберіг prediction-level `event_id + signal + future_return`. Тому medians, min/max/std, absolute-move bins, окремі average moves для correct/incorrect LONG/SHORT, direction-specific profit factors, signal-only source/event distributions і duplicate prediction-row check доказово недоступні. Їх позначено `null`; модель не перенавчалась і thresholds/mapping/lock не змінювалися. Окремі 46 validation signals наведені лише у блоці B і не змішані зі 111 walk-forward signals.

AUDIT STATUS

- Existing aggregate arithmetic: PASS.
- Lock/config immutability: PASS.
- Requested prediction-level diagnostics: FAIL — source rows were never persisted.
- Overall diagnostic completeness: PARTIAL_EVIDENCE.
- Stage 17B status remains `INSUFFICIENT_NEW_DATA`; цей audit не є новим test.
