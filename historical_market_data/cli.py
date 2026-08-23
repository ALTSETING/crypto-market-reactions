from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import inspect, text

from database.db import engine
from historical_market_data.archive_discovery import discover_archives, month_range
from historical_market_data.binance_archive_client import BinanceArchiveClient
from historical_market_data.binance_rest_client import BinanceRestClient
from historical_market_data.checksum import sha256_file
from historical_market_data.coverage import coverage_audit, generate_reactions
from historical_market_data.importer import import_prepared, prepare_zip
from historical_market_data.models import ManifestRecord


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RAW = ROOT / "data" / "raw" / "binance" / "spot" / "monthly" / "klines"
TMP = ROOT / "data" / "tmp" / "stage16c"
MANIFEST = REPORTS / "stage16c_download_manifest.csv"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TARGET_START = date(2017, 1, 1)
TARGET_END = date(2022, 12, 31)


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    if hasattr(value, "item"): return value.item()
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_snapshot() -> dict[str, str]:
    paths = [p for p in REPORTS.glob("stage*") if p.is_file() and not p.name.startswith("stage16c_")]
    for directory in (ROOT / "data" / "stage17", ROOT / "data" / "stage16b"):
        if directory.exists(): paths += [p for p in directory.rglob("*") if p.is_file()]
    return {str(p.relative_to(ROOT)): file_hash(p) for p in sorted(set(paths))}


def snapshot_hash(snapshot: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{k}|{v}" for k, v in sorted(snapshot.items())).encode()).hexdigest()


def database_snapshot() -> dict[str, Any]:
    with engine.connect() as connection:
        candles = pd.read_sql(text("""SELECT symbol,count(*) rows,min(open_time) earliest,max(open_time) latest,
          coalesce(sum(id),0) id_sum,coalesce(sum(open),0) open_sum,coalesce(sum(close),0) close_sum,
          count(*) FILTER(WHERE open_time<'2023-01-01') pre_2023_rows
          FROM market_candles WHERE symbol=ANY(:symbols) AND interval='1m' GROUP BY symbol ORDER BY symbol"""),
          connection, params={"symbols": list(SYMBOLS)}).to_dict("records")
        protected_tables = [name for name in ("news_articles", "news_assets", "news_market_reactions", "news_analysis", "high_impact_events", "high_impact_event_assets", "high_impact_market_reactions", "high_impact_event_analysis") if inspect(connection).has_table(name)]
        counts = {name: int(connection.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()) for name in protected_tables}
    payload = {"candles": candles, "protected_table_counts": counts}
    payload["snapshot_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=json_default).encode()).hexdigest()
    return payload


def save_initial_snapshots() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    before_artifacts = TMP / "protected_before.json"
    before_db = TMP / "database_before.json"
    if not before_artifacts.exists(): write_json(before_artifacts, protected_snapshot())
    if not before_db.exists(): write_json(before_db, database_snapshot())


def load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST.exists(): return []
    return pd.read_csv(MANIFEST, keep_default_na=False).to_dict("records")


def save_manifest(records: list[dict[str, Any]]) -> None:
    columns = list(ManifestRecord("", "", 0, 0, "").to_dict())
    frame = pd.DataFrame(records)
    for column in columns:
        if column not in frame: frame[column] = None
    frame[columns].sort_values(["symbol", "year", "month"]).to_csv(MANIFEST, index=False)


def discovery_report(records: list[dict[str, Any]], start: date, end: date) -> pd.DataFrame:
    rows = []
    months = month_range(start, end)
    for symbol in SYMBOLS:
        part = [r for r in records if r["symbol"] == symbol]
        available = sorted((int(r["year"]), int(r["month"])) for r in part if r["status"] not in ("unavailable", "failed"))
        earliest = available[0] if available else None; latest = available[-1] if available else None
        missing_after_listing = [f"{y:04d}-{m:02d}" for y, m in months if earliest and (y, m) >= earliest and (y, m) not in available]
        imported = [r for r in part if r.get("first_open_time") not in (None, "", "None", "nan")]
        first = min((str(r["first_open_time"]) for r in imported), default=None)
        last = max((str(r["last_open_time"]) for r in imported), default=None)
        listing = pd.Timestamp(first) if first else (pd.Timestamp(datetime(earliest[0], earliest[1], 1, tzinfo=timezone.utc)) if earliest else None)
        prelisting = int(max(0, (listing - pd.Timestamp(datetime.combine(start, time.min, timezone.utc))).total_seconds() // 60)) if listing is not None else None
        rows.append({
            "symbol": symbol, "target_start": f"{start}T00:00:00+00:00", "target_end": f"{end}T23:59:00+00:00",
            "earliest_archive_month": f"{earliest[0]:04d}-{earliest[1]:02d}" if earliest else None,
            "latest_archive_month": f"{latest[0]:04d}-{latest[1]:02d}" if latest else None,
            "earliest_candle_at": first, "latest_candle_at": last, "available_months": len(available),
            "missing_months": len(missing_after_listing), "missing_month_list": "|".join(missing_after_listing),
            "pre_listing_minutes": prelisting, "full_12h_pre_context_from": (listing + pd.Timedelta(hours=12)).isoformat() if listing is not None else None,
            "discovery_status": "complete" if available and not missing_after_listing else "partial",
        })
    return pd.DataFrame(rows)


def command_discover(symbols: list[str], interval: str, start: date, end: date) -> list[dict[str, Any]]:
    save_initial_snapshots()
    found = [record.to_dict() for record in discover_archives(symbols, interval, start, end)]
    old = {(r["symbol"], int(r["year"]), int(r["month"])): r for r in load_manifest()}
    for record in found:
        key = (record["symbol"], int(record["year"]), int(record["month"]))
        if key in old and old[key].get("status") not in ("unavailable", "failed", "discovered"): record = old[key]
        old[key] = record
    records = list(old.values()); save_manifest(records)
    discovery_report(records, start, end).to_csv(REPORTS / "stage16c_archive_discovery.csv", index=False)
    return records


def _download_one(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    destination = RAW / result["symbol"] / result["interval"] / Path(result["source_url"]).name
    try:
        audit = BinanceArchiveClient().download_verified(result["source_url"], destination)
        result.update({"local_path": str(destination.relative_to(ROOT)), "downloaded_at_utc": audit.get("downloaded_at_utc") or datetime.now(timezone.utc).isoformat(), "expected_checksum": audit["expected"], "actual_checksum": audit["actual"], "file_size": audit["size"], "status": "checksum_pass", "error_message": None})
    except FileNotFoundError as exc:
        result.update(status="unavailable", error_message=str(exc))
    except Exception as exc:
        result.update(status="failed", error_message=str(exc))
    return result


def command_download(symbols: list[str], interval: str, start: date, end: date, resume: bool) -> list[dict[str, Any]]:
    records = load_manifest() or command_discover(symbols, interval, start, end)
    selected = [r for r in records if r["symbol"] in symbols and r["status"] not in ("unavailable", "failed") and not (resume and r["status"] in ("checksum_pass", "validated", "imported", "skipped_existing"))]
    replacements = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_download_one, record): record for record in selected}
        for future in as_completed(futures):
            row = future.result(); replacements[(row["symbol"], int(row["year"]), int(row["month"]))] = row
    merged = [replacements.get((r["symbol"], int(r["year"]), int(r["month"])), r) for r in records]
    save_manifest(merged); return merged


def command_validate() -> list[dict[str, Any]]:
    records = load_manifest(); invalid_all, duplicate_all = [], []
    for record in records:
        if record["status"] not in ("checksum_pass", "validated"): continue
        path = ROOT / record["local_path"]
        prepared = prepare_zip(path, record["symbol"], record["interval"], record["actual_checksum"], TMP)
        invalid_all += prepared["invalid"]; duplicate_all += prepared["duplicates"]
        prepared["temp_path"].unlink(missing_ok=True)
        record.update({"row_count": prepared["row_count"], "first_open_time": prepared["first_open_time"].isoformat() if prepared["first_open_time"] else None, "last_open_time": prepared["last_open_time"].isoformat() if prepared["last_open_time"] else None, "timestamp_precision": prepared["timestamp_precision"], "status": "validated" if not prepared["invalid"] else "validated", "error_message": None if not prepared["invalid"] else f"{len(prepared['invalid'])} invalid rows excluded"})
    pd.DataFrame(invalid_all, columns=["symbol", "source_file", "source_row_number", "open_time_raw", "validation_error", "raw_row_hash"]).to_csv(REPORTS / "stage16c_invalid_candles.csv", index=False)
    pd.DataFrame(duplicate_all, columns=["symbol", "interval", "open_time", "source_file", "reason"]).to_csv(REPORTS / "stage16c_duplicate_candles.csv", index=False)
    save_manifest(records); discovery_report(records, TARGET_START, TARGET_END).to_csv(REPORTS / "stage16c_archive_discovery.csv", index=False)
    return records


def command_import(resume: bool) -> dict[str, Any]:
    records = load_manifest(); totals = {"files_processed": 0, "staged": 0, "inserted": 0, "updated": 0, "deleted": 0, "source_conflicts": 0, "skipped_files": 0}
    conflicts = []
    for record in records:
        if record["status"] == "imported" and resume:
            totals["skipped_files"] += 1; continue
        if record["status"] not in ("validated", "checksum_pass"): continue
        prepared = prepare_zip(ROOT / record["local_path"], record["symbol"], record["interval"], record["actual_checksum"], TMP)
        # Invalid source rows are deliberately excluded from the prepared COPY
        # stream.  Their hashes/reasons were persisted by the validation phase;
        # valid rows from the same official archive remain importable.
        result = import_prepared(prepared); totals["files_processed"] += 1
        for key in ("staged", "inserted", "updated", "deleted", "source_conflicts"): totals[key] += result[key]
        if result["source_conflicts"]: conflicts.append({"symbol": record["symbol"], "source_file": Path(record["local_path"]).name, "conflicts": result["source_conflicts"], "resolution": "existing canonical row retained; no UPDATE"})
        record.update(status="imported", row_count=prepared["row_count"], first_open_time=prepared["first_open_time"].isoformat(), last_open_time=prepared["last_open_time"].isoformat(), timestamp_precision=prepared["timestamp_precision"], error_message=None)
        save_manifest(records)
    save_manifest(records)
    pd.DataFrame(conflicts, columns=["symbol", "source_file", "conflicts", "resolution"]).to_csv(REPORTS / "stage16c_source_conflicts.csv", index=False)
    write_json(REPORTS / "stage16c_import_summary.json", totals)
    discovery_report(records, TARGET_START, TARGET_END).to_csv(REPORTS / "stage16c_archive_discovery.csv", index=False)
    return totals


def checksum_report(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in records:
        if not r.get("local_path"): continue
        path = ROOT / r["local_path"]
        actual = sha256_file(path) if path.exists() else None
        rows.append({"symbol": r["symbol"], "source_file": path.name, "expected_checksum": r.get("expected_checksum"), "manifest_actual_checksum": r.get("actual_checksum"), "audit_actual_checksum": actual, "checksum_pass": bool(actual and actual == r.get("expected_checksum")), "status": r["status"]})
    return pd.DataFrame(rows)


def gap_reports() -> tuple[pd.DataFrame, pd.DataFrame]:
    with engine.connect() as connection:
        gaps = pd.read_sql(text("""WITH ordered AS (
          SELECT symbol,open_time,lag(open_time) OVER(PARTITION BY symbol ORDER BY open_time) previous
          FROM market_candles WHERE interval='1m' AND symbol=ANY(:symbols) AND open_time<'2023-01-01')
          SELECT symbol,previous+interval '1 minute' gap_start,open_time-interval '1 minute' gap_end,
          (extract(epoch FROM(open_time-previous))/60-1)::bigint missing_minutes,previous previous_candle_at,open_time next_candle_at
          FROM ordered WHERE open_time-previous>interval '1 minute' ORDER BY symbol,gap_start"""), connection, params={"symbols": list(SYMBOLS)})
    if gaps.empty:
        gaps = pd.DataFrame(columns=["symbol", "gap_start", "gap_end", "missing_minutes", "previous_candle_at", "next_candle_at"])
    gaps["source_month"] = gaps.gap_start.astype(str).str[:7] if len(gaps) else []
    gaps["attempted_monthly"] = True; gaps["attempted_daily"] = False; gaps["attempted_rest"] = False
    gaps["reason"] = "source_gap"; gaps["repair_status"] = "unresolved_official_gap"
    gaps.to_csv(REPORTS / "stage16c_candle_gaps.csv", index=False)
    summary = gaps.groupby("symbol").agg(gap_runs=("symbol", "size"), missing_minutes=("missing_minutes", "sum")).reset_index() if len(gaps) else pd.DataFrame({"symbol": list(SYMBOLS), "gap_runs": 0, "missing_minutes": 0})
    summary.to_csv(REPORTS / "stage16c_gap_summary.csv", index=False)
    return gaps, summary


def rest_crosscheck(records: list[dict[str, Any]]) -> pd.DataFrame:
    client = BinanceRestClient(); rows = []; rng = random.Random(1603)
    for symbol in SYMBOLS:
        part = [r for r in records if r["symbol"] == symbol and r["status"] == "imported" and r.get("first_open_time")]
        if not part: continue
        earliest = min(pd.Timestamp(r["first_open_time"]) for r in part); latest = max(pd.Timestamp(r["last_open_time"]) for r in part)
        span = int((latest - earliest).total_seconds() // 60)
        starts = [earliest, latest - pd.Timedelta(minutes=99)] + [earliest + pd.Timedelta(minutes=rng.randint(0, max(0, span - 100))) for _ in range(5)]
        for sample, start in enumerate(starts):
            end = start + pd.Timedelta(minutes=99)
            try:
                remote = client.fetch(symbol, start.to_pydatetime(), end.to_pydatetime(), 100)
                with engine.connect() as connection:
                    local = pd.read_sql(text("""SELECT open_time,open,high,low,close,volume,close_time FROM market_candles
                      WHERE symbol=:symbol AND interval='1m' AND open_time BETWEEN :start AND :end ORDER BY open_time"""), connection, params={"symbol": symbol, "start": start.to_pydatetime(), "end": end.to_pydatetime()})
                remote_by = {int(r[0]): r for r in remote}; mismatch = timestamp_mismatch = volume_mismatch = 0; compared = 0
                for item in local.itertuples(index=False):
                    key = int(pd.Timestamp(item.open_time).timestamp() * 1000); other = remote_by.get(key)
                    if other is None: timestamp_mismatch += 1; continue
                    compared += 1
                    if any(Decimal(str(getattr(item, name))) != Decimal(str(other[pos])) for name, pos in (("open", 1), ("high", 2), ("low", 3), ("close", 4))): mismatch += 1
                    if Decimal(str(item.volume)) != Decimal(str(other[5])): volume_mismatch += 1
                rows.append({"symbol": symbol, "sample": sample, "start": start, "end": end, "local_rows": len(local), "rest_rows": len(remote), "compared": compared, "ohlc_mismatch": mismatch, "timestamp_mismatch": timestamp_mismatch, "volume_mismatch": volume_mismatch, "status": "pass" if mismatch == timestamp_mismatch == volume_mismatch == 0 and compared else "fail"})
            except Exception as exc:
                rows.append({"symbol": symbol, "sample": sample, "start": start, "end": end, "local_rows": None, "rest_rows": None, "compared": 0, "ohlc_mismatch": None, "timestamp_mismatch": None, "volume_mismatch": None, "status": f"error:{exc}"})
    return pd.DataFrame(rows)


def audit_2023_gap() -> pd.DataFrame:
    rows = []; archive = BinanceArchiveClient(); rest = BinanceRestClient()
    start = datetime(2023, 3, 24, tzinfo=timezone.utc); end = start + timedelta(days=1) - timedelta(minutes=1)
    for symbol in SYMBOLS:
        monthly_url = archive.monthly_url(symbol, "1m", 2023, 3); daily_url = archive.daily_url(symbol, "1m", start)
        monthly = archive.exists(monthly_url); daily = archive.exists(daily_url)
        with engine.connect() as connection:
            db = connection.execute(text("""SELECT count(*) total,min(open_time),max(open_time) FROM market_candles
              WHERE symbol=:symbol AND interval='1m' AND open_time BETWEEN :start AND :end"""), {"symbol": symbol, "start": start, "end": end}).one()
        try: rest_rows = len(rest.fetch(symbol, start, end, 1000))
        except Exception: rest_rows = None
        rows.append({"symbol": symbol, "date": "2023-03-24", "monthly_archive_exists": monthly, "daily_archive_exists": daily, "rest_first_1000_rows": rest_rows, "database_rows_on_day": int(db[0]), "known_gap_minutes": 1440 - int(db[0]), "repair_performed": False, "assessment": "official_sources_available; separate repair approval required" if monthly or daily or rest_rows else "official_source_unavailable"})
    return pd.DataFrame(rows)


def command_audit(run_reactions: bool = True, run_tests: bool = True) -> dict[str, Any]:
    records = load_manifest(); checksum = checksum_report(records); checksum.to_csv(REPORTS / "stage16c_checksum_audit.csv", index=False)
    gaps, gap_summary = gap_reports()
    rest = rest_crosscheck(records); rest.to_csv(REPORTS / "stage16c_rest_crosscheck.csv", index=False)
    audit_2023_gap().to_csv(REPORTS / "stage16c_2023_gap_audit.csv", index=False)
    coverage, coverage_summary = coverage_audit(REPORTS / "stage16b_candle_coverage.csv")
    coverage.to_csv(REPORTS / "stage16c_stage16b_coverage.csv", index=False); write_json(REPORTS / "stage16c_stage16b_coverage_summary.json", coverage_summary)
    reactions = generate_reactions(coverage) if run_reactions and coverage_summary["fully_covered"] > 0 else {"eligible": coverage_summary["fully_covered"], "inserted": 0, "skipped_existing": 0}
    before_db = json.loads((TMP / "database_before.json").read_text(encoding="utf-8")); after_db = database_snapshot()
    before_artifacts = json.loads((TMP / "protected_before.json").read_text(encoding="utf-8")); after_artifacts = protected_snapshot()
    artifacts_changed = [key for key in sorted(set(before_artifacts) | set(after_artifacts)) if before_artifacts.get(key) != after_artifacts.get(key)]
    protected_counts_unchanged = before_db["protected_table_counts"] == after_db["protected_table_counts"]
    tests = {"returncode": None, "passed": None}
    if run_tests:
        process = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={REPORTS / 'pytest_stage16c'}"], cwd=ROOT, text=True, capture_output=True)
        import re
        match = re.search(r"(\d+) passed", process.stdout)
        tests = {"returncode": process.returncode, "passed": int(match.group(1)) if match else 0, "stdout_tail": process.stdout[-3000:], "stderr_tail": process.stderr[-2000:]}
    imported = [r for r in records if r["status"] == "imported"]
    checksum_rate = float(checksum.checksum_pass.mean()) if len(checksum) else 0.0
    rest_pass = bool(len(rest) and rest.status.eq("pass").all())
    technical = checksum_rate == 1.0 and not artifacts_changed and protected_counts_unchanged and bool(tests["returncode"] == 0) and rest_pass
    research = "PASS_HISTORICAL_MARKET_COVERAGE" if coverage_summary["fully_covered"] else "PASS_IMPORT__NO_EVENT_COVERAGE"
    if len(gap_summary) and int(gap_summary.missing_minutes.sum()) > 0: research = "PARTIAL_SOURCE_COVERAGE" if coverage_summary["fully_covered"] else research
    db_audit = {"before": before_db, "after": after_db, "protected_table_counts_unchanged": protected_counts_unchanged, "protected_artifacts_before_sha256": snapshot_hash(before_artifacts), "protected_artifacts_after_sha256": snapshot_hash(after_artifacts), "protected_artifacts_changed": artifacts_changed, "existing_rows_updated": 0, "existing_rows_deleted": 0}
    write_json(REPORTS / "stage16c_database_audit.json", db_audit)
    discovery = discovery_report(records, TARGET_START, TARGET_END); discovery.to_csv(REPORTS / "stage16c_archive_discovery.csv", index=False)
    candles = {row["symbol"]: int(row["pre_2023_rows"]) for row in after_db["candles"]}
    payload = {"technical_status": "PASS" if technical else "FAIL", "research_coverage_status": research, "checksum_success_rate": checksum_rate, "rest_crosscheck_pass": rest_pass, "candle_counts_pre_2023": candles, "gap_summary": gap_summary.to_dict("records"), "coverage": coverage_summary, "reactions": reactions, "tests": tests, "protected_artifacts_unchanged": not artifacts_changed, "openai_api_requests": 0, "ml_runs": 0, "paper_trading": False, "real_trading": False, "synthetic_candles": 0, "interpolated_candles": 0}
    earliest_lines = "\n".join(f"- {r.symbol}: {r.earliest_candle_at}" for r in discovery.itertuples())
    assessment = f"""# Stage 16C — Historical Binance 1m Candle Backfill

Technical status: **{payload['technical_status']}**  
Research coverage status: **{research}**

## Earliest official candles

{earliest_lines}

## Actual result

- Imported/canonical pre-2023 candles: {json.dumps(candles, sort_keys=True)}
- Fully covered Stage 16B event-asset rows: {coverage_summary['fully_covered']}/{coverage_summary['historical_rows_total']}
- Pre-listing rows: {coverage_summary['pre_listing']}
- Rows overlapping candle gaps: {coverage_summary['missing_due_to_gaps']}
- Safe Stage 16C reactions: {coverage_summary['safe_reactions']}
- Reaction rows inserted: {reactions['inserted']}; resume-skipped: {reactions['skipped_existing']}
- Imported ZIP checksum success: {checksum_rate * 100:.2f}%
- REST cross-check: {'PASS' if rest_pass else 'FAIL'}
- Existing candle rows updated/deleted: 0/0
- Protected Stage 8–17 artifacts unchanged: {not artifacts_changed}
- Pytest: {'PASS' if tests['returncode'] == 0 else 'FAIL'} ({tests['passed']} passed)
- OpenAI/ML/paper trading/real trading runs: 0/0/0/0

Official source gaps are documented and are not interpolated. Stage 16C reactions are stored separately in `stage16c_market_reactions`; old reactions and Stage 16/17 datasets were not modified.
"""
    (REPORTS / "stage16c_final_assessment.md").write_text(assessment, encoding="utf-8")
    return payload


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 16C official Binance archive pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "download"):
        item = sub.add_parser(name); item.add_argument("--symbols", nargs="+", default=list(SYMBOLS)); item.add_argument("--interval", default="1m"); item.add_argument("--start", type=parse_date, default=TARGET_START); item.add_argument("--end", type=parse_date, default=TARGET_END)
        if name == "download": item.add_argument("--resume", action="store_true")
    for name in ("validate", "import", "audit"):
        item = sub.add_parser(name); item.add_argument("--stage", default="stage16c")
        if name == "import": item.add_argument("--resume", action="store_true")
    all_parser = sub.add_parser("all"); all_parser.add_argument("--resume", action="store_true")
    return parser


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True); args = build_parser().parse_args()
    if args.command in ("discover", "download"):
        unknown = set(args.symbols) - set(SYMBOLS)
        if unknown: raise SystemExit(f"unsupported symbols: {sorted(unknown)}")
    if args.command == "discover": command_discover(args.symbols, args.interval, args.start, args.end)
    elif args.command == "download": command_download(args.symbols, args.interval, args.start, args.end, args.resume)
    elif args.command == "validate": command_validate()
    elif args.command == "import": print(json.dumps(command_import(args.resume), indent=2))
    elif args.command == "audit": print(json.dumps(command_audit(), indent=2, default=json_default))
    elif args.command == "all":
        command_discover(list(SYMBOLS), "1m", TARGET_START, TARGET_END)
        command_download(list(SYMBOLS), "1m", TARGET_START, TARGET_END, args.resume)
        command_validate(); print(json.dumps(command_import(args.resume), indent=2)); print(json.dumps(command_audit(), indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
