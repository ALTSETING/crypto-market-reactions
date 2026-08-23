-- Server-side average reaction sorting for the website event archive.
-- NULL horizons are ignored, zero is included, and at least three values are required.

BEGIN;

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS btc_average_reaction double precision
    GENERATED ALWAYS AS (
        CASE
            WHEN num_nonnulls(btc_1m, btc_5m, btc_15m, btc_1h, btc_4h, btc_24h) >= 3
            THEN (
                coalesce(btc_1m, 0) + coalesce(btc_5m, 0) + coalesce(btc_15m, 0)
                + coalesce(btc_1h, 0) + coalesce(btc_4h, 0) + coalesce(btc_24h, 0)
            ) / num_nonnulls(btc_1m, btc_5m, btc_15m, btc_1h, btc_4h, btc_24h)
            ELSE NULL
        END
    ) STORED,
    ADD COLUMN IF NOT EXISTS eth_average_reaction double precision
    GENERATED ALWAYS AS (
        CASE
            WHEN num_nonnulls(eth_1m, eth_5m, eth_15m, eth_1h, eth_4h, eth_24h) >= 3
            THEN (
                coalesce(eth_1m, 0) + coalesce(eth_5m, 0) + coalesce(eth_15m, 0)
                + coalesce(eth_1h, 0) + coalesce(eth_4h, 0) + coalesce(eth_24h, 0)
            ) / num_nonnulls(eth_1m, eth_5m, eth_15m, eth_1h, eth_4h, eth_24h)
            ELSE NULL
        END
    ) STORED,
    ADD COLUMN IF NOT EXISTS sol_average_reaction double precision
    GENERATED ALWAYS AS (
        CASE
            WHEN num_nonnulls(sol_1m, sol_5m, sol_15m, sol_1h, sol_4h, sol_24h) >= 3
            THEN (
                coalesce(sol_1m, 0) + coalesce(sol_5m, 0) + coalesce(sol_15m, 0)
                + coalesce(sol_1h, 0) + coalesce(sol_4h, 0) + coalesce(sol_24h, 0)
            ) / num_nonnulls(sol_1m, sol_5m, sol_15m, sol_1h, sol_4h, sol_24h)
            ELSE NULL
        END
    ) STORED;

-- Three partial indexes cover the only new computed sort keys. The small table does
-- not justify another 18 indexes for the existing horizon columns.
CREATE INDEX IF NOT EXISTS ix_events_btc_average_reaction
    ON public.events (btc_average_reaction)
    WHERE btc_average_reaction IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_events_eth_average_reaction
    ON public.events (eth_average_reaction)
    WHERE eth_average_reaction IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_events_sol_average_reaction
    ON public.events (sol_average_reaction)
    WHERE sol_average_reaction IS NOT NULL;

COMMENT ON COLUMN public.events.btc_average_reaction IS
    'Mean of available BTC percentage returns across 1m, 5m, 15m, 1h, 4h and 24h; NULL below three values.';
COMMENT ON COLUMN public.events.eth_average_reaction IS
    'Mean of available ETH percentage returns across 1m, 5m, 15m, 1h, 4h and 24h; NULL below three values.';
COMMENT ON COLUMN public.events.sol_average_reaction IS
    'Mean of available SOL percentage returns across 1m, 5m, 15m, 1h, 4h and 24h; NULL below three values.';

COMMIT;
