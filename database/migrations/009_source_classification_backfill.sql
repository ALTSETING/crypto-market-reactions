-- Production-specific idempotent backfill for the frozen 9,073-event DZ13
-- event/domain/provenance mapping. Only the four independent V2 columns are set.

BEGIN;

LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    v_total bigint;
    v_verified_methodology bigint;
BEGIN
    SELECT
        count(*),
        count(*) FILTER (
            WHERE reaction_methodology = 'reaction_v2_next_full_minute_open_to_open'
        )
    INTO v_total, v_verified_methodology
    FROM public.events;

    IF (v_total, v_verified_methodology)
       IS DISTINCT FROM (9073::bigint, 9073::bigint) THEN
        RAISE EXCEPTION
            'DZ14 reaction methodology precondition failed: total=%, verified=%',
            v_total, v_verified_methodology;
    END IF;
END
$$;

CREATE TEMP TABLE IF NOT EXISTS dz14_medium_confidence_ids (
    event_id text PRIMARY KEY
) ON COMMIT DROP;

TRUNCATE dz14_medium_confidence_ids;

INSERT INTO dz14_medium_confidence_ids(event_id) VALUES
    ('evt18-016c0710f2ac9b4fb513'),
    ('evt18-01c1050db8864fc00b51'),
    ('evt18-05580c290ff2056ce545'),
    ('evt18-0ec666d8b9f0c2867661'),
    ('evt18-139c64254bec7d9910f2'),
    ('evt18-13b6195163f4416d544e'),
    ('evt18-16323e959d16f8f74e51'),
    ('evt18-1785d4f629411ad6d5e0'),
    ('evt18-2245db3794c29aecc174'),
    ('evt18-286df48f73b457ad00ae'),
    ('evt18-2bb2aab1e007864965a0'),
    ('evt18-35148849d3c8400c46e8'),
    ('evt18-363c20806447ac41f573'),
    ('evt18-36cda2e851578d5b469a'),
    ('evt18-380e485f1887e5321282'),
    ('evt18-3c6e6112be42e0f407f6'),
    ('evt18-3daf6ae9f14b6dfe0ef2'),
    ('evt18-4b6cfb68a5f534d6b6ab'),
    ('evt18-4d106e37b84a11511ff0'),
    ('evt18-4dd4ae11be7382787bc4'),
    ('evt18-50f670a6b9eaed982254'),
    ('evt18-54dbff7d61eccf5f66d1'),
    ('evt18-5604a0f0875cfcf6f909'),
    ('evt18-567a5be9f65506cc245b'),
    ('evt18-56d4f4a20dc200c157a7'),
    ('evt18-576ae912227240792b79'),
    ('evt18-5a80e3a98b84568a027b'),
    ('evt18-5c42ae1721db977bd203'),
    ('evt18-5c6a8319d3f2370effa3'),
    ('evt18-61989f2aeced9c6c908d'),
    ('evt18-6352dc7977d02c0b462d'),
    ('evt18-675b307bcd0d3a9560c6'),
    ('evt18-6a0a1e671222f047b05e'),
    ('evt18-6a81f40ece910b59e459'),
    ('evt18-6c3001180ae12aa7eace'),
    ('evt18-6d680df320c6090f3ca6'),
    ('evt18-6de03d7c7f02f9f905d7'),
    ('evt18-6ed3847be19da3e3ae6e'),
    ('evt18-7048065c2c3ff8e321cf'),
    ('evt18-723010dbb4de11c47539'),
    ('evt18-731e73cfa1b73b344c54'),
    ('evt18-7409451d30dd7d25fe30'),
    ('evt18-7790ffb9ad1fca9a2ed0'),
    ('evt18-7aab790aad0b4dc9f850'),
    ('evt18-7b32a649c6375c6aaef2'),
    ('evt18-7c6582223ef4b6fdd3ad'),
    ('evt18-7e1cade8508fa2e96628'),
    ('evt18-7ed8e8d36a010146156c'),
    ('evt18-852b96f2ff2549061bae'),
    ('evt18-8708c63572c47739fa1e'),
    ('evt18-8ad2b5dda16b6cde250c'),
    ('evt18-8d6f2c41758f0004d7d9'),
    ('evt18-8e1205acbe3b0201af91'),
    ('evt18-8e9149c0bc66a89fde0e'),
    ('evt18-8f3a0488093a790d855a'),
    ('evt18-8f760bdbb15bdf120381'),
    ('evt18-9c625387064e657c1472'),
    ('evt18-9c9b8a0572950dcfdcca'),
    ('evt18-9e2326bb419734d4a675'),
    ('evt18-9e337de263a293020f69'),
    ('evt18-a0de824f64c5ddac9f65'),
    ('evt18-a4227f5429742fbdbb8b'),
    ('evt18-a4458b698d37f6bfabdf'),
    ('evt18-a4ad65a0cc963b15290e'),
    ('evt18-a5200aa1f9b9e40e5df7'),
    ('evt18-a870568067407c9bbcc9'),
    ('evt18-a91754a2b280fee038b2'),
    ('evt18-ac058cc7d026872aa93f'),
    ('evt18-aeaaeb6a37f67f7c7c6a'),
    ('evt18-b0bf2ba6855b7f63fc38'),
    ('evt18-b12208168e88f6a8a416'),
    ('evt18-b1c74b9ddd6ac518d36f'),
    ('evt18-b58fcc78bc5810226bc7'),
    ('evt18-b78d8d8aee0b588ccdc0'),
    ('evt18-b91b7308705760f9c89d'),
    ('evt18-be75357670b98aa5bc04'),
    ('evt18-bf96d28e2985c64a1a7b'),
    ('evt18-c12b2984e631b21a435b'),
    ('evt18-c1e6f7bebb4b197e9da3'),
    ('evt18-c29caddfcc3cce2e73ff'),
    ('evt18-c2a3bdc7c5c12c13fead'),
    ('evt18-c34957bd4e6d02130ecd'),
    ('evt18-c45d9837e89599a630fe'),
    ('evt18-c689813dc7400d18691b'),
    ('evt18-c6eb3e81cf3c2f9efdbb'),
    ('evt18-c962a6df62672c5f9ce7'),
    ('evt18-cb75725bc2cf32bfc8cb'),
    ('evt18-d5d9fd68ba962ef61608'),
    ('evt18-d9f734d3050f2e5ad806'),
    ('evt18-e180439a2d9db28454ea'),
    ('evt18-e373f8064541750bab12'),
    ('evt18-e63cd1c1f47a486f8436'),
    ('evt18-e75a737cf58d77d5f35f'),
    ('evt18-e762fd29fbfd81657bd0'),
    ('evt18-e954221f26ddcc18d042'),
    ('evt18-e9f733cfaa6c2d581a64'),
    ('evt18-ea583cf92c3583c4866d'),
    ('evt18-ec4c0c7dceaa891d8123'),
    ('evt18-ed835e9d1001d01e0e58'),
    ('evt18-ee632082eff900aac793'),
    ('evt18-ee6c19a909b1e02475f9'),
    ('evt18-f13c3c91cf1d7b1f9d3f'),
    ('evt18-f3f4dab31568d3e6e9da'),
    ('evt18-f6344efa1d2227aae920'),
    ('evt18-f98af883fa9bf95b2597'),
    ('evt18-fbef7407f28d6b304df6'),
    ('evt18-fef98ba92fb515031056');

DO $$
BEGIN
    IF (SELECT count(*) FROM dz14_medium_confidence_ids) <> 107 THEN
        RAISE EXCEPTION 'DZ14 frozen medium-confidence ID set is not 107 rows';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM dz14_medium_confidence_ids frozen
        LEFT JOIN public.events event USING (event_id)
        WHERE event.event_id IS NULL
    ) THEN
        RAISE EXCEPTION 'DZ14 frozen medium-confidence ID is absent from production';
    END IF;
END
$$;

WITH classified AS (
    SELECT
        event.event_id,
        CASE
            WHEN lower(event.source_url) ~ '^https?://(www\.)?(coindesk\.com|decrypt\.co|cointelegraph\.com)(/|$)'
                THEN 'news_media'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?sec\.gov(/|$)'
                THEN 'primary_document'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?github\.com/.+/releases/'
                 AND lower(event.source) IN ('btc_github', 'eth_github', 'ethereum_github', 'sol_github')
                THEN 'official_announcement'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?blog\.ethereum\.org(/|$)'
                THEN 'official_announcement'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?github\.com(/|$)'
                 AND lower(event.source) IN ('btc_github', 'eth_github', 'ethereum_github', 'sol_github')
                THEN 'primary_document'
            ELSE 'unknown'
        END AS new_source_class,
        CASE
            WHEN lower(event.source_url) ~ '^https?://(www\.)?(coindesk\.com|decrypt\.co|cointelegraph\.com)(/|$)'
                THEN 'news_article'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?sec\.gov(/|$)'
                THEN 'regulatory_filing'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?github\.com/.+/releases/'
                 AND lower(event.source) IN ('btc_github', 'eth_github', 'ethereum_github', 'sol_github')
                THEN 'protocol_announcement'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?blog\.ethereum\.org(/|$)'
                THEN 'protocol_announcement'
            ELSE 'other'
        END AS new_document_class,
        CASE
            WHEN frozen.event_id IS NOT NULL
                 AND lower(event.source_url) ~ '^https?://(www\.)?(coindesk\.com|decrypt\.co|cointelegraph\.com)(/|$)'
                THEN 'medium'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?(coindesk\.com|decrypt\.co|cointelegraph\.com|sec\.gov|blog\.ethereum\.org)(/|$)'
                THEN 'high'
            WHEN lower(event.source_url) ~ '^https?://(www\.)?github\.com(/|$)'
                 AND lower(event.source) IN ('btc_github', 'eth_github', 'ethereum_github', 'sol_github')
                THEN 'high'
            ELSE 'low'
        END AS new_confidence
    FROM public.events event
    LEFT JOIN dz14_medium_confidence_ids frozen USING (event_id)
), updated AS (
    UPDATE public.events AS event
    SET
        source_class_v2 = classified.new_source_class,
        document_class_v2 = classified.new_document_class,
        source_class_confidence_v2 = classified.new_confidence,
        source_classification_version = 'dz13-source-class-v2'
    FROM classified
    WHERE event.event_id = classified.event_id
      AND (
          event.source_class_v2,
          event.document_class_v2,
          event.source_class_confidence_v2,
          event.source_classification_version
      ) IS DISTINCT FROM (
          classified.new_source_class,
          classified.new_document_class,
          classified.new_confidence,
          'dz13-source-class-v2'
      )
    RETURNING event.event_id
)
SELECT count(*) AS metadata_rows_changed FROM updated;

DO $$
DECLARE
    v_total bigint;
    v_news bigint;
    v_primary bigint;
    v_official bigint;
    v_unknown bigint;
    v_high bigint;
    v_medium bigint;
    v_low bigint;
    v_news_documents bigint;
    v_regulatory_documents bigint;
    v_protocol_documents bigint;
    v_other_documents bigint;
    v_version bigint;
    v_medium_mapping_mismatches bigint;
BEGIN
    SELECT
        count(*),
        count(*) FILTER (WHERE source_class_v2 = 'news_media'),
        count(*) FILTER (WHERE source_class_v2 = 'primary_document'),
        count(*) FILTER (WHERE source_class_v2 = 'official_announcement'),
        count(*) FILTER (WHERE source_class_v2 = 'unknown'),
        count(*) FILTER (WHERE source_class_confidence_v2 = 'high'),
        count(*) FILTER (WHERE source_class_confidence_v2 = 'medium'),
        count(*) FILTER (WHERE source_class_confidence_v2 = 'low'),
        count(*) FILTER (WHERE document_class_v2 = 'news_article'),
        count(*) FILTER (WHERE document_class_v2 = 'regulatory_filing'),
        count(*) FILTER (WHERE document_class_v2 = 'protocol_announcement'),
        count(*) FILTER (WHERE document_class_v2 = 'other'),
        count(*) FILTER (WHERE source_classification_version = 'dz13-source-class-v2')
    INTO
        v_total, v_news, v_primary, v_official, v_unknown,
        v_high, v_medium, v_low,
        v_news_documents, v_regulatory_documents,
        v_protocol_documents, v_other_documents, v_version
    FROM public.events;

    SELECT count(*)
    INTO v_medium_mapping_mismatches
    FROM public.events event
    FULL JOIN dz14_medium_confidence_ids frozen USING (event_id)
    WHERE (event.source_class_confidence_v2 = 'medium') IS DISTINCT FROM (frozen.event_id IS NOT NULL);

    IF (
        v_total, v_news, v_primary, v_official, v_unknown,
        v_high, v_medium, v_low,
        v_news_documents, v_regulatory_documents,
        v_protocol_documents, v_other_documents,
        v_version, v_medium_mapping_mismatches
    ) IS DISTINCT FROM (
        9073::bigint, 8046::bigint, 736::bigint, 291::bigint, 0::bigint,
        8966::bigint, 107::bigint, 0::bigint,
        8046::bigint, 496::bigint, 291::bigint, 240::bigint,
        9073::bigint, 0::bigint
    ) THEN
        RAISE EXCEPTION
            'DZ14 classification mismatch: total=%, news=%, primary=%, official=%, unknown=%, high=%, medium=%, low=%, news_doc=%, regulatory_doc=%, protocol_doc=%, other_doc=%, version=%, medium_map=%',
            v_total, v_news, v_primary, v_official, v_unknown,
            v_high, v_medium, v_low,
            v_news_documents, v_regulatory_documents,
            v_protocol_documents, v_other_documents,
            v_version, v_medium_mapping_mismatches;
    END IF;
END
$$;

ALTER TABLE public.events
    ALTER COLUMN source_class_v2 SET NOT NULL,
    ALTER COLUMN document_class_v2 SET NOT NULL,
    ALTER COLUMN source_class_confidence_v2 SET NOT NULL,
    ALTER COLUMN source_classification_version SET NOT NULL;

COMMIT;
