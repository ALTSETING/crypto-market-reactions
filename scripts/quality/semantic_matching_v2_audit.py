"""Independent, read-only quality audit for Semantic Event Matching V2.

The golden labels in ``datasets/semantic_matching_v2/golden_events.csv`` are
the oracle.  This module deliberately does not import or reproduce the V2
production matcher.  Candidate predictions are accepted as a small JSONL
interchange so that the server-side TypeScript classifier can be evaluated
without exposing database rows to an AI service.

Production mode performs one bounded SELECT in a read-only transaction.  It
never mutates event or Reaction V2 values.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = ROOT / "datasets" / "semantic_matching_v2" / "golden_events.jsonl"
DEFAULT_REPORT_JSON = ROOT / "reports" / "semantic_matching_v2" / "semantic_quality_audit.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "semantic_matching_v2" / "SEMANTIC_QUALITY_AUDIT.md"
TOLERANCE = 1e-9
MAX_ROWS = 10_000
LARGE_USD_THRESHOLD = 50_000_000

TOPICS = {
    "large_investment",
    "institutional_purchase",
    "institutional_selling",
    "etf",
    "sec",
    "hack",
}
ACTORS = {
    "company", "fund", "ETF", "institution", "government", "regulator",
    "exchange", "protocol", "investor", "whale", "unknown",
}
ACTIONS = {
    "buy", "sell", "invest", "divest", "fund", "raise", "acquire",
    "liquidate", "deposit", "withdraw", "approve", "reject", "file",
    "sue", "hack", "exploit", "list", "delist", "upgrade", "stake",
    "unstake", "unknown",
}
DIRECTIONS = {"inflow", "outflow", "neutral", "unknown"}
MAGNITUDES = {"small", "medium", "large", "major_unquantified", "unknown"}
ASSET_RELEVANCE = {"primary", "secondary", "none"}
EXPECTED_BUCKETS = {
    "large_investment": 30,
    "institutional_purchase": 20,
    "institutional_selling": 20,
    "etf": 20,
    "sec": 20,
    "hack": 20,
    "negative_control": 20,
}


@dataclass(frozen=True)
class GoldenEvent:
    id: str
    event_id: str
    provenance: str
    title: str
    assets: tuple[str, ...]
    primary_asset: str | None
    category: str
    asset: str
    audit_bucket: str
    relevant: bool
    asset_relevance: str
    actor_type: str
    action: str
    direction: str
    magnitude_class: str
    amount_usd: float | None
    expected_topic: str | None
    label_notes: str


def _optional_float(value: str | None) -> float | None:
    return None if value is None or not value.strip() else float(value)


def load_golden(path: Path = DEFAULT_GOLDEN) -> list[GoldenEvent]:
    rows: list[GoldenEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = set(GoldenEvent.__dataclass_fields__) - set(row)
            if missing:
                raise ValueError(f"golden line {line_number} missing fields: {sorted(missing)}")
            rows.append(GoldenEvent(
                id=str(row["id"]), event_id=str(row["event_id"]), provenance=str(row["provenance"]),
                title=str(row["title"]), assets=tuple(row["assets"]),
                primary_asset=str(row["primary_asset"]) if row["primary_asset"] is not None else None,
                category=str(row["category"]), asset=str(row["asset"]),
                audit_bucket=str(row["audit_bucket"]), relevant=bool(row["relevant"]),
                asset_relevance=str(row["asset_relevance"]), actor_type=str(row["actor_type"]),
                action=str(row["action"]), direction=str(row["direction"]),
                magnitude_class=str(row["magnitude_class"]),
                amount_usd=float(row["amount_usd"]) if row["amount_usd"] is not None else None,
                expected_topic=str(row["expected_topic"]) if row["expected_topic"] is not None else None,
                label_notes=str(row["label_notes"]),
            ))
    validate_golden(rows)
    return rows


def validate_golden(rows: Sequence[GoldenEvent]) -> None:
    if len(rows) < 150:
        raise ValueError(f"golden dataset must have at least 150 rows, found {len(rows)}")
    if len({row.id for row in rows}) != len(rows):
        raise ValueError("golden row ids must be unique")
    if len({row.event_id for row in rows}) != len(rows):
        raise ValueError("golden event ids must be unique")
    counts = Counter(row.audit_bucket for row in rows)
    if counts != Counter(EXPECTED_BUCKETS):
        raise ValueError(f"golden distribution mismatch: {dict(counts)}")
    for row in rows:
        if not row.title.strip() or not row.label_notes.strip():
            raise ValueError(f"{row.id}: title and manual label note are required")
        if row.asset not in {"BTC", "ETH", "SOL"} or row.asset not in row.assets:
            raise ValueError(f"{row.id}: audited asset must be a related BTC/ETH/SOL asset")
        if row.asset_relevance not in ASSET_RELEVANCE:
            raise ValueError(f"{row.id}: invalid asset relevance")
        if row.actor_type not in ACTORS or row.action not in ACTIONS:
            raise ValueError(f"{row.id}: non-allowlisted actor/action")
        if row.direction not in DIRECTIONS or row.magnitude_class not in MAGNITUDES:
            raise ValueError(f"{row.id}: invalid direction/magnitude")
        if row.relevant != (row.expected_topic is not None):
            raise ValueError(f"{row.id}: relevant and expected_topic disagree")
        if row.expected_topic is not None and row.expected_topic not in TOPICS:
            raise ValueError(f"{row.id}: invalid expected topic")


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            row_id = str(item.get("id", ""))
            if not row_id or row_id in predictions:
                raise ValueError(f"prediction line {line_number}: missing/duplicate id")
            raw_topics = item.get("topics", [item["topic"]] if item.get("topic") else [])
            topics = list(dict.fromkeys(raw_topics))
            if not set(topics) <= TOPICS:
                raise ValueError(f"prediction line {line_number}: non-allowlisted topic")
            normalized = dict(item)
            normalized["topics"] = topics
            predictions[row_id] = normalized
    return predictions


# This is the frozen V1 baseline under audit, not the V2 reference oracle.
_LEGACY_PATTERNS: Mapping[str, tuple[re.Pattern[str], ...]] = {
    "large_investment": tuple(re.compile(value, re.I) for value in (
        r"\binvest(?:s|ed|ing)\b", r"\binvestments?\b(?!\s+(?:gains?|returns?|products?|funds?|vehicles?)\b)",
        r"\bfunding\b(?!\s+(?:gap|shortfall|cuts?|pressure|concerns?|crisis|issues?|problems?|needs?)\b)",
        r"\bfunded\b", r"\brais(?:e|es|ed|ing)\b[^.]{0,40}\b(?:million|billion|round|capital|funding)\b",
        r"\b(?:purchase|purchases|purchased|buys|bought)\b", r"\bacqui(?:res?|red|sition|sitions)\b",
        r"treasury\s+(?:buy|buys|purchase|purchases)", r"institutional\s+(?:buy|buys|purchase|purchases)",
    )),
    "institutional_purchase": tuple(re.compile(value, re.I) for value in (
        r"\binstitutional\s+(?:buy|buys|buyer|purchase|purchases|purchased)\b",
        r"\btreasury\s+(?:buy|buys|purchase|purchases|purchased|reserve)\b",
    )),
    "etf": (re.compile(r"\bETFs?\b", re.I), re.compile(r"\bexchange[- ]traded\s+funds?\b", re.I)),
    "sec": (re.compile(r"\bSEC\b"), re.compile(r"\bSecurities\s+and\s+Exchange\s+Commission\b", re.I)),
    "hack": tuple(re.compile(value, re.I) for value in (
        r"\bhack(?:ed|ing|s)?\b", r"\bexploit(?:ed|s|ing)?\b", r"\bsecurity\s+breach\b", r"\bcyber(?:attack| attack)\b",
    )),
}


def legacy_predictions(rows: Sequence[GoldenEvent]) -> dict[str, dict[str, Any]]:
    return {
        row.id: {"id": row.id, "topics": [topic for topic, patterns in _LEGACY_PATTERNS.items() if any(p.search(row.title) for p in patterns)]}
        for row in rows
    }


def evaluate(rows: Sequence[GoldenEvent], predictions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    missing_ids = sorted({row.id for row in rows} - set(predictions))
    extra_ids = sorted(set(predictions) - {row.id for row in rows})
    if missing_ids or extra_ids:
        raise ValueError(f"prediction coverage mismatch missing={missing_ids[:3]} extra={extra_ids[:3]}")
    false_positives: list[dict[str, str]] = []
    false_negatives: list[dict[str, str]] = []
    topic_counts: dict[str, Counter[str]] = {topic: Counter() for topic in TOPICS}
    structured = Counter()
    for row in rows:
        prediction = predictions[row.id]
        predicted = set(prediction.get("topics", ()))
        # Each positive cohort is exhaustively labelled for its expected topic.
        # The shared negative-control cohort is exhaustively negative for all six
        # topics. Other positive cohorts are not treated as negatives because
        # valid meanings overlap (a $500M fund buy is both large and institutional).
        if row.expected_topic:
            if row.expected_topic in predicted:
                topic_counts[row.expected_topic]["tp"] += 1
                correct = True
            else:
                topic_counts[row.expected_topic]["fn"] += 1
                false_negatives.append({"id": row.id, "expected": row.expected_topic})
                correct = False
        else:
            correct = False
            for topic in sorted(predicted):
                topic_counts[topic]["fp"] += 1
                false_positives.append({"id": row.id, "predicted": topic, "expected": "none"})
        if correct:
            for key, expected_value in (
                ("asset_relevance", row.asset_relevance), ("actor_type", row.actor_type),
                ("action", row.action), ("direction", row.direction), ("magnitude_class", row.magnitude_class),
            ):
                if key in prediction:
                    structured[f"{key}_total"] += 1
                    structured[f"{key}_correct"] += prediction[key] == expected_value
    def metrics(counts: Mapping[str, int]) -> dict[str, Any]:
        local_tp, local_fp, local_fn = counts.get("tp", 0), counts.get("fp", 0), counts.get("fn", 0)
        precision = local_tp / (local_tp + local_fp) if local_tp + local_fp else 0.0
        recall = local_tp / (local_tp + local_fn) if local_tp + local_fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"tp": local_tp, "fp": local_fp, "fn": local_fn, "precision": precision, "recall": recall, "f1": f1}
    overall_counts = Counter()
    for counts in topic_counts.values():
        overall_counts.update(counts)
    overall = metrics(overall_counts)
    topic_metrics = {topic: metrics(counts) for topic, counts in sorted(topic_counts.items())}
    structured_accuracy = {
        key.removesuffix("_total"): structured[key.replace("_total", "_correct")] / total
        for key, total in structured.items() if key.endswith("_total") and total
    }
    targets = {
        "overall_precision_gte_0_90": overall["precision"] >= .90,
        "overall_recall_gte_0_80": overall["recall"] >= .80,
        "overall_f1_gte_0_85": overall["f1"] >= .85,
        "sec_precision_gte_0_95": topic_metrics["sec"]["precision"] >= .95,
        "etf_precision_gte_0_95": topic_metrics["etf"]["precision"] >= .95,
        "hack_precision_gte_0_95": topic_metrics["hack"]["precision"] >= .95,
        "large_investment_precision_gte_0_90": topic_metrics["large_investment"]["precision"] >= .90,
    }
    return {
        "rows": len(rows), "overall": overall, "topics": topic_metrics,
        "structured_accuracy": structured_accuracy, "false_positives": false_positives,
        "false_negatives": false_negatives, "targets": targets, "passed": all(targets.values()),
    }


_AMOUNT = re.compile(
    r"(?P<currency>\$|USD\s*|€|EUR\s*)(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>billion|million|bn|mn|b|m)\b",
    re.I,
)


def extract_amounts_usd(title: str) -> list[float]:
    """Deterministic headline amount parser; EUR uses a documented fixed 1.08."""
    amounts: list[float] = []
    for match in _AMOUNT.finditer(title):
        unit = match.group("unit").lower()
        multiplier = 1_000_000_000 if unit in {"billion", "bn", "b"} else 1_000_000
        fx = 1.08 if match.group("currency").strip().upper() in {"€", "EUR"} else 1.0
        amounts.append(float(match.group("number")) * multiplier * fx)
    return amounts


def magnitude_class(amount: float | None, title: str = "") -> str:
    if amount is not None:
        if amount >= LARGE_USD_THRESHOLD: return "large"
        if amount >= 10_000_000: return "medium"
        return "small"
    if re.search(r"\b(?:massive|major|billion-dollar|large treasury|major institutional)\b", title, re.I):
        return "major_unquantified"
    return "unknown"


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _trimmed_mean(values: Sequence[float]) -> float | None:
    if not values: return None
    ordered = sorted(values); trim = math.floor(len(ordered) * .05)
    selected = ordered[trim:len(ordered) - trim] if trim else ordered
    return math.fsum(selected) / len(selected)


def reaction_stats(values: Sequence[float]) -> dict[str, float | int | None]:
    n = len(values)
    std = statistics.stdev(values) if n > 1 else None
    return {
        "n": n, "mean": _mean(values), "median": _median(values),
        "positive_share": sum(value > 0 for value in values) / n if n else None,
        "trimmed_mean_5pct": _trimmed_mean(values), "sample_stddev": std,
        "standard_error": std / math.sqrt(n) if std is not None else None,
    }


def independent_reaction_stats(values: Sequence[float]) -> dict[str, Decimal | int | None]:
    decimals = [Decimal(str(value)) for value in values]
    n = len(decimals)
    if not n:
        return {"n": 0, "mean": None, "median": None, "positive_share": None, "trimmed_mean_5pct": None}
    ordered = sorted(decimals); middle = n // 2
    median = ordered[middle] if n % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    trim = math.floor(n * .05); selected = ordered[trim:n - trim] if trim else ordered
    return {
        "n": n, "mean": sum(decimals) / Decimal(n), "median": median,
        "positive_share": Decimal(sum(value > 0 for value in decimals)) / Decimal(n),
        "trimmed_mean_5pct": sum(selected) / Decimal(len(selected)),
    }


def verify_math(cases: Sequence[tuple[str, Sequence[float]]]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for case_id, values in cases:
        primary, independent = reaction_stats(values), independent_reaction_stats(values)
        for key in ("n", "mean", "median", "positive_share", "trimmed_mean_5pct"):
            left, right = primary[key], independent[key]
            if left is None or right is None:
                equal = left is None and right is None
            else:
                equal = abs(float(left) - float(right)) <= TOLERANCE
            if not equal:
                mismatches.append({"case": case_id, "field": key, "primary": left, "independent": str(right)})
    return {"cases": len(cases), "tolerance": TOLERANCE, "mismatch_count": len(mismatches), "mismatches": mismatches}


def _normalize_database_url(value: str) -> str:
    parsed = urlparse(value); query = dict(parse_qsl(parsed.query)); query["sslmode"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _production_rows(env_path: Path) -> list[dict[str, Any]]:
    # Imports stay optional so offline golden evaluation has no DB dependency.
    from dotenv import dotenv_values
    import psycopg2
    config = dotenv_values(env_path)
    database_url = str(config.get("DATABASE_URL") or "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing from the explicitly supplied env file")
    connection = psycopg2.connect(
        _normalize_database_url(database_url), application_name="semantic_matching_v2_readonly_audit",
        connect_timeout=15, options="-c statement_timeout=60000",
    )
    connection.set_session(readonly=True, autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.events")
            count = int(cursor.fetchone()[0])
            if count > MAX_ROWS:
                raise RuntimeError("Try a narrower asset, topic or date range.")
            cursor.execute(
                "SELECT event_id,title,published_at,source,source_url,primary_asset,related_assets,category,"
                "eth_1m,eth_5m,eth_15m,eth_1h,eth_4h,eth_24h FROM public.events ORDER BY event_id LIMIT %s",
                (MAX_ROWS,),
            )
            columns = [item.name for item in cursor.description]
            rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
            if len(rows) != count:
                raise RuntimeError(f"bounded production snapshot incomplete: {len(rows)} of {count}")
            return rows
    finally:
        connection.rollback()
        connection.close()


def _legacy_topics_for_title(title: str) -> set[str]:
    return {topic for topic, patterns in _LEGACY_PATTERNS.items() if any(p.search(title) for p in patterns)}


_ETH = re.compile(r"\b(?:ETH|ether|ethereum)\b", re.I)
_CRYPTO_ACTION = re.compile(r"\b(?:buy|buys|bought|purchase[sd]?|purchased|invest(?:s|ed|ment)?|adds?|added|acquir(?:e[sd]?|ed))\b", re.I)
_FUNDING = re.compile(r"\b(?:funding|funded|fundrais(?:e|es|ed|ing)|seed round|series [a-z] round|rais(?:e|es|ed|ing))\b", re.I)
_ACQUISITION = re.compile(r"\b(?:acqui(?:re[sd]?|red|sition|sitions)|takeover)\b", re.I)
_INSTITUTION = re.compile(r"\b(?:institution(?:al)?|fund|ETF|ETP|treasury|company|firm|BitMine|Strategy|MicroStrategy|Metaplanet|SharpLink|Harvard|BlackRock|Fidelity|Grayscale)\b", re.I)
_SELLING = re.compile(r"\b(?:sell|sells|sold|selling|offloads?|dumps?|divests?|redemptions?|outflows?|withdraws?)\b", re.I)


def classify_legacy_eth_row(row: Mapping[str, Any]) -> str:
    title = str(row["title"]); direct_eth = bool(_ETH.search(title)); amounts = extract_amounts_usd(title)
    action = bool(_CRYPTO_ACTION.search(title))
    if direct_eth and action and amounts and max(amounts) >= LARGE_USD_THRESHOLD:
        return "true_large_eth_investment"
    if _FUNDING.search(title) and not direct_eth:
        return "funding_only"
    if _ACQUISITION.search(title) and not (direct_eth and action):
        return "acquisition_only"
    if not direct_eth and "ETH" in (row.get("related_assets") or []):
        return "eth_secondary_mention"
    if re.search(r"\binvest", title, re.I):
        return "generic_investment"
    return "unrelated_false_positive"


def _institutional_purchase(row: Mapping[str, Any]) -> bool:
    title = str(row["title"])
    return bool(_INSTITUTION.search(title) and _CRYPTO_ACTION.search(title) and re.search(r"\b(?:ETH|ether|ethereum|BTC|bitcoin|SOL|solana)\b", title, re.I) and not _SELLING.search(title))


def _institutional_selling(row: Mapping[str, Any]) -> bool:
    title = str(row["title"])
    return bool(_INSTITUTION.search(title) and _SELLING.search(title) and re.search(r"\b(?:ETH|ether|ethereum|BTC|bitcoin|SOL|solana|ETF|ETP|fund)\b", title, re.I))


def production_candidate_predictions(rows: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    """Run the shipped TypeScript classifier over the bounded local snapshot."""
    bridge = ROOT / "scripts" / "quality" / "semantic_matching_v2_predict.mjs"
    payload = "".join(json.dumps(dict(row), default=str) + "\n" for row in rows)
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(bridge), "--production-stdin"],
        input=payload, text=True, capture_output=True, cwd=ROOT, timeout=60, check=True,
    )
    decoded = json.loads(result.stdout)
    if int(decoded.get("scanned", -1)) != len(rows):
        raise RuntimeError("candidate production bridge did not scan the complete bounded snapshot")
    return {
        str(item["event_id"]): set(item.get("matched_topics", ()))
        for item in decoded.get("selected", ())
    }


def _reaction_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in ("1m", "5m", "15m", "1h", "4h", "24h"):
        values = [float(row[f"eth_{horizon}"]) for row in rows if row.get(f"eth_{horizon}") is not None]
        output[horizon] = reaction_stats(values)
    return output


def _reaction_delta(
    left: Mapping[str, Mapping[str, float | int | None]],
    right: Mapping[str, Mapping[str, float | int | None]],
) -> dict[str, dict[str, float | int | None]]:
    output: dict[str, dict[str, float | int | None]] = {}
    for horizon in ("1m", "5m", "15m", "1h", "4h", "24h"):
        values: dict[str, float | int | None] = {
            "left_n": left[horizon]["n"], "right_n": right[horizon]["n"]
        }
        for key in ("mean", "median", "trimmed_mean_5pct"):
            left_value, right_value = left[horizon][key], right[horizon][key]
            values[f"{key}_delta"] = (
                float(left_value) - float(right_value)
                if left_value is not None and right_value is not None else None
            )
        left_share, right_share = left[horizon]["positive_share"], right[horizon]["positive_share"]
        values["positive_share_delta_pp"] = (
            (float(left_share) - float(right_share)) * 100
            if left_share is not None and right_share is not None else None
        )
        output[horizon] = values
    return output


def production_audit(
    rows: Sequence[Mapping[str, Any]],
    candidate_predictions: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    eth_rows = [row for row in rows if "ETH" in (row.get("related_assets") or [])]
    old_large = [row for row in eth_rows if "large_investment" in _legacy_topics_for_title(str(row["title"]))]
    classifications = Counter(classify_legacy_eth_row(row) for row in old_large)
    predictions = candidate_predictions or {}
    cleaned_large = [row for row in rows if "large_investment" in predictions.get(str(row["event_id"]), set())]
    purchases = [row for row in rows if "institutional_purchase" in predictions.get(str(row["event_id"]), set())]
    selling = [row for row in rows if "institutional_selling" in predictions.get(str(row["event_id"]), set())]
    explicit_amounts = [max(values) for row in old_large if (values := extract_amounts_usd(str(row["title"]))) ]
    distribution = Counter()
    distribution["no_explicit_amount"] = len(old_large) - len(explicit_amounts)
    for amount in explicit_amounts:
        bucket = "lt_10m" if amount < 10e6 else "10m_to_lt_50m" if amount < 50e6 else "50m_to_lt_250m" if amount < 250e6 else "250m_to_lt_1b" if amount < 1e9 else "gte_1b"
        distribution[bucket] += 1
    cohorts = {
        "eth_large_before_legacy": old_large, "eth_large_after_semantic_cleaning": cleaned_large,
        "institutional_buying": purchases, "institutional_selling_or_outflow": selling,
    }
    cases: list[tuple[str, Sequence[float]]] = []
    for cohort, selected in cohorts.items():
        for horizon in ("1m", "5m", "15m", "1h", "4h", "24h"):
            cases.append((f"{cohort}:{horizon}", [float(row[f"eth_{horizon}"]) for row in selected if row.get(f"eth_{horizon}") is not None]))
    # Six additional deterministic partitions make the independent check >=30.
    for horizon in ("1m", "5m", "15m", "1h", "4h", "24h"):
        values = [float(row[f"eth_{horizon}"]) for row in eth_rows if row.get(f"eth_{horizon}") is not None and str(row["event_id"])[-1] in "01234567"]
        cases.append((f"eth_hash_partition:{horizon}", values))
    count = len(old_large)
    impact = {name: _reaction_report(selected) for name, selected in cohorts.items()}
    return {
        "mode": "production_readonly", "production_writes": "NO", "reaction_values_recalculated": "NO",
        "events_scanned": len(rows), "scan_limit": MAX_ROWS, "eth_related_events": len(eth_rows),
        "old_eth_large_investment_count": count,
        "old_339_confirmed": count == 339,
        "candidate_classifier": "frontend/lib/ai-search/semantic-matcher.ts",
        "candidate_eth_counts": {
            "large_investment": len(cleaned_large),
            "institutional_purchase": len(purchases),
            "institutional_selling": len(selling),
        },
        "old_339_classification": {
            key: {"count": value, "percent": value * 100 / count if count else 0.0}
            for key, value in sorted(classifications.items())
        },
        "amount_distribution": {
            "threshold_usd": LARGE_USD_THRESHOLD, "fixed_eur_usd": 1.08,
            "explicit_amount_count": len(explicit_amounts), "buckets": dict(distribution),
            "min": min(explicit_amounts) if explicit_amounts else None,
            "median": statistics.median(explicit_amounts) if explicit_amounts else None,
            "max": max(explicit_amounts) if explicit_amounts else None,
            "rationale": "USD 50M separates explicit large capital deployment from routine sub-50M rounds/purchases; amountless events require a strong major-scale phrase and lower confidence.",
        },
        "statistical_impact": impact,
        "statistical_deltas": {
            "after_minus_before": _reaction_delta(
                impact["eth_large_after_semantic_cleaning"], impact["eth_large_before_legacy"]
            ),
            "institutional_buying_minus_selling": _reaction_delta(
                impact["institutional_buying"], impact["institutional_selling_or_outflow"]
            ),
        },
        "independent_math_verification": verify_math(cases),
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float): return f"{value:.6f}"
    return str(value)


def markdown_report(report: Mapping[str, Any]) -> str:
    lines = ["# Semantic Matching V2 — independent quality audit", "", "## Golden dataset", ""]
    lines.append(f"The manually reviewed oracle contains **{report['golden']['rows']}** unique events with distribution `{json.dumps(report['golden']['distribution'], sort_keys=True)}`.")
    for name in ("legacy", "candidate"):
        audit = report.get(name)
        if not audit: continue
        overall = audit["overall"]
        lines += ["", f"## {name.title()} matcher", "", "| Precision | Recall | F1 | FP | FN | Gate |", "|---:|---:|---:|---:|---:|:---:|", f"| {_fmt(overall['precision'])} | {_fmt(overall['recall'])} | {_fmt(overall['f1'])} | {overall['fp']} | {overall['fn']} | {'PASS' if audit['passed'] else 'FAIL'} |", "", "| Topic | Precision | Recall | F1 | FP | FN |", "|---|---:|---:|---:|---:|---:|"]
        for topic, values in audit["topics"].items():
            lines.append(f"| {topic} | {_fmt(values['precision'])} | {_fmt(values['recall'])} | {_fmt(values['f1'])} | {values['fp']} | {values['fn']} |")
    production = report.get("production")
    if production:
        lines += ["", "## Production read-only audit", "", f"Scanned {production['events_scanned']} rows (bounded at {production['scan_limit']}); writes: **NO**; Reaction V2 recalculation: **NO**.", "", f"Legacy ETH large-investment sample: **{production['old_eth_large_investment_count']}**; exact 339 confirmed: **{production['old_339_confirmed']}**.", "", "| Classification | Count | Percent |", "|---|---:|---:|"]
        for label, values in production["old_339_classification"].items():
            lines.append(f"| {label} | {values['count']} | {values['percent']:.2f}% |")
        lines += ["", "Candidate ETH cohorts from the shipped TypeScript classifier: " + ", ".join(
            f"`{key}` **{value}**" for key, value in production["candidate_eth_counts"].items()
        ) + ".", "", "### Reaction V2 statistical impact", "", "| Cohort | Horizon | n | Mean | Median | Positive share | 5% trimmed mean | SD | SE |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for cohort, horizons in production["statistical_impact"].items():
            for horizon, values in horizons.items():
                lines.append(
                    f"| {cohort} | {horizon} | {values['n']} | {_fmt(values['mean'])} | {_fmt(values['median'])} | "
                    f"{_fmt(values['positive_share'])} | {_fmt(values['trimmed_mean_5pct'])} | "
                    f"{_fmt(values['sample_stddev'])} | {_fmt(values['standard_error'])} |"
                )
        lines += ["", "### Cohort deltas", "", "| Comparison | Horizon | left n | right n | Mean delta | Median delta | Positive-share delta (pp) | Trimmed-mean delta |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for comparison, horizons in production["statistical_deltas"].items():
            for horizon, values in horizons.items():
                lines.append(
                    f"| {comparison} | {horizon} | {values['left_n']} | {values['right_n']} | "
                    f"{_fmt(values['mean_delta'])} | {_fmt(values['median_delta'])} | "
                    f"{_fmt(values['positive_share_delta_pp'])} | {_fmt(values['trimmed_mean_5pct_delta'])} |"
                )
        verification = production["independent_math_verification"]
        lines += ["", "## Independent math verification", "", f"Cases: **{verification['cases']}**; tolerance: `{verification['tolerance']}`; mismatches: **{verification['mismatch_count']}**."]
    lines += ["", "## Limitations", "", "Golden labels use immutable headline evidence; ambiguous facts requiring article-body context are excluded or labelled conservatively. Production classification is an independent deterministic audit, not a replacement for the golden oracle. EUR normalization is fixed at 1.08 rather than live FX. No production rows were sent to an AI service.", ""]
    return "\n".join(lines)


def run(golden_path: Path, predictions_path: Path | None = None, production_env: Path | None = None) -> dict[str, Any]:
    golden = load_golden(golden_path)
    report: dict[str, Any] = {
        "schema_version": "semantic_matching_v2_audit_v1",
        "golden": {"rows": len(golden), "distribution": dict(Counter(row.audit_bucket for row in golden)), "manual_labels": True},
        "legacy": evaluate(golden, legacy_predictions(golden)),
    }
    if predictions_path:
        report["candidate"] = evaluate(golden, load_predictions(predictions_path))
    if production_env:
        production_rows = _production_rows(production_env)
        report["production"] = production_audit(
            production_rows, production_candidate_predictions(production_rows)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--production-env", type=Path, help="explicit path to env containing DATABASE_URL")
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args()
    report = run(args.golden, args.predictions, args.production_env)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report_md.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "golden_rows": report["golden"]["rows"], "legacy": report["legacy"]["overall"],
        "candidate": report.get("candidate", {}).get("overall"),
        "production_old_eth_large": report.get("production", {}).get("old_eth_large_investment_count"),
        "production_writes": "NO", "reaction_values_recalculated": "NO",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
