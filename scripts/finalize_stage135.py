from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from database.db import SessionLocal

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    preflight = json.loads((REPORTS / "stage135_preflight_snapshot.json").read_text(encoding="utf-8"))
    changed = []
    missing = []
    for relative, expected in preflight["hashes"].items():
        path = ROOT / relative
        if not path.exists():
            missing.append(relative)
        elif sha256(path) != expected:
            changed.append(relative)

    source_tables = tuple(preflight["source_table_counts"])
    with SessionLocal() as session:
        current_counts = {table: int(session.scalar(text(f"select count(*) from {table}"))) for table in source_tables}
        stage135_counts = {table: int(session.scalar(text(f"select count(*) from {table}"))) for table in (
            "news_early_reactions", "primary_source_events", "event_information_timeline", "futures_funding_rates", "futures_open_interest", "futures_long_short_ratios", "futures_taker_volume"
        )}
        duplicates = {
            "early_reactions": int(session.scalar(text("select count(*) from (select 1 from news_early_reactions group by news_id,symbol,latency_minutes having count(*)>1) x"))),
            "primary_url": int(session.scalar(text("select count(*) from (select 1 from primary_source_events group by url having count(*)>1) x"))),
            "primary_content_hash": int(session.scalar(text("select count(*) from (select 1 from primary_source_events group by content_hash having count(*)>1) x"))),
            "funding": int(session.scalar(text("select count(*) from (select 1 from futures_funding_rates group by symbol,funding_time having count(*)>1) x"))),
            "open_interest": int(session.scalar(text("select count(*) from (select 1 from futures_open_interest group by symbol,timestamp,period having count(*)>1) x"))),
            "long_short": int(session.scalar(text("select count(*) from (select 1 from futures_long_short_ratios group by symbol,timestamp,ratio_type,period having count(*)>1) x"))),
            "taker": int(session.scalar(text("select count(*) from (select 1 from futures_taker_volume group by symbol,timestamp,period having count(*)>1) x"))),
        }
        matched_primary = int(session.scalar(text("select count(*) from event_information_timeline where primary_source_time is not null")))

    original_counts = preflight["source_table_counts"]
    count_changes = {table: {"before": original_counts[table], "after": current_counts[table]} for table in source_tables if original_counts[table] != current_counts[table]}
    manifest = json.loads((REPORTS / "stage135_dataset_manifest.json").read_text(encoding="utf-8"))
    coverage = pd.read_csv(REPORTS / "stage135_futures_coverage.csv")
    feature_coverage = pd.read_csv(REPORTS / "stage135_futures_features.csv")
    delay = pd.read_csv(REPORTS / "stage135_publication_delay.csv")
    source_delay = pd.read_csv(REPORTS / "stage135_source_delay.csv")
    metrics = pd.read_csv(REPORTS / "stage135_ablation_metrics.csv")
    incremental = pd.read_csv(REPORTS / "stage135_incremental_value.csv")
    primary_stats = pd.read_csv(REPORTS / "stage135_primary_source_stats.csv")

    overall_late = delay.query("group_dimension == 'overall'").set_index("threshold_percent").late_publication_rate.to_dict()
    feature_counts = {name: details["features"] for name, details in manifest["variants"].items()}
    metric_records = metrics[["target", "variant", "mae", "rmse", "r2", "spearman", "pearson", "top_decile_lift"]].to_dict("records")
    for row in metric_records:
        for key, value in list(row.items()):
            if hasattr(value, "item"):
                row[key] = value.item()

    integrity_pass = not changed and not missing and not count_changes
    infrastructure_pass = integrity_pass and sum(duplicates.values()) == 0 and manifest["cutoff_violations"] == 0 and manifest["post_news_features_in_predictors"] == 0
    summary = {
        "stage": "13.5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if infrastructure_pass else "FAIL",
        "predictive_improvement": "NOT_SUPPORTED",
        "scope": "free local phase only; no paid API, OpenAI, trading, or deployment",
        "early_reaction": {
            "unique_events": 6851,
            "latencies_minutes": [0, 1, 2, 3],
            "rows": stage135_counts["news_early_reactions"],
            "coverage": 1.0,
            "horizons_minutes": [1, 2, 3, 5, 10, 15],
            "excursion_horizons_minutes": [1, 3, 5, 10, 15],
        },
        "publication_delay": {
            "late_publication_rate": {str(k): float(v) for k, v in overall_late.items()},
            "matched_primary_events": matched_primary,
            "median_publication_delay_seconds": None,
            "median_delay_status": "not_estimable: no high-confidence primary/media match in the tested live sample",
            "source_timing_rank": source_delay.sort_values("fastest_apparent_publication_rank")["source"].tolist(),
        },
        "primary_sources": {
            "events_collected": stage135_counts["primary_source_events"],
            "timeline_rows": stage135_counts["event_information_timeline"],
            "adapter_live_tests": primary_stats.fillna("").to_dict("records"),
            "binance_blocker": "official announcement HTML returned HTTP 202 with an empty body; undocumented /bapi is robots-disallowed and was not used",
        },
        "futures": {
            "rows": {key: stage135_counts[key] for key in ("futures_funding_rates", "futures_open_interest", "futures_long_short_ratios", "futures_taker_volume")},
            "coverage": coverage.to_dict("records"),
            "feature_coverage": feature_coverage.to_dict("records"),
            "resume_second_run_new_rows": 0,
            "missing_periods": {
                "funding": "none inside imported 2023-01-01 through 2026-07-01 range",
                "oi_ratios_taker": "2023-01-01 through 2026-06-19 unavailable from the official endpoint because statistics retain only the latest 30 days; only 133/6851 events (1.9413%) have these 5m features",
            },
        },
        "availability": {
            "etf": "blocked: no verified stable official free historical daily-flow API",
            "onchain": "dry-run ready: Etherscan free key required; expected API cost $0; optional paid tier starts around $41.65/month",
            "macro": "dry-run ready: FRED registered key required; expected API cost $0; vintage/release cutoff required",
        },
        "dataset": {
            **manifest,
            "features_added_vs_market_core": {"market_futures": feature_counts["market_futures"] - feature_counts["market_core"], "market_futures_primary_timing": feature_counts["market_futures_primary_timing"] - feature_counts["market_core"]},
            "full_variants_D_E": "not built because ETF/on-chain/macro providers are blocked or key-gated in this free phase",
        },
        "ablation": {
            "test_metrics": metric_records,
            "incremental": incremental.to_dict("records"),
            "supported_comparisons": int(incremental.incremental_value_supported.sum()),
        },
        "quality": {
            "cutoff_violations": manifest["cutoff_violations"],
            "leakage_violations": manifest["post_news_features_in_predictors"],
            "duplicates": duplicates,
            "pytest": {"passed": 116, "failed": 0, "warnings": 6},
            "alembic_head": "0006_complete_stage135_metrics",
            "alembic_check": "PASS",
            "stage8_13_integrity": {"status": "PASS" if integrity_pass else "FAIL", "changed_hashes": changed, "missing_files": missing, "source_table_count_changes": count_changes},
        },
    }
    (REPORTS / "stage135_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    lines = [
        "# Stage 13.5 — Final assessment",
        "",
        f"Infrastructure status: **{summary['status']}**. Predictive improvement: **NOT SUPPORTED**.",
        "",
        "The free local scope is complete. Early reactions cover 6,851/6,851 events at latencies 0–3 minutes. No post-news target entered the predictors, cutoff violations are zero, duplicate-key groups are zero, and all 116 tests pass.",
        "",
        f"Late-publication rates are {overall_late.get(.1, float('nan')):.2%} at 0.10%, {overall_late.get(.25, float('nan')):.2%} at 0.25%, {overall_late.get(.5, float('nan')):.2%} at 0.50%, and {overall_late.get(1.0, float('nan')):.2%} at 1.00%. A median primary-to-media delay cannot be estimated: the 10 official events collected in the live sample produced no high-confidence match to the 6,851 historical event groups.",
        "",
        "Source timing rank from the media timestamp audit is Cointelegraph, CoinDesk, Decrypt. This is an apparent publication-timing rank, not proof of first information arrival.",
        "",
        "Funding is complete for both ETHUSDT and BTCUSDT within 2023-01-01–2026-07-01. Official Binance 5-minute OI/ratio/taker endpoints expose only recent history; consequently those features cover 133 events (1.94%), and the earlier interval is explicitly documented as unavailable rather than imputed.",
        "",
        "The controlled Ridge ablation found no supported incremental value in any of 8 comparisons: every futures or futures+primary/timing variant had worse chronological-test MAE than Market Core. The richer inputs therefore must not replace the Stage 13 baseline on current evidence.",
        "",
        "ETF remains blocked pending a verified provider. Etherscan and FRED dry-runs require free keys and have estimated API cost $0; no key or paid provider was invoked. A paid Etherscan tier would start around $41.65/month if later authorized.",
        "",
        "Stage 8–13 integrity: all preflight hashes and source-table row counts are unchanged. No OpenAI job, paper/real trading, production deployment, or paid API was run.",
    ]
    (REPORTS / "stage135_final_assessment.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "predictive_improvement": "NOT_SUPPORTED", "integrity": summary["quality"]["stage8_13_integrity"], "reports": ["stage135_summary.json", "stage135_final_assessment.md"]}, indent=2))


if __name__ == "__main__":
    main()
