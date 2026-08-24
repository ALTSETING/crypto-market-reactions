from scripts.quality.build_source_classification_v2 import (
    MEDIUM_CONFIDENCE_EVENT_IDS,
    VERSION,
    classify,
    mapping_sha256,
)


def test_classifier_uses_stable_identity_url_and_provenance_only():
    media = classify(
        "stable-event", "https://www.coindesk.com/markets/example", "coindesk"
    )
    filing = classify(
        "stable-filing", "https://www.sec.gov/Archives/edgar/data/1/x", "sec"
    )
    release = classify(
        "stable-release",
        "https://github.com/ethereum/go-ethereum/releases/tag/v1.2.3",
        "eth_github",
    )
    assert (media.source_class_v2, media.document_class_v2) == (
        "news_media",
        "news_article",
    )
    assert (filing.source_class_v2, filing.document_class_v2) == (
        "primary_document",
        "regulatory_filing",
    )
    assert (release.source_class_v2, release.document_class_v2) == (
        "official_announcement",
        "protocol_announcement",
    )


def test_medium_confidence_is_frozen_by_event_identity_not_legacy_metadata():
    event_id = next(iter(MEDIUM_CONFIDENCE_EVENT_IDS))
    decision = classify(event_id, "https://decrypt.co/example", "decrypt")
    assert decision.source_class_confidence_v2 == "medium"
    assert len(MEDIUM_CONFIDENCE_EVENT_IDS) == 107


def test_mapping_hash_is_order_independent():
    import pandas as pd

    rows = pd.DataFrame(
        [
            {
                "event_id": "b",
                "source_class_v2": "news_media",
                "document_class_v2": "news_article",
                "source_class_confidence_v2": "high",
                "source_classification_version": VERSION,
            },
            {
                "event_id": "a",
                "source_class_v2": "primary_document",
                "document_class_v2": "regulatory_filing",
                "source_class_confidence_v2": "high",
                "source_classification_version": VERSION,
            },
        ]
    )
    assert mapping_sha256(rows) == mapping_sha256(rows.iloc[::-1])
