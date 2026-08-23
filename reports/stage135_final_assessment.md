# Stage 13.5 — Final assessment

Infrastructure status: **PASS**. Predictive improvement: **NOT SUPPORTED**.

The free local scope is complete. Early reactions cover 6,851/6,851 events at latencies 0–3 minutes. No post-news target entered the predictors, cutoff violations are zero, duplicate-key groups are zero, and all 116 tests pass.

Late-publication rates are 34.67% at 0.10%, 14.04% at 0.25%, 3.34% at 0.50%, and 0.58% at 1.00%. A median primary-to-media delay cannot be estimated: the 10 official events collected in the live sample produced no high-confidence match to the 6,851 historical event groups.

Source timing rank from the media timestamp audit is Cointelegraph, CoinDesk, Decrypt. This is an apparent publication-timing rank, not proof of first information arrival.

Funding is complete for both ETHUSDT and BTCUSDT within 2023-01-01–2026-07-01. Official Binance 5-minute OI/ratio/taker endpoints expose only recent history; consequently those features cover 133 events (1.94%), and the earlier interval is explicitly documented as unavailable rather than imputed.

The controlled Ridge ablation found no supported incremental value in any of 8 comparisons: every futures or futures+primary/timing variant had worse chronological-test MAE than Market Core. The richer inputs therefore must not replace the Stage 13 baseline on current evidence.

ETF remains blocked pending a verified provider. Etherscan and FRED dry-runs require free keys and have estimated API cost $0; no key or paid provider was invoked. A paid Etherscan tier would start around $41.65/month if later authorized.

Stage 8–13 integrity: all preflight hashes and source-table row counts are unchanged. No OpenAI job, paper/real trading, production deployment, or paid API was run.
