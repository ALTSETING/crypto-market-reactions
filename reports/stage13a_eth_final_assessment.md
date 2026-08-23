# Stage 13A ETH Early Reaction Timing Audit

Technical status: PASS

Timing conclusion: EARLY_REACTION_NOT_SUPPORTED

Median absolute 5m pre-move: 0.1012%. Median absolute 5m post-move: 0.1092%. The aggregate result therefore does not show that the main move usually occurs before publication.

Late-publication rate at 0.10%: 28.39%. This is a material late-timestamp subset rather than a universal effect. Cointelegraph has the fastest apparent publication in the three-source comparison; CoinDesk and Decrypt have higher late-publication rates. Primary-source integrations, exchange/regulator/project announcement feeds, and lower-latency realtime ingestion are recommended for this subset.

The strict early-reaction claim is accepted only when all five decision checks pass. It fails because 1–5m abnormal effects are weaker than 15m–1h effects and AI direction is not better at early horizons. This audit ran no ML, OpenAI API, paper trading, or real trading and did not alter Stage 8–12 datasets.
