"""Read-only audit of publication timestamps versus canonical event timestamps.

This module deliberately does not infer an event timestamp from a headline.  A
lag is measurable only when ``event_at`` is populated.  Production Reaction V2
columns are read for context and are never updated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "semantic_matching_v2"
DEFAULT_ENV = ROOT.parents[1] / "eth_news_trading_bot" / ".env"
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
SAMPLE_SIZE = 120
SAMPLE_PER_CLASS = 60
AUDITED_SOURCE_CLASSES = ("primary_document", "news_media")
HORIZONS_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "24h": 1440}
REACTION_COLUMNS = [
    f"{asset.lower()}_{horizon}"
    for asset in ("BTC", "ETH", "SOL")
    for horizon in HORIZONS_MINUTES
]
MAX_SCAN_ROWS = 10_000
NARROWER_SCOPE_MESSAGE = "Try a narrower asset, topic or date range."


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def _stable_order(event_id: object, salt: str = "timestamp-audit-v1") -> str:
    return hashlib.sha256(f"{salt}:{event_id}".encode("utf-8")).hexdigest()


def select_stratified_sample(
    events: pd.DataFrame,
    *,
    per_class: int = SAMPLE_PER_CLASS,
    source_classes: tuple[str, ...] = AUDITED_SOURCE_CLASSES,
) -> pd.DataFrame:
    """Select an identity-stable, source-class-balanced audit sample."""

    required = {"event_id", "source_class_v2"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Missing sample columns: {sorted(missing)}")
    pieces: list[pd.DataFrame] = []
    for source_class in source_classes:
        candidates = events.loc[events.source_class_v2.eq(source_class)].copy()
        if len(candidates) < per_class:
            raise ValueError(
                f"Need {per_class} {source_class} events; only {len(candidates)} available"
            )
        candidates["_sample_order"] = candidates.event_id.map(_stable_order)
        pieces.append(candidates.sort_values("_sample_order").head(per_class))
    sample = pd.concat(pieces, ignore_index=True).drop(columns="_sample_order")
    if len(sample) < 100:
        raise ValueError("Timestamp audit sample must contain at least 100 events")
    return sample.sort_values(["source_class_v2", "event_id"]).reset_index(drop=True)


def assess_timestamps(sample: pd.DataFrame) -> pd.DataFrame:
    """Add evidence-bounded timestamp audit fields to sampled production rows."""

    result = sample.copy()
    result["article_published_at"] = pd.to_datetime(result.published_at, utc=True)
    result["primary_announcement_at"] = pd.to_datetime(result.event_at, utc=True)
    result["is_primary_announcement_document"] = result.source_class_v2.eq(
        "primary_document"
    )
    # A primary document is primary-source evidence, but its publication time is
    # not silently promoted to the time at which the described event occurred.
    has_event_time = result.primary_announcement_at.notna()
    result["estimated_lag_minutes"] = (
        result.article_published_at - result.primary_announcement_at
    ).dt.total_seconds().div(60).where(has_event_time)
    result["headline_describes_earlier_event"] = result.estimated_lag_minutes.gt(0).where(
        has_event_time
    ).astype("boolean")
    result["lag_available"] = has_event_time
    stored_confidence = result.event_time_confidence.astype("string").str.lower()
    result["timing_confidence"] = stored_confidence.where(
        stored_confidence.isin(["high", "medium", "low"]), "low"
    )
    result["timing_evidence"] = np.where(
        has_event_time,
        result.event_time_source.fillna("event_at present; provenance unavailable"),
        "event_at unavailable; headline timing was not inferred",
    )
    result["primary_pair_eligible"] = (
        result.source_class_v2.eq("news_media")
        & has_event_time
        & result.timing_confidence.eq("high")
        & result.estimated_lag_minutes.ge(0)
    )
    return result


def _percent_over(values: pd.Series, threshold: float) -> float | None:
    clean = values.dropna()
    return float(clean.gt(threshold).mean() * 100) if len(clean) else None


def lag_summary(audit: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source_class, group in audit.groupby("source_class_v2", sort=True):
        lag = group.estimated_lag_minutes.dropna()
        valid = lag[lag.ge(0)]
        rows.append(
            {
                "source_class": source_class,
                "sample_n": len(group),
                "event_at_n": int(group.primary_announcement_at.notna().sum()),
                "event_at_coverage_pct": float(group.primary_announcement_at.notna().mean() * 100),
                "valid_nonnegative_lag_n": len(valid),
                "negative_lag_n": int(lag.lt(0).sum()),
                "median_lag_minutes": float(valid.median()) if len(valid) else None,
                "p75_lag_minutes": float(valid.quantile(0.75)) if len(valid) else None,
                "p90_lag_minutes": float(valid.quantile(0.90)) if len(valid) else None,
                "pct_lag_gt_5m": _percent_over(valid, 5),
                "pct_lag_gt_15m": _percent_over(valid, 15),
                "pct_lag_gt_1h": _percent_over(valid, 60),
                "status": "measured" if len(valid) else "unavailable",
            }
        )
    return pd.DataFrame(rows)


def first_full_minute_after(value: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).floor("min") + pd.Timedelta(minutes=1)


def anchored_return(
    candles: pd.DataFrame, anchor: pd.Timestamp, horizon_minutes: int
) -> float | None:
    """Reaction V2-compatible open-to-open return from a supplied anchor."""

    if candles.empty:
        return None
    opens = candles.copy()
    opens["open_time"] = pd.to_datetime(opens.open_time, utc=True)
    opens = opens.drop_duplicates("open_time").set_index("open_time").open
    reference = first_full_minute_after(pd.Timestamp(anchor))
    endpoint = reference + pd.Timedelta(minutes=horizon_minutes)
    if reference not in opens.index or endpoint not in opens.index:
        return None
    start, end = float(opens.loc[reference]), float(opens.loc[endpoint])
    if not math.isfinite(start) or not math.isfinite(end) or start == 0:
        return None
    return (end / start - 1.0) * 100.0


def load_pair_candles(
    pairs: pd.DataFrame, price_path_root: Path
) -> pd.DataFrame:
    """Load only partitions needed by eligible pairs; return empty if none exist."""

    required = {"canonical_event_id", "asset", "open_time", "open"}
    frames: list[pd.DataFrame] = []
    for row in pairs.itertuples(index=False):
        asset = str(row.primary_asset).upper()
        months = {
            (stamp.year, stamp.month)
            for stamp in (row.article_published_at, row.primary_announcement_at)
            if pd.notna(stamp)
        }
        # Include adjacent months because a 24h horizon may cross a boundary.
        expanded: set[tuple[int, int]] = set()
        for year, month in months:
            base = pd.Timestamp(year=year, month=month, day=15, tz="UTC")
            for shift in (-1, 0, 1):
                value = base + pd.DateOffset(months=shift)
                expanded.add((value.year, value.month))
        for year, month in sorted(expanded):
            partition = price_path_root / f"asset={asset}" / f"year={year}" / f"month={month:02d}"
            for path in sorted(partition.glob("*.parquet")):
                frame = pd.read_parquet(path, columns=list(required))
                frames.append(
                    frame.loc[
                        frame.canonical_event_id.astype(str).eq(str(row.event_id))
                        & frame.asset.astype(str).str.upper().eq(asset)
                    ]
                )
    if not frames:
        return pd.DataFrame(columns=sorted(required))
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        ["canonical_event_id", "asset", "open_time"]
    )


def reaction_bias(
    audit: pd.DataFrame, candles: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare article and primary anchors for high-confidence media pairs."""

    pairs = audit.loc[audit.primary_pair_eligible].copy()
    detail_rows: list[dict[str, object]] = []
    for event in pairs.itertuples(index=False):
        asset = str(event.primary_asset).upper()
        event_candles = candles.loc[
            candles.canonical_event_id.astype(str).eq(str(event.event_id))
            & candles.asset.astype(str).str.upper().eq(asset)
        ]
        for label, minutes in HORIZONS_MINUTES.items():
            reaction_column = f"{asset.lower()}_{label}"
            stored_article_return = getattr(event, reaction_column, None)
            article_return = (
                float(stored_article_return)
                if pd.notna(stored_article_return)
                else anchored_return(event_candles, event.article_published_at, minutes)
            )
            article_return_source = (
                "production_reaction_v2"
                if pd.notna(stored_article_return)
                else "recomputed_from_local_candles"
            )
            primary_return = anchored_return(event_candles, event.primary_announcement_at, minutes)
            detail_rows.append(
                {
                    "event_id": event.event_id,
                    "asset": asset,
                    "horizon": label,
                    "article_anchor_at": event.article_published_at,
                    "primary_anchor_at": event.primary_announcement_at,
                    "article_anchor_return_source": article_return_source,
                    "article_anchor_return_pct": article_return,
                    "primary_anchor_return_pct": primary_return,
                    "article_minus_primary_pp": (
                        article_return - primary_return
                        if article_return is not None and primary_return is not None
                        else None
                    ),
                }
            )
    detail = pd.DataFrame(
        detail_rows,
        columns=[
            "event_id", "asset", "horizon", "article_anchor_at", "primary_anchor_at",
            "article_anchor_return_source", "article_anchor_return_pct", "primary_anchor_return_pct",
            "article_minus_primary_pp",
        ],
    )
    summary_rows: list[dict[str, object]] = []
    for label in HORIZONS_MINUTES:
        group = detail.loc[detail.horizon.eq(label)] if len(detail) else detail
        complete = group.dropna(
            subset=["article_anchor_return_pct", "primary_anchor_return_pct"]
        ) if len(group) else group
        delta = complete.article_minus_primary_pp if len(complete) else pd.Series(dtype=float)
        flips = (
            np.sign(complete.article_anchor_return_pct)
            != np.sign(complete.primary_anchor_return_pct)
        ) if len(complete) else pd.Series(dtype=bool)
        summary_rows.append(
            {
                "horizon": label,
                "eligible_pair_n": len(pairs),
                "complete_pair_n": len(complete),
                "article_anchor_mean_pct": float(complete.article_anchor_return_pct.mean()) if len(complete) else None,
                "primary_anchor_mean_pct": float(complete.primary_anchor_return_pct.mean()) if len(complete) else None,
                "mean_delta_pp": float(delta.mean()) if len(delta) else None,
                "median_abs_delta_pp": float(delta.abs().median()) if len(delta) else None,
                "direction_flip_n": int(flips.sum()) if len(flips) else 0,
                "direction_flip_pct": float(flips.mean() * 100) if len(flips) else None,
                "status": "measured" if len(complete) else "unavailable",
            }
        )
    return pd.DataFrame(summary_rows), detail


def fetch_production_events(database_url: str, expected_project_ref: str) -> pd.DataFrame:
    parsed = urlparse(database_url)
    identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if expected_project_ref and expected_project_ref not in identity:
        raise RuntimeError("DATABASE_URL does not identify the expected production project")
    columns = [
        "event_id", "title", "source", "source_url", "published_at", "primary_asset",
        "source_class_v2", "document_class_v2", "publication_time_source",
        "publication_time_confidence", "event_at", "event_time_source",
        "event_time_confidence", *REACTION_COLUMNS,
    ]
    connection = psycopg2.connect(
        database_url,
        application_name="semantic_timestamp_readonly_audit",
        connect_timeout=15,
        options="-c statement_timeout=60000",
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM public.events "
                "ORDER BY event_id LIMIT %s",
                (MAX_SCAN_ROWS + 1,),
            )
            names = [item.name for item in cursor.description]
            events = pd.DataFrame(cursor.fetchall(), columns=names)
            if len(events) > MAX_SCAN_ROWS:
                raise RuntimeError(NARROWER_SCOPE_MESSAGE)
        connection.rollback()
    finally:
        connection.close()
    return events


def _json_value(value: object) -> object:
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def load_contextual_bias_evidence(root: Path = ROOT) -> dict[str, object]:
    """Load prior market-move proxies without relabelling them canonical truth."""

    stage13_path = root / "reports/stage13a_eth_summary.json"
    delay_path = root / "reports/stage135_publication_delay.csv"
    timing_path = root / "data/stage135/market_futures_primary_timing.parquet"
    evidence: dict[str, object] = {
        "status": "unavailable",
        "interpretation": "Market pre-move diagnostics are proxies, not canonical event-time pairs.",
        "artifacts": [
            stage13_path.relative_to(root).as_posix(),
            delay_path.relative_to(root).as_posix(),
            timing_path.relative_to(root).as_posix(),
        ],
    }
    if not (stage13_path.exists() and delay_path.exists() and timing_path.exists()):
        return evidence
    stage13 = json.loads(stage13_path.read_text(encoding="utf-8"))
    delay = pd.read_csv(delay_path)
    overall_010 = delay.loc[
        delay.group_dimension.eq("overall")
        & delay.group_value.eq("all")
        & delay.threshold_percent.eq(0.1)
    ]
    timing = pd.read_parquet(timing_path, columns=["pre_primary_source_found"])
    found = pd.to_numeric(timing.pre_primary_source_found, errors="coerce").fillna(0).ne(0)
    evidence.update(
        {
            "status": "available_context_only",
            "stage13a_events_analyzed": int(stage13["events_analyzed"]),
            "stage13a_late_publication_proxy_rate_0_10pct": float(
                stage13["late_publication_rates"]["threshold_0.10pct"]
            ),
            "stage13a_conclusion": str(stage13["late_timestamp_conclusion"]),
            "stage135_overall_late_publication_proxy_rate_0_10pct": (
                float(overall_010.iloc[0].late_publication_rate)
                if len(overall_010)
                else None
            ),
            "stage135_primary_timing_rows": len(timing),
            "stage135_pre_primary_source_found_n": int(found.sum()),
            "canonical_pair_usable": bool(found.any()),
        }
    )
    return evidence


def build_summary(
    events: pd.DataFrame,
    audit: pd.DataFrame,
    lag: pd.DataFrame,
    bias: pd.DataFrame,
    contextual_evidence: dict[str, object],
) -> dict[str, object]:
    all_event_at = int(pd.to_datetime(events.event_at, utc=True).notna().sum())
    high_pairs = int(audit.primary_pair_eligible.sum())
    measured_cells = int(bias.complete_pair_n.sum())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_mode": "read_only",
        "production_events_n": len(events),
        "production_event_at_n": all_event_at,
        "production_event_at_coverage_pct": all_event_at / len(events) * 100 if len(events) else 0,
        "sample_n": len(audit),
        "sample_by_source_class": {
            str(key): int(value)
            for key, value in audit.source_class_v2.value_counts().sort_index().items()
        },
        "sample_event_at_n": int(audit.primary_announcement_at.notna().sum()),
        "sample_manual_canonical_truth_n": int(
            audit.event_time_source.astype("string").str.contains("manual", case=False, na=False).sum()
        ),
        "high_confidence_news_primary_pair_n": high_pairs,
        "measured_reaction_pair_cells_n": measured_cells,
        "lag_metrics": [
            {key: _json_value(value) for key, value in row.items()}
            for row in lag.to_dict("records")
        ],
        "reaction_bias": [
            {key: _json_value(value) for key, value in row.items()}
            for row in bias.to_dict("records")
        ],
        "contextual_reaction_start_evidence": contextual_evidence,
        "evidence_status": "sufficient" if high_pairs and measured_cells else "insufficient",
        "decision_gate": "B",
        "recommendation": (
            "Plan Reaction V3 around a separately reviewed canonical event timestamp; "
            "do not build or migrate V3 in this task, and leave all Reaction V2 values unchanged."
        ),
        "recommendation_caveat": (
            "Exact canonical lag and reaction deltas remain unavailable. However, zero canonical "
            "coverage plus a material prior pre-publication-move subset make Reaction V2 "
            "insufficient for claims about reaction from the event itself."
        ),
        "v3_evidence_required": (
            "Populate a separately reviewed canonical timestamp set, link news articles to primary "
            "announcements, then rerun lag and reaction-anchor comparisons before a V3 decision."
        ),
    }


def render_report(summary: dict[str, object], lag: pd.DataFrame, bias: pd.DataFrame) -> str:
    lag_lines = []
    for row in lag.itertuples(index=False):
        def show(value: object) -> str:
            return "unavailable" if pd.isna(value) else f"{float(value):.3f}"
        lag_lines.append(
            f"| {row.source_class} | {row.sample_n} | {row.event_at_n} "
            f"({row.event_at_coverage_pct:.1f}%) | {show(row.median_lag_minutes)} | "
            f"{show(row.p75_lag_minutes)} | {show(row.p90_lag_minutes)} | "
            f"{show(row.pct_lag_gt_5m)} | {show(row.pct_lag_gt_15m)} | "
            f"{show(row.pct_lag_gt_1h)} | {row.status} |"
        )
    bias_lines = []
    for row in bias.itertuples(index=False):
        value = "unavailable" if pd.isna(row.mean_delta_pp) else f"{row.mean_delta_pp:.6f}"
        bias_lines.append(
            f"| {row.horizon} | {row.eligible_pair_n} | {row.complete_pair_n} | {value} | {row.status} |"
        )
    generated = summary["generated_at"]
    context = summary["contextual_reaction_start_evidence"]
    context_text = "Context artifacts unavailable."
    if context.get("status") == "available_context_only":
        context_text = (
            f"The prior Stage 13A market diagnostic analyzed **{context['stage13a_events_analyzed']:,}** "
            f"ETH news events and flagged **{context['stage13a_late_publication_proxy_rate_0_10pct'] * 100:.2f}%** "
            f"at its 0.10% pre-move threshold (`{context['stage13a_conclusion']}`). The separate "
            f"Stage 13.5 publication-delay table reports **{context['stage135_overall_late_publication_proxy_rate_0_10pct'] * 100:.2f}%** "
            f"under its own classification. But `pre_primary_source_found` is **{context['stage135_pre_primary_source_found_n']} "
            f"of {context['stage135_primary_timing_rows']:,}**, so neither rate is a canonical "
            "event-time lag or a paired-anchor reaction delta."
        )
    return f"""# Event Timestamp Audit - Semantic Matching V2

Generated read-only from production at `{generated}`. No Reaction V2 value, schema,
or production row was changed.

## Coverage and evidence

- Production rows: **{summary['production_events_n']:,}**.
- Production rows with `event_at`: **{summary['production_event_at_n']:,}**
  ({summary['production_event_at_coverage_pct']:.1f}%).
- Deterministic audit sample: **{summary['sample_n']}** rows
  ({summary['sample_by_source_class']}).
- Sample rows backed by an explicitly manual canonical timestamp: **{summary['sample_manual_canonical_truth_n']}**.
- High-confidence news-to-primary pairs: **{summary['high_confidence_news_primary_pair_n']}**.

`published_at` is an article/document publication timestamp. The audit never treats a
past-tense headline as proof of an earlier event, and it never copies `published_at`
into `event_at`. Consequently, headline-earlier flags and estimated lags are marked
unavailable when canonical evidence is absent.

## Lag by source class

Percentages above thresholds use only rows with a nonnegative, evidence-backed lag;
coverage is shown separately so missing timestamps cannot look like zero lag.

| Source class | sample n | event_at n (coverage) | median min | p75 min | p90 min | >5m % | >15m % | >1h % | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(lag_lines)}

## Reaction start bias

Eligible comparisons require a news-media row with a nonnegative `event_at` lag and
stored **high** event-time confidence. Returns use the Reaction V2 rule: first full
minute after each anchor, open to open. A missing pair remains unavailable.

| Horizon | eligible pairs | complete pairs | mean article-primary delta (pp) | status |
|---|---:|---:|---:|---|
{chr(10).join(bias_lines)}

## Contextual market-move evidence

{context_text}

These diagnostics support concern about reaction-start bias, but cannot provide the
required median/p75/p90 lag or paired-anchor effect size.

## Decision gate

**B - plan Reaction V3 with a canonical event timestamp.** Do not build or migrate V3
in this task, and leave Reaction V2 unchanged. Evidence for the exact bias magnitude
is **{summary['evidence_status']}**. {summary['recommendation_caveat']}

V3 prerequisite: {summary['v3_evidence_required']}
"""


def write_outputs(
    report_dir: Path,
    audit: pd.DataFrame,
    lag: pd.DataFrame,
    bias: pd.DataFrame,
    detail: pd.DataFrame,
    summary: dict[str, object],
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    sample_columns = [
        "event_id", "title", "source", "source_url", "source_class_v2",
        "document_class_v2", "article_published_at", "publication_time_source",
        "publication_time_confidence", "is_primary_announcement_document",
        "primary_announcement_at", "stored_event_time_confidence",
        "headline_describes_earlier_event", "estimated_lag_minutes", "lag_available",
        "timing_confidence", "timing_evidence", "primary_pair_eligible", "primary_asset",
    ]
    export = audit.rename(columns={"event_time_confidence": "stored_event_time_confidence"})
    export[sample_columns].to_csv(report_dir / "timestamp_audit_sample.csv", index=False)
    lag.to_csv(report_dir / "timestamp_lag_metrics.csv", index=False)
    bias.to_csv(report_dir / "timestamp_reaction_bias.csv", index=False)
    detail.to_csv(report_dir / "timestamp_reaction_pairs.csv", index=False)
    (report_dir / "timestamp_audit_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (report_dir / "timestamp_audit_report.md").write_text(
        render_report(summary, lag, bias), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--price-path-root", type=Path, default=ROOT / "data/stage18/price_paths")
    parser.add_argument("--expected-project-ref", default=EXPECTED_PROJECT_REF)
    parser.add_argument("--per-class", type=int, default=SAMPLE_PER_CLASS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(args.env_file)
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError(f"DATABASE_URL is unavailable from {args.env_file}")
    events = fetch_production_events(database_url, args.expected_project_ref)
    sample = select_stratified_sample(events, per_class=args.per_class)
    audit = assess_timestamps(sample)
    lag = lag_summary(audit)
    eligible = audit.loc[audit.primary_pair_eligible]
    candles = load_pair_candles(eligible, args.price_path_root)
    bias, detail = reaction_bias(audit, candles)
    contextual_evidence = load_contextual_bias_evidence()
    summary = build_summary(events, audit, lag, bias, contextual_evidence)
    write_outputs(args.report_dir, audit, lag, bias, detail, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
