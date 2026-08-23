# Stage 10 ETH AI label effectiveness

## Scope

- Model: `gpt-5-mini-2025-08-07`; prompt: `eth_label_v1`.
- 7,065 successful labels audited; 7,058 have complete ETHUSDT reactions.
- 7 excluded rows are individually documented in `stage10_eth_summary.json` and were not imputed.
- Article-level n=7,058; earliest-article event-level n=6,851.

## Findings

- Direction has no stable prognostic value. Best all-data balanced accuracy is 0.3675 at 15m with a ±1.00% band, but MCC is only 0.0136 and kappa 0.0061. Article- and event-level results are both approximately chance-level.
- On the untouched chronological test period, AI beats the best simple baseline only at 30m and 1h, by small margins (0.0050 and 0.0095 balanced-accuracy points). It loses at the other four horizons.
- Sentiment/return Pearson and Spearman correlations are near zero at every horizon (absolute values below 0.03).
- Importance has 2/6 BH-significant correlations with absolute movement (30m and 4h), but both effects are weak and negative (-0.037 and -0.042); higher importance did not predict stronger movement.
- Confidence does not provide a stable direction filter. The strongest all-data cell is confidence >=70 at 24h (accuracy 0.370, n=181), but this is not confirmed by the chronological threshold test.
- High ETH relevance (>=70) does not increase ETH movement. Its only BH-significant comparison is a negative 4h magnitude difference.
- Category raw accuracy is heavily affected by the neutral-class share. No category is accepted as reliably useful without balanced, time-split, and source-stable confirmation.
- Thresholds were shortlisted on train, selected on validation, and evaluated once on test. The test set was never used for threshold selection.
- The only selected combination is 24h: confidence>=50, importance>=40, |sentiment|>=50, relevance>=90. Its test result is 50% win rate with n=10 and 95% CI [0.237, 0.763], so it is inconclusive.

## Readiness assessment

- Final ML training: **not performed in Stage 10**. The dataset is suitable for controlled feature-ablation research, but the AI labels alone are not validated predictive features.
- Paper trading: **not yet justified**. The only selected threshold has an inadequate test sample and a confidence interval spanning poor and good outcomes.
- Real trading: **not justified** by this observational study. Transaction costs, latency, slippage, execution, and prospective validation are absent.

## Final conclusion

Stage 10 execution is **PASS** because coverage, controls, significance testing, leak-free splits, reports, and tests are complete. The hypothesis that GPT-5 mini labels provide a stable tradable ETH edge is **not supported**. Continue only with offline ML experiments and prospective data collection; do not start paper or real trading from these labels alone.

## Limitations

- Seven analyses are outside available ETHUSDT candle coverage and are documented, not imputed.
- Returns end at 24h, so AI weeks/months horizons are marked unverifiable rather than wrong.
- Time-to-MFE/MAE is unavailable; only stored 1h extrema exist.
- Observational correlations do not establish causality.
- Threshold search uses train/validation/test chronology; test is not used for selection.
