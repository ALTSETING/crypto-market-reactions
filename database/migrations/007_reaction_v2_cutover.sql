-- Reaction V2 cutover metadata. Apply in the same transaction as the V2 data update.
-- No RLS, identity, source, classification, semantic, or SEO fields are changed.

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS btc_reaction_quality text NULL
        CHECK (btc_reaction_quality IS NULL OR btc_reaction_quality IN ('raw_verified_v2', 'partial_raw_verified_v2', 'missing_market_data', 'excluded_invalid_candle', 'legacy_v1')),
    ADD COLUMN IF NOT EXISTS btc_reaction_missing_reason jsonb NULL,
    ADD COLUMN IF NOT EXISTS eth_reaction_quality text NULL
        CHECK (eth_reaction_quality IS NULL OR eth_reaction_quality IN ('raw_verified_v2', 'partial_raw_verified_v2', 'missing_market_data', 'excluded_invalid_candle', 'legacy_v1')),
    ADD COLUMN IF NOT EXISTS eth_reaction_missing_reason jsonb NULL,
    ADD COLUMN IF NOT EXISTS sol_reaction_quality text NULL
        CHECK (sol_reaction_quality IS NULL OR sol_reaction_quality IN ('raw_verified_v2', 'partial_raw_verified_v2', 'missing_market_data', 'excluded_invalid_candle', 'legacy_v1')),
    ADD COLUMN IF NOT EXISTS sol_reaction_missing_reason jsonb NULL;

COMMENT ON COLUMN public.events.btc_reaction_quality IS 'Reproducibility status for BTC reaction fields.';
COMMENT ON COLUMN public.events.eth_reaction_quality IS 'Reproducibility status for ETH reaction fields.';
COMMENT ON COLUMN public.events.sol_reaction_quality IS 'Reproducibility status for SOL reaction fields.';
COMMENT ON COLUMN public.events.btc_reaction_missing_reason IS 'Per-horizon internal missing-data reasons; not selected by public list/detail APIs.';
COMMENT ON COLUMN public.events.eth_reaction_missing_reason IS 'Per-horizon internal missing-data reasons; not selected by public list/detail APIs.';
COMMENT ON COLUMN public.events.sol_reaction_missing_reason IS 'Per-horizon internal missing-data reasons; not selected by public list/detail APIs.';
