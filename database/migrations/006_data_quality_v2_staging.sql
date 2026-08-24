-- Data Quality V2 metadata only. Review and apply to staging before production.
-- This migration does not overwrite V1 reaction values or delete any event.

BEGIN;

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS record_type text NOT NULL DEFAULT 'other'
        CHECK (record_type IN ('news_article', 'regulatory_filing', 'official_announcement', 'github_commit', 'protocol_release', 'research', 'other')),
    ADD COLUMN IF NOT EXISTS story_id text NULL,
    ADD COLUMN IF NOT EXISTS captured_title text NULL,
    ADD COLUMN IF NOT EXISTS current_source_title text NULL,
    ADD COLUMN IF NOT EXISTS display_title text NULL,
    ADD COLUMN IF NOT EXISTS source_type text NULL CHECK (source_type IS NULL OR source_type IN ('primary', 'publisher', 'other')),
    ADD COLUMN IF NOT EXISTS source_name text NULL,
    ADD COLUMN IF NOT EXISTS capture_method text NULL,
    ADD COLUMN IF NOT EXISTS publication_time_source text NULL,
    ADD COLUMN IF NOT EXISTS publication_time_confidence text NULL
        CHECK (publication_time_confidence IS NULL OR publication_time_confidence IN ('high', 'medium', 'low', 'unverified')),
    ADD COLUMN IF NOT EXISTS publication_time_verified_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS event_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS event_time_source text NULL,
    ADD COLUMN IF NOT EXISTS event_time_confidence text NULL
        CHECK (event_time_confidence IS NULL OR event_time_confidence IN ('high', 'medium', 'low')),
    ADD COLUMN IF NOT EXISTS primary_asset_confidence text NULL
        CHECK (primary_asset_confidence IS NULL OR primary_asset_confidence IN ('high', 'medium', 'low', 'not_assigned')),
    ADD COLUMN IF NOT EXISTS source_http_status text NULL,
    ADD COLUMN IF NOT EXISTS source_final_url text NULL,
    ADD COLUMN IF NOT EXISTS source_verified_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS quality_status text NOT NULL DEFAULT 'accepted'
        CHECK (quality_status IN ('verified', 'accepted', 'needs_review', 'rejected')),
    ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS dataset_version integer NOT NULL DEFAULT 2 CHECK (dataset_version > 0),
    ADD COLUMN IF NOT EXISTS dataset_release text NOT NULL DEFAULT '2026-08-data-quality-v2',
    ADD COLUMN IF NOT EXISTS btc_reaction_quality text NULL,
    ADD COLUMN IF NOT EXISTS eth_reaction_quality text NULL,
    ADD COLUMN IF NOT EXISTS sol_reaction_quality text NULL,
    ADD COLUMN IF NOT EXISTS search_document_v2 tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
        || setweight(to_tsvector('english'::regconfig, coalesce(current_source_title, '')), 'A')
        || setweight(to_tsvector('simple'::regconfig, coalesce(source, '')), 'B')
        || setweight(to_tsvector('english'::regconfig, coalesce(category, '')), 'B')
        || setweight(to_tsvector('simple'::regconfig, coalesce(record_type, '')), 'B')
        || setweight(
            to_tsvector(
                'simple'::regconfig,
                (CASE WHEN related_assets @> ARRAY['BTC']::text[] THEN 'BTC ' ELSE '' END)
                || (CASE WHEN related_assets @> ARRAY['ETH']::text[] THEN 'ETH ' ELSE '' END)
                || (CASE WHEN related_assets @> ARRAY['SOL']::text[] THEN 'SOL' ELSE '' END)
            ),
            'B'
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_events_story_id ON public.events (story_id) WHERE story_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_events_record_type ON public.events (record_type);
CREATE INDEX IF NOT EXISTS ix_events_quality_public ON public.events (quality_status, published_at DESC) WHERE is_public;
CREATE INDEX IF NOT EXISTS ix_events_search_document_v2_gin ON public.events USING gin (search_document_v2);

COMMENT ON COLUMN public.events.story_id IS 'Conservative cluster identifier; multiple articles may describe one underlying story.';
COMMENT ON COLUMN public.events.event_at IS 'Explicit underlying event time only; never inferred merely from publication time.';
COMMENT ON COLUMN public.events.quality_status IS 'Data Quality V2 review state; rejected records are retained, not physically deleted.';
COMMENT ON COLUMN public.events.search_document_v2 IS 'Metadata-only search document; copyrighted article bodies are excluded.';

COMMIT;
