from pathlib import Path

import pandas as pd
import pytest

from scripts.quality.semantic_timestamp_audit import (
    MAX_SCAN_ROWS,
    NARROWER_SCOPE_MESSAGE,
    anchored_return,
    assess_timestamps,
    build_summary,
    lag_summary,
    load_contextual_bias_evidence,
    reaction_bias,
    select_stratified_sample,
)


def _events(per_class: int = 70) -> pd.DataFrame:
    rows = []
    for source_class in ("primary_document", "news_media"):
        for number in range(per_class):
            rows.append(
                {
                    "event_id": f"{source_class}-{number:03d}",
                    "title": f"event {number}",
                    "source": "sec" if source_class == "primary_document" else "coindesk",
                    "source_url": "https://example.test/event",
                    "source_class_v2": source_class,
                    "document_class_v2": "regulatory_filing" if source_class == "primary_document" else "news_article",
                    "published_at": "2025-01-01T10:00:30Z",
                    "primary_asset": "ETH",
                    "publication_time_source": "publisher_metadata",
                    "publication_time_confidence": "high",
                    "event_at": None,
                    "event_time_source": None,
                    "event_time_confidence": None,
                }
            )
    return pd.DataFrame(rows)


def test_sample_is_balanced_stable_and_at_least_one_hundred():
    events = _events()
    first = select_stratified_sample(events)
    second = select_stratified_sample(events.sample(frac=1, random_state=42))

    assert len(first) == 120
    assert first.source_class_v2.value_counts().to_dict() == {
        "news_media": 60,
        "primary_document": 60,
    }
    assert set(first.event_id) == set(second.event_id)


def test_missing_event_at_is_low_confidence_and_never_inferred_from_source_class():
    events = _events(per_class=1)
    audit = assess_timestamps(events)
    primary = audit.loc[audit.source_class_v2.eq("primary_document")].iloc[0]
    media = audit.loc[audit.source_class_v2.eq("news_media")].iloc[0]

    assert bool(primary.is_primary_announcement_document)
    assert pd.isna(primary.primary_announcement_at)
    assert pd.isna(primary.headline_describes_earlier_event)
    assert primary.timing_confidence == "low"
    assert not bool(primary.lag_available)
    assert not bool(media.primary_pair_eligible)


def test_lag_metrics_exclude_missing_and_negative_values_from_percentages():
    events = _events(per_class=2)
    events.loc[events.source_class_v2.eq("news_media"), "event_at"] = [
        "2025-01-01T09:50:30Z",
        "2025-01-01T09:40:30Z",
    ]
    events.loc[events.source_class_v2.eq("news_media"), "event_time_confidence"] = "high"
    audit = assess_timestamps(events)
    metrics = lag_summary(audit).set_index("source_class")

    assert metrics.loc["news_media", "median_lag_minutes"] == pytest.approx(15.0)
    assert metrics.loc["news_media", "p75_lag_minutes"] == pytest.approx(17.5)
    assert metrics.loc["news_media", "pct_lag_gt_5m"] == pytest.approx(100.0)
    assert metrics.loc["news_media", "pct_lag_gt_15m"] == pytest.approx(50.0)
    assert metrics.loc["primary_document", "status"] == "unavailable"


def test_reaction_comparison_uses_first_full_minute_after_each_anchor():
    event = _events(per_class=1).loc[lambda x: x.source_class_v2.eq("news_media")].copy()
    event["event_at"] = "2025-01-01T09:50:30Z"
    event["event_time_source"] = "manual_primary_pair"
    event["event_time_confidence"] = "high"
    audit = assess_timestamps(event)
    event_id = audit.iloc[0].event_id
    candles = pd.DataFrame(
        [
            {"canonical_event_id": event_id, "asset": "ETH", "open_time": "2025-01-01T09:51:00Z", "open": 100.0},
            {"canonical_event_id": event_id, "asset": "ETH", "open_time": "2025-01-01T09:52:00Z", "open": 110.0},
            {"canonical_event_id": event_id, "asset": "ETH", "open_time": "2025-01-01T10:01:00Z", "open": 100.0},
            {"canonical_event_id": event_id, "asset": "ETH", "open_time": "2025-01-01T10:02:00Z", "open": 90.0},
        ]
    )

    assert anchored_return(candles, pd.Timestamp("2025-01-01T09:50:30Z"), 1) == pytest.approx(10.0)
    summary, detail = reaction_bias(audit, candles)
    one_minute = summary.set_index("horizon").loc["1m"]
    pair = detail.loc[detail.horizon.eq("1m")].iloc[0]

    assert one_minute.complete_pair_n == 1
    assert one_minute.mean_delta_pp == pytest.approx(-20.0)
    assert one_minute.direction_flip_n == 1
    assert pair.primary_anchor_return_pct == pytest.approx(10.0)
    assert pair.article_anchor_return_pct == pytest.approx(-10.0)


def test_audit_source_contains_no_production_dml():
    source = (
        Path(__file__).parents[1] / "scripts/quality/semantic_timestamp_audit.py"
    ).read_text(encoding="utf-8").upper()
    for statement in ("UPDATE PUBLIC.EVENTS", "DELETE FROM PUBLIC.EVENTS", "INSERT INTO PUBLIC.EVENTS"):
        assert statement not in source
    assert "READONLY=TRUE" in source.replace(" ", "")
    assert MAX_SCAN_ROWS == 10_000
    assert "LIMIT %S" in source
    assert NARROWER_SCOPE_MESSAGE == "Try a narrower asset, topic or date range."


def test_decision_gate_uses_context_without_claiming_canonical_pairs():
    events = _events(per_class=1)
    audit = assess_timestamps(events)
    lag = lag_summary(audit)
    candles = pd.DataFrame(columns=["canonical_event_id", "asset", "open_time", "open"])
    bias, _ = reaction_bias(audit, candles)
    context = load_contextual_bias_evidence()
    summary = build_summary(events, audit, lag, bias, context)

    assert context["stage13a_events_analyzed"] == 6851
    assert context["stage13a_late_publication_proxy_rate_0_10pct"] == pytest.approx(
        0.2839001605605021
    )
    assert context["stage135_pre_primary_source_found_n"] == 0
    assert context["canonical_pair_usable"] is False
    assert summary["decision_gate"] == "B"
    assert summary["evidence_status"] == "insufficient"
