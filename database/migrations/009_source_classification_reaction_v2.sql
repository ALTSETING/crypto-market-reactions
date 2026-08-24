-- DZ14 source-classification schema only. These V2 fields deliberately do not
-- reuse or alter the legacy record_type/source_type columns.

BEGIN;

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS source_class_v2 text NULL
        CHECK (
            source_class_v2 IS NULL OR source_class_v2 IN (
                'news_media', 'primary_document',
                'official_announcement', 'unknown'
            )
        ),
    ADD COLUMN IF NOT EXISTS document_class_v2 text NULL
        CHECK (
            document_class_v2 IS NULL OR document_class_v2 IN (
                'news_article', 'regulatory_filing', 'court_document',
                'government_release', 'company_press_release', 'exchange_notice',
                'protocol_announcement', 'other'
            )
        ),
    ADD COLUMN IF NOT EXISTS source_class_confidence_v2 text NULL
        CHECK (
            source_class_confidence_v2 IS NULL
            OR source_class_confidence_v2 IN ('high', 'medium', 'low')
        ),
    ADD COLUMN IF NOT EXISTS source_classification_version text NULL
        CHECK (
            source_classification_version IS NULL
            OR source_classification_version = 'dz13-source-class-v2'
        );

CREATE INDEX IF NOT EXISTS ix_events_source_class_v2_published_at
    ON public.events (source_class_v2, published_at DESC);

COMMENT ON COLUMN public.events.source_class_v2 IS
    'User-facing source class from frozen deterministic DZ13 event/domain/provenance rules.';
COMMENT ON COLUMN public.events.document_class_v2 IS
    'Document class from frozen deterministic DZ13 event/domain/provenance rules.';
COMMENT ON COLUMN public.events.source_class_confidence_v2 IS
    'Confidence from the frozen DZ13 event-level mapping; legacy metadata is not an input.';
COMMENT ON COLUMN public.events.source_classification_version IS
    'Version of the independent source-classification mapping.';

COMMIT;
