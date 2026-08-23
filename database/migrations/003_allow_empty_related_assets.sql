-- General crypto events may be relevant without evidence for a supported asset.

BEGIN;

ALTER TABLE public.events
    DROP CONSTRAINT IF EXISTS events_related_assets_check;

ALTER TABLE public.events
    ADD CONSTRAINT events_related_assets_check
    CHECK (related_assets <@ ARRAY['BTC', 'ETH', 'SOL']::text[]);

COMMENT ON COLUMN public.events.related_assets IS
    'Explicitly evidenced subset of BTC, ETH and SOL; may be empty for market-wide crypto events.';

COMMIT;
