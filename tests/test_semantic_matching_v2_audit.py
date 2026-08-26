import json
from collections import Counter
from pathlib import Path

from scripts.quality.build_semantic_matching_v2_golden import CURATED_IDS
from scripts.quality.semantic_matching_v2_audit import (
    DEFAULT_GOLDEN,
    EXPECTED_BUCKETS,
    evaluate,
    legacy_predictions,
    load_golden,
    load_predictions,
)


ROOT = Path(__file__).parents[1]
PREDICTIONS = ROOT / "reports/semantic_matching_v2/candidate_predictions.jsonl"
REPORT = ROOT / "reports/semantic_matching_v2/semantic_quality_audit.json"


def test_real_production_golden_is_fixed_unique_and_exactly_150_rows():
    rows = load_golden(DEFAULT_GOLDEN)

    assert len(rows) == 150
    assert Counter(row.audit_bucket for row in rows) == Counter(EXPECTED_BUCKETS)
    assert all(row.event_id.startswith(("bf3-", "evt18-")) for row in rows)
    assert all(row.provenance == "production_readonly_manual_curation_2026-08-26" for row in rows)
    assert not any("representative-" in row.event_id for row in rows)
    assert sum(len(ids) for ids in CURATED_IDS.values()) == 150


def test_candidate_passes_every_quality_gate_and_improves_on_frozen_v1():
    rows = load_golden(DEFAULT_GOLDEN)
    candidate = evaluate(rows, load_predictions(PREDICTIONS))
    legacy = evaluate(rows, legacy_predictions(rows))

    assert candidate["passed"]
    assert all(candidate["targets"].values())
    assert candidate["overall"]["f1"] > legacy["overall"]["f1"]


def test_production_report_has_30_independent_math_checks_and_no_mutation():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    production = report["production"]

    assert production["production_writes"] == "NO"
    assert production["reaction_values_recalculated"] == "NO"
    assert production["old_339_confirmed"] is True
    assert production["independent_math_verification"]["cases"] >= 30
    assert production["independent_math_verification"]["tolerance"] == 1e-9
    assert production["independent_math_verification"]["mismatch_count"] == 0


def test_audit_queries_are_bounded_read_only_and_builder_does_not_select_from_candidate():
    audit_source = (ROOT / "scripts/quality/semantic_matching_v2_audit.py").read_text(encoding="utf-8").upper()
    builder_source = (ROOT / "scripts/quality/build_semantic_matching_v2_golden.py").read_text(encoding="utf-8").lower()

    for statement in ("UPDATE PUBLIC.EVENTS", "DELETE FROM PUBLIC.EVENTS", "INSERT INTO PUBLIC.EVENTS"):
        assert statement not in audit_source
    assert "READONLY=TRUE" in audit_source.replace(" ", "")
    assert "MAX_ROWS = 10_000" in audit_source
    assert "LIMIT %S" in audit_source
    assert "candidate_predictions" not in builder_source
