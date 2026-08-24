-- Run after import with: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/checks/verify_events.sql

SELECT
    count(*) AS total_rows,
    count(DISTINCT event_id) AS unique_event_id,
    count(DISTINCT slug) AS unique_slug,
    count(*) = count(DISTINCT event_id) AS event_id_unique_pass,
    count(*) = count(DISTINCT slug) AS slug_unique_pass
FROM public.events;

SELECT source_url, count(*) AS occurrences
FROM public.events
GROUP BY source_url
HAVING count(*) > 1
ORDER BY occurrences DESC, source_url;

SELECT
    count(*) FILTER (WHERE title IS NULL OR btrim(title) = '') AS missing_title,
    count(*) FILTER (WHERE published_at IS NULL) AS missing_published_at,
    count(*) FILTER (WHERE sentiment IS NULL) AS null_sentiment,
    count(*) FILTER (WHERE importance IS NULL) AS null_importance,
    min(published_at) AS min_published_at,
    max(published_at) AS max_published_at
FROM public.events;

SELECT
    count(*) FILTER (WHERE btc_1m IS NOT NULL AND btc_5m IS NOT NULL
        AND btc_15m IS NOT NULL AND btc_1h IS NOT NULL
        AND btc_4h IS NOT NULL AND btc_24h IS NOT NULL) AS btc_full_reaction_coverage,
    count(*) FILTER (WHERE eth_1m IS NOT NULL AND eth_5m IS NOT NULL
        AND eth_15m IS NOT NULL AND eth_1h IS NOT NULL
        AND eth_4h IS NOT NULL AND eth_24h IS NOT NULL) AS eth_full_reaction_coverage,
    count(*) FILTER (WHERE sol_1m IS NOT NULL AND sol_5m IS NOT NULL
        AND sol_15m IS NOT NULL AND sol_1h IS NOT NULL
        AND sol_4h IS NOT NULL AND sol_24h IS NOT NULL) AS sol_full_reaction_coverage
FROM public.events;

-- Compare coverage with the release manifest/report; no release size is hardcoded here.

-- Full-text search: "ethereum ETF".
SELECT event_id, slug, title, source, published_at,
       ts_rank(search_vector, websearch_to_tsquery('english', 'ethereum ETF')) AS rank
FROM public.events
WHERE search_vector @@ websearch_to_tsquery('english', 'ethereum ETF')
ORDER BY rank DESC, published_at DESC
LIMIT 25;

-- Filter by primary asset.
SELECT event_id, slug, title, published_at, eth_1h, eth_24h
FROM public.events
WHERE primary_asset = 'ETH'
ORDER BY published_at DESC
LIMIT 25;

-- Date range uses a half-open interval to avoid end-of-day ambiguity.
SELECT event_id, slug, title, source, published_at
FROM public.events
WHERE published_at >= timestamptz '2024-01-01 00:00:00+00'
  AND published_at <  timestamptz '2025-01-01 00:00:00+00'
ORDER BY published_at DESC;

-- Related-asset filter uses the GIN-indexed array operator.
SELECT event_id, slug, title, related_assets, published_at
FROM public.events
WHERE related_assets @> ARRAY['ETH']::text[]
ORDER BY published_at DESC
LIMIT 25;

-- Latest events.
SELECT event_id, slug, title, source, published_at
FROM public.events
ORDER BY published_at DESC
LIMIT 25;
