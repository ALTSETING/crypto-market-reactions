# Semantic Event Matching V2 — final report

## Outcome

Semantic Event Matching V2 replaces broad keyword inclusion with a deterministic server-side event-meaning model: asset role, actor, action, direction, magnitude, normalized amount, topic, confidence, and bounded entity text. AI resolves only an allowlisted intent and never receives database rows.

Production Supabase writes: **NO**. Reaction V2 values recalculated: **NO**.

## Semantic relevance audit

The immutable golden dataset contains 150 real production events: 30 large investments; 20 institutional purchases; 20 institutional selling/outflow; 20 ETF; 20 SEC; 20 hacks; and 20 hard negative controls. Selection is pinned by production `event_id` and is independent of candidate matcher output.

| Matcher | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| Frozen V1 baseline | 0.8667 | 0.6000 | 0.7091 | 12 | 52 |
| Semantic V2 | 1.0000 | 1.0000 | 1.0000 | 0 | 0 |

All required gates pass. SEC, ETF, hack, and large-investment precision are each 1.0000 on the golden set. This result is evidence for the reviewed sample, not a claim of perfect performance on every future headline.

The legacy 339-event ETH “large investment” sample contains only 23 independently classified true large ETH investments (6.78%); 316/339 (93.22%) are non-target under the audit taxonomy.

| Legacy classification | Count | Share |
|---|---:|---:|
| True large ETH investment | 23 | 6.78% |
| Generic investment | 19 | 5.60% |
| Funding only | 54 | 15.93% |
| Acquisition only | 56 | 16.52% |
| ETH secondary mention | 142 | 41.89% |
| Unrelated false positive | 45 | 13.27% |

The old sample has 157 explicit headline amounts and 182 without one. Explicit amounts: 12 below $10M; 36 from $10M to below $50M; 43 from $50M to below $250M; 23 from $250M to below $1B; and 43 at least $1B. Median is $175M; maximum is $122B. The retained default is **$50M**. EUR is converted deterministically at a fixed 1.08 USD/EUR; no live FX API is used. Amountless events qualify only through a small strong-phrase allowlist at confidence 0.6.

## Statistical impact on existing Reaction V2

The shipped TypeScript classifier finds 55 direct-primary-ETH large-investment events, 48 direct-primary-ETH institutional-buying events, and 33 direct-primary-ETH institutional-selling/outflow events in the bounded 9,073-row read-only snapshot. `related_assets` or `primary_asset` without a direct headline asset reference remains secondary and is excluded by default.

| Horizon | Legacy large n / mean / median / positive | V2 large n / mean / median / positive |
|---|---|---|
| 1m | 339 / -0.0019 / 0.0016 / 50.74% | 55 / -0.0374 / -0.0162 / 41.82% |
| 5m | 339 / -0.0114 / -0.0079 / 47.20% | 55 / 0.0480 / 0.0242 / 58.18% |
| 15m | 339 / -0.0112 / -0.0030 / 49.26% | 55 / 0.0566 / 0.1118 / 61.82% |
| 1h | 339 / -0.0629 / -0.0391 / 48.38% | 55 / -0.1021 / -0.1761 / 47.27% |
| 4h | 339 / -0.0014 / -0.0199 / 49.26% | 55 / -0.2092 / -0.1433 / 47.27% |
| 24h | 339 / -0.2399 / -0.2622 / 47.79% | 55 / -0.3474 / -0.9185 / 41.82% |

| Horizon | Institutional buying n / mean / median / positive | Selling/outflow n / mean / median / positive |
|---|---|---|
| 1m | 48 / -0.0254 / -0.0082 / 43.75% | 33 / 0.0144 / -0.0121 / 42.42% |
| 5m | 48 / 0.0301 / 0.0179 / 56.25% | 33 / 0.0052 / -0.0215 / 45.45% |
| 15m | 48 / 0.0806 / 0.1196 / 60.42% | 33 / -0.1016 / -0.0675 / 36.36% |
| 1h | 48 / 0.0254 / 0.1501 / 54.17% | 33 / -0.0629 / 0.0093 / 54.55% |
| 4h | 48 / -0.0384 / -0.1087 / 47.92% | 33 / -0.2126 / -0.4349 / 30.30% |
| 24h | 48 / 0.1486 / -0.1793 / 47.92% | 33 / -0.0400 / -0.6578 / 42.42% |

The buying and selling samples are distinct and directionally meaningful; they are not reused broad keyword samples. Raw mean, median, 5% trimmed mean, sample SD, SE, and positive-share Wilson 95% CI are computed by backend analytics. At 24h, the trimmed means are -0.4120 for V2 large investments, 0.0939 for institutional buying, and -0.0594 for selling/outflow, making outlier sensitivity explicit without replacing the raw mean.

Independent Decimal-based verification covered 30 cases for n, mean, median, positive share, and trimmed mean at tolerance `1e-9`; mismatches: **0**.

## Event timestamp audit

The stratified read-only sample contains 120 events: 60 news-media and 60 primary-document records. Production `event_at` coverage is 0/9,073, and the sample contains zero manually linked high-confidence canonical announcement pairs. Consequently median/p75/p90 lag, shares above 5m/15m/1h, and canonical-vs-publication reaction deltas are **unavailable**, not zero.

Prior contextual proxies cover 6,851 ETH events and show 28.39% pre-publication movement at the Stage13a 0.10% proxy (34.67% under the Stage13.5 proxy classification), but those signals are not canonical timestamp pairs.

Decision gate: **B**. Plan a future Reaction V3 around separately reviewed canonical event timestamps and news-to-primary links. Do not build or migrate V3 in this task; keep every Reaction V2 value unchanged. The evidence proves that `published_at` alone is insufficient for claims about reaction from the event itself, while exact canonical lag bias remains unmeasurable until canonical timestamps exist.

## Verification and limitations

- Frontend: ESLint PASS; TypeScript PASS; 155 Vitest PASS, 3 opt-in suites skipped in the ordinary run; Next production build PASS.
- Production parity: 30 legacy numeric cases at `1e-9` plus 30 semantic bounded-contract cases PASS against the 9,073-event read-only snapshot.
- Quality: 150-event golden evaluation PASS; timestamp audit PASS; 10 required Ukrainian/English semantic API examples PASS with different normalized intents and samples.
- Security: bounded scans at 10,000; at most 50 citations; same-origin/rate-limit/safe-error gates retained; API security smoke PASS; client bundle scan PASS; no rows sent to OpenAI.
- Python: focused audit suites 10/10 PASS. Full repository suite: 398 PASS, 14 skipped, 7 failures caused solely by pre-existing Stage12 manifest/report hash mismatches in unchanged files.

Detailed machine-readable evidence is in `semantic_quality_audit.json`, `candidate_predictions.jsonl`, `timestamp_audit_summary.json`, and the CSV audit artifacts in this directory.
