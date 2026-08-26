# Event Timestamp Audit - Semantic Matching V2

Generated read-only from production at `2026-08-26T09:18:18.374061+00:00`. No Reaction V2 value, schema,
or production row was changed.

## Coverage and evidence

- Production rows: **9,073**.
- Production rows with `event_at`: **0**
  (0.0%).
- Deterministic audit sample: **120** rows
  ({'news_media': 60, 'primary_document': 60}).
- Sample rows backed by an explicitly manual canonical timestamp: **0**.
- High-confidence news-to-primary pairs: **0**.

`published_at` is an article/document publication timestamp. The audit never treats a
past-tense headline as proof of an earlier event, and it never copies `published_at`
into `event_at`. Consequently, headline-earlier flags and estimated lags are marked
unavailable when canonical evidence is absent.

## Lag by source class

Percentages above thresholds use only rows with a nonnegative, evidence-backed lag;
coverage is shown separately so missing timestamps cannot look like zero lag.

| Source class | sample n | event_at n (coverage) | median min | p75 min | p90 min | >5m % | >15m % | >1h % | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| news_media | 60 | 0 (0.0%) | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |
| primary_document | 60 | 0 (0.0%) | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |

## Reaction start bias

Eligible comparisons require a news-media row with a nonnegative `event_at` lag and
stored **high** event-time confidence. Returns use the Reaction V2 rule: first full
minute after each anchor, open to open. A missing pair remains unavailable.

| Horizon | eligible pairs | complete pairs | mean article-primary delta (pp) | status |
|---|---:|---:|---:|---|
| 1m | 0 | 0 | unavailable | unavailable |
| 5m | 0 | 0 | unavailable | unavailable |
| 15m | 0 | 0 | unavailable | unavailable |
| 1h | 0 | 0 | unavailable | unavailable |
| 4h | 0 | 0 | unavailable | unavailable |
| 24h | 0 | 0 | unavailable | unavailable |

## Contextual market-move evidence

The prior Stage 13A market diagnostic analyzed **6,851** ETH news events and flagged **28.39%** at its 0.10% pre-move threshold (`PUBLISHED_AT_OFTEN_LAGS_MARKET_MOVE`). The separate Stage 13.5 publication-delay table reports **34.67%** under its own classification. But `pre_primary_source_found` is **0 of 6,851**, so neither rate is a canonical event-time lag or a paired-anchor reaction delta.

These diagnostics support concern about reaction-start bias, but cannot provide the
required median/p75/p90 lag or paired-anchor effect size.

## Decision gate

**B - plan Reaction V3 with a canonical event timestamp.** Do not build or migrate V3
in this task, and leave Reaction V2 unchanged. Evidence for the exact bias magnitude
is **insufficient**. Exact canonical lag and reaction deltas remain unavailable. However, zero canonical coverage plus a material prior pre-publication-move subset make Reaction V2 insufficient for claims about reaction from the event itself.

V3 prerequisite: Populate a separately reviewed canonical timestamp set, link news articles to primary announcements, then rerun lag and reaction-anchor comparisons before a V3 decision.
