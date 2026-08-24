-- Idempotent DZ14 schema/metadata rollback. Every pre-existing production
-- column, including legacy record_type/source_type and Reaction V2, is untouched.

BEGIN;

LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE;

DROP INDEX IF EXISTS public.ix_events_source_class_v2_published_at;

ALTER TABLE public.events
    DROP COLUMN IF EXISTS source_class_v2,
    DROP COLUMN IF EXISTS document_class_v2,
    DROP COLUMN IF EXISTS source_class_confidence_v2,
    DROP COLUMN IF EXISTS source_classification_version;

COMMIT;
