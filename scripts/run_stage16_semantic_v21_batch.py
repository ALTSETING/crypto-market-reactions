"""Submit, watch, import, and audit the single authorized Stage 16 semantic v2.1 Batch."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from database.db import engine, session_scope
from high_impact_sources.analysis.ai_analyzer import (
    PRICES, batch_request, compact_input_v21, dry_run_row, leakage_fields,
    representative_output_tokens, schema_predictive_fields, strict_schema_issues,
    validate_semantic_output,
)
from high_impact_sources.config import PROMPT_VERSION, REPORTS
from high_impact_sources.datasets.dataset_builder import build as build_dataset
from high_impact_sources.models import high_impact_event_analysis
from high_impact_sources.schemas import SEMANTIC_V21_SCHEMA

MODEL = "gpt-5-mini"
MAX_COST_USD = 0.70
MAX_OUTPUT_TOKENS = 350
EXPECTED_EVENTS = 714
JSONL_LIMIT_BYTES = 200 * 1024 * 1024
INPUT_PRICE = PRICES[MODEL]["input"]
OUTPUT_PRICE = PRICES[MODEL]["output"]

JSONL = REPORTS / "stage16_semantic_v21_batch_input.jsonl"
PREFLIGHT = REPORTS / "stage16_semantic_v21_batch_preflight.json"
SUBMISSION = REPORTS / "stage16_semantic_v21_batch_submission.json"
OUTPUT = REPORTS / "stage16_semantic_v21_batch_output.jsonl"
ERRORS = REPORTS / "stage16_semantic_v21_batch_errors.jsonl"
API_STATS = REPORTS / "stage16_semantic_v21_api_stats.json"
RESULTS = REPORTS / "stage16_semantic_v21_results.csv"
FAILURES = REPORTS / "stage16_semantic_v21_failures.csv"
FINAL = REPORTS / "stage16_semantic_v21_final_report.json"
DISTRIBUTIONS = REPORTS / "stage16_semantic_v21_distributions.csv"
ASSET_METRICS = REPORTS / "stage16_semantic_v21_asset_metrics.csv"
AUDIT_CSV = REPORTS / "stage16_semantic_v21_descriptive_audit.csv"
AUDIT_JSON = REPORTS / "stage16_semantic_v21_descriptive_audit.json"
PRESERVED_ARTIFACTS = {
    "stage16_semantic_v1_vs_v2.json": "B060BF7536806512C46B54E61A9E4758E52D9E68FD01DCC24A142A475AE1646A",
    "stage16_semantic_v2_preflight.json": "0BF9C936B28BD13B5F0621273BED1EBBD53C34B8640A3D456C0D17362282A3D3",
    "stage16_ai_semantic_v2_results.csv": "C1C5BB88FCFA6C23094122C7791DF36BEDA46B10AD0AC2917925B0AF6D7C94F1",
    "stage16_ai_semantic_v1_dryrun_comparator.csv": "5B4BEA15807DC6599E32DA97B302AFB2612ABA2F1E4D45710AE1A2D05B39D795",
    "stage16_high_impact_semantic_v2_preflight.jsonl": "FF5E52F42D53A1B35FC5F76568D59E6DF87541A807ECA32628CE33F40CA46CCF",
}

TOP_FIELDS = [
    "event_type", "information_status", "source_reliability", "novelty", "importance",
    "specificity", "confidence", "surprise_level", "surprise_evidence", "first_disclosure",
    "actionability", "institutional_relevance", "retail_relevance", "market_scope",
    "regulatory_strength", "economic_significance", "technical_significance",
    "security_significance", "adoption_significance", "execution_certainty", "urgency",
    "fundamental_relevance", "temporary_vs_structural", "evidence_quality",
]
SCORE_FIELDS = [field for field in TOP_FIELDS if field not in {
    "event_type", "information_status", "surprise_evidence", "first_disclosure",
    "market_scope", "temporary_vs_structural", "evidence_quality",
}]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserved_artifact_check() -> dict[str, Any]:
    actual={name:sha256(REPORTS/name).upper() if (REPORTS/name).exists() else None for name in PRESERVED_ARTIFACTS}
    changed=[name for name,expected in PRESERVED_ARTIFACTS.items() if actual[name]!=expected]
    return {"unchanged":not changed,"changed":changed,"expected":PRESERVED_ARTIFACTS,"actual":actual}


def load_events() -> list[SimpleNamespace]:
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id,source,source_type,platform,author_name,published_at,title,body "
            "FROM high_impact_events WHERE status='accepted' ORDER BY id"
        )).mappings().all()
        asset_rows = connection.execute(text(
            "SELECT event_id,asset FROM high_impact_event_assets ORDER BY event_id,asset"
        )).mappings().all()
    assets: dict[int, list[str]] = {}
    for item in asset_rows:
        assets.setdefault(int(item["event_id"]), []).append(str(item["asset"]))
    return [SimpleNamespace(**dict(row), assets=assets.get(int(row["id"]), [])) for row in rows]


def existing_identity() -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(
            "SELECT event_id,status,batch_id,batch_custom_id FROM high_impact_event_analysis "
            "WHERE model_name=:model AND prompt_version=:version ORDER BY event_id"
        ), {"model": MODEL, "version": PROMPT_VERSION}).mappings()]


def current_preflight(max_cost_usd: float, write_jsonl: bool) -> tuple[list[SimpleNamespace], list[dict[str, Any]], dict[str, Any]]:
    if PROMPT_VERSION != "high_impact_semantic_v2_1":
        raise RuntimeError(f"Unexpected prompt_version: {PROMPT_VERSION}")
    events = load_events()
    identity = existing_identity()
    submitted_batches = sorted({row["batch_id"] for row in identity if row.get("batch_id")})
    existing_submission = read_json(SUBMISSION)
    if submitted_batches and not existing_submission:
        raise RuntimeError(f"Database has an untracked batch: {submitted_batches}")
    success_ids = {int(row["event_id"]) for row in identity if row["status"] == "success"}
    pending = [event for event in events if event.id not in success_ids]
    output_tokens = representative_output_tokens("v21", include_reason=False)
    dry = [dry_run_row(event, MODEL, output_tokens) for event in pending]
    lines = [batch_request(event, MODEL, MAX_OUTPUT_TOKENS) for event in pending]
    custom_ids = [line["custom_id"] for line in lines]
    event_ids = [event.id for event in events]
    pending_ids = [event.id for event in pending]
    leakage = [line["custom_id"] for line in lines if leakage_fields(json.dumps(line, ensure_ascii=False))]
    structural = [line["custom_id"] for line in lines if not (
        line.get("method") == "POST"
        and line.get("url") == "/v1/responses"
        and line.get("body", {}).get("model") == MODEL
        and line.get("body", {}).get("store") is False
        and line.get("body", {}).get("text", {}).get("format", {}).get("strict") is True
        and "reason" not in line.get("body", {}).get("text", {}).get("format", {}).get("schema", {})
    )]
    input_tokens = sum(int(row["input_tokens"]) for row in dry)
    expected_output_tokens = len(pending) * output_tokens
    maximum_output_tokens = len(pending) * MAX_OUTPUT_TOKENS
    estimated_cost = input_tokens / 1_000_000 * INPUT_PRICE + expected_output_tokens / 1_000_000 * OUTPUT_PRICE
    capped_cost = input_tokens / 1_000_000 * INPUT_PRICE + maximum_output_tokens / 1_000_000 * OUTPUT_PRICE
    jsonl_text = "".join(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n" for line in lines)
    jsonl_bytes = len(jsonl_text.encode("utf-8"))
    checks = {
        "selected_events_714": len(events) == EXPECTED_EVENTS,
        "unique_event_id_714": len(set(event_ids)) == EXPECTED_EVENTS,
        "pending_events_714": len(pending) == EXPECTED_EVENTS,
        "unique_pending_event_id_714": len(set(pending_ids)) == EXPECTED_EVENTS,
        "unique_custom_id_714": len(set(custom_ids)) == EXPECTED_EVENTS,
        "duplicates_zero": len(custom_ids) - len(set(custom_ids)) == 0,
        "prompt_version": PROMPT_VERSION == "high_impact_semantic_v2_1",
        "model": MODEL == "gpt-5-mini",
        "strict_schema_issues_zero": not strict_schema_issues(SEMANTIC_V21_SCHEMA),
        "predictive_fields_zero": not schema_predictive_fields(SEMANTIC_V21_SCHEMA),
        "leakage_zero": not leakage,
        "structural_issues_zero": not structural,
        "api_key_present": bool(settings.openai_api_key),
        "estimated_cost_lte_budget": estimated_cost <= max_cost_usd,
        "maximum_token_cap_cost_lte_budget": capped_cost <= max_cost_usd,
        "jsonl_below_limit": jsonl_bytes < JSONL_LIMIT_BYTES,
        "no_existing_submission": not existing_submission and not submitted_batches,
    }
    report = {
        "status": "PREFLIGHT_PASS" if all(checks.values()) else "PREFLIGHT_FAIL",
        "created_at": now(), "api_requests": 0, "api_key_present": bool(settings.openai_api_key),
        "api_key_logged": False, "selected_events": len(events), "unique_event_ids": len(set(event_ids)),
        "already_success": len(success_ids), "submitted_identity_rows": len(identity),
        "pending_events": len(pending), "unique_pending_event_ids": len(set(pending_ids)),
        "unique_custom_ids": len(set(custom_ids)), "duplicates": len(custom_ids)-len(set(custom_ids)),
        "model": MODEL, "prompt_version": PROMPT_VERSION, "include_reason": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS, "strict_schema_issues": strict_schema_issues(SEMANTIC_V21_SCHEMA),
        "predictive_fields": schema_predictive_fields(SEMANTIC_V21_SCHEMA), "leakage_count": len(leakage),
        "leakage_custom_ids": leakage, "structural_failures": structural,
        "estimated_input_tokens": input_tokens, "estimated_output_tokens": expected_output_tokens,
        "maximum_output_tokens_by_request_cap": maximum_output_tokens,
        "estimated_batch_cost_usd": round(estimated_cost, 8),
        "maximum_cost_at_output_token_cap_usd": round(capped_cost, 8),
        "max_cost_usd": max_cost_usd,
        "pricing_usd_per_million": {"input": INPUT_PRICE, "output": OUTPUT_PRICE},
        "jsonl": {"path": str(JSONL.relative_to(REPORTS.parent)), "bytes": jsonl_bytes,
                  "limit_bytes": JSONL_LIMIT_BYTES, "lines": len(lines),
                  "sha256": hashlib.sha256(jsonl_text.encode("utf-8")).hexdigest()},
        "custom_ids_sha256": hashlib.sha256("\n".join(custom_ids).encode()).hexdigest(),
        "input_hashes": {str(row["event_id"]): row["input_hash"] for row in dry},
        "checks": checks,
    }
    if write_jsonl:
        REPORTS.mkdir(parents=True, exist_ok=True)
        JSONL.write_text(jsonl_text, encoding="utf-8", newline="\n")
        if sha256(JSONL) != report["jsonl"]["sha256"]:
            raise RuntimeError("Written JSONL SHA-256 mismatch")
        write_json(PREFLIGHT, report)
    return pending, lines, report


def preflight(max_cost_usd: float) -> dict[str, Any]:
    _events, _lines, report = current_preflight(max_cost_usd, True)
    if report["status"] != "PREFLIGHT_PASS":
        raise RuntimeError("Stage 16 v2.1 preflight failed")
    return report


def mark_submitted(events: list[SimpleNamespace], lines: list[dict[str, Any]], batch_id: str, estimate: dict[str, Any]) -> None:
    line_by_id = {int(line["custom_id"].rsplit("-", 1)[1]): line for line in lines}
    rows = []
    estimated_cost_each = Decimal(str(estimate["estimated_batch_cost_usd"] / len(events)))
    for event in events:
        line = line_by_id[event.id]
        combined = line["body"]["instructions"] + line["body"]["input"] + json.dumps(SEMANTIC_V21_SCHEMA, separators=(",", ":"))
        rows.append({"event_id": event.id, "model_name": MODEL, "prompt_version": PROMPT_VERSION,
                     "input_hash": hashlib.sha256(combined.encode()).hexdigest(),
                     "estimated_cost_usd": estimated_cost_each, "status": "submitted",
                     "batch_id": batch_id, "batch_custom_id": line["custom_id"]})
    statement = pg_insert(high_impact_event_analysis).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_high_impact_analysis_identity",
        set_={"input_hash": statement.excluded.input_hash,
              "estimated_cost_usd": statement.excluded.estimated_cost_usd,
              "status": statement.excluded.status, "batch_id": statement.excluded.batch_id,
              "batch_custom_id": statement.excluded.batch_custom_id},
        where=high_impact_event_analysis.c.status != "success",
    )
    with session_scope() as session:
        session.execute(statement)


def submit(max_cost_usd: float) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing; no API request made")
    existing = read_json(SUBMISSION)
    if existing and existing.get("batch_id"):
        existing["resume_no_new_batch"] = True
        return existing
    events, lines, current = current_preflight(max_cost_usd, False)
    locked = read_json(PREFLIGHT)
    if not locked or locked.get("status") != "PREFLIGHT_PASS":
        raise RuntimeError("Locked preflight missing or failed; no API request made")
    if locked["jsonl"]["sha256"] != sha256(JSONL) or locked["input_hashes"] != current["input_hashes"]:
        raise RuntimeError("Inputs changed after preflight; no API request made")
    client = OpenAI(api_key=settings.openai_api_key, max_retries=2)
    with JSONL.open("rb") as source:
        uploaded = client.files.create(file=source, purpose="batch")
    partial = {"phase": "input_uploaded", "input_file_id": uploaded.id, "batch_id": None,
               "updated_at": now(), "model": MODEL, "prompt_version": PROMPT_VERSION,
               "jsonl_sha256": locked["jsonl"]["sha256"]}
    write_json(SUBMISSION, partial)
    batch = client.batches.create(input_file_id=uploaded.id, endpoint="/v1/responses",
                                  completion_window="24h",
                                  metadata={"stage":"16","prompt_version":PROMPT_VERSION,"semantic_only":"true"})
    report = {
        "phase": "submitted", "submitted_at": now(), "batch_id": batch.id,
        "input_file_id": uploaded.id, "status": batch.status, "selected": locked["selected_events"],
        "submitted": len(events), "model": MODEL, "prompt_version": PROMPT_VERSION,
        "max_cost_usd": max_cost_usd, "estimated_batch_cost_usd": locked["estimated_batch_cost_usd"],
        "maximum_cost_at_output_token_cap_usd": locked["maximum_cost_at_output_token_cap_usd"],
        "jsonl_path": str(JSONL.relative_to(REPORTS.parent)), "jsonl_bytes": JSONL.stat().st_size,
        "jsonl_sha256": sha256(JSONL), "custom_ids_sha256": locked["custom_ids_sha256"],
        "automatic_retry_batch": False, "duplicate_batch_guard": True,
    }
    write_json(SUBMISSION, report)
    mark_submitted(events, lines, batch.id, locked)
    return report


def batch_status() -> dict[str, Any]:
    submission = read_json(SUBMISSION)
    if not submission or not submission.get("batch_id"):
        raise RuntimeError("No batch_id recorded")
    client = OpenAI(api_key=settings.openai_api_key, max_retries=2)
    batch = client.batches.retrieve(submission["batch_id"])
    submission.update({"status": batch.status, "checked_at": now(),
                       "request_counts": batch.request_counts.model_dump() if batch.request_counts else None,
                       "output_file_id": batch.output_file_id, "error_file_id": batch.error_file_id})
    write_json(SUBMISSION, submission)
    return submission


def download(client: OpenAI, file_id: str | None, path: Path) -> None:
    if file_id:
        path.write_bytes(client.files.content(file_id).content)
    elif not path.exists():
        path.write_text("", encoding="utf-8")


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def output_text(body: dict[str, Any]) -> str | None:
    for item in body.get("output", []):
        if item.get("type") != "message": continue
        for content in item.get("content", []):
            if content.get("type") == "output_text": return content.get("text")
    return None


def refusal_text(body: dict[str, Any]) -> str | None:
    for item in body.get("output", []):
        if item.get("type") != "message": continue
        for content in item.get("content", []):
            if content.get("type") == "refusal": return str(content.get("refusal") or "Model refusal")
    return None


def parse_result(line: dict[str, Any], expected: dict[str, int], input_hashes: dict[str, str]) -> dict[str, Any]:
    custom_id = str(line.get("custom_id", ""));event_id = expected.get(custom_id)
    if event_id is None:
        return {"custom_id":custom_id,"event_id":None,"status":"unmatched","error_message":"Unknown custom_id","raw_response_json":line}
    response=line.get("response") or {};body=response.get("body") or {};usage=body.get("usage") or {}
    input_tokens=int(usage.get("input_tokens") or 0);output_tokens=int(usage.get("output_tokens") or 0)
    base={"event_id":event_id,"custom_id":custom_id,"input_hash":input_hashes[str(event_id)],
          "input_tokens":input_tokens,"output_tokens":output_tokens,
          "total_tokens":int(usage.get("total_tokens") or input_tokens+output_tokens),"raw_response_json":line}
    error=line.get("error") or body.get("error")
    if error or response.get("status_code") != 200:
        return base|{"status":"failed","payload":None,"error_message":json.dumps(error or body,ensure_ascii=False)}
    refusal=refusal_text(body)
    if refusal:return base|{"status":"refused","payload":None,"error_message":refusal}
    try:
        payload=json.loads(output_text(body) or "")
        validate_semantic_output(payload,SEMANTIC_V21_SCHEMA)
    except Exception as error_schema:
        return base|{"status":"invalid_schema","payload":None,"error_message":str(error_schema)}
    return base|{"status":"success","payload":payload,"error_message":None}


def persist(results: list[dict[str, Any]], batch_id: str) -> None:
    with engine.connect() as connection:
        success_ids=set(connection.execute(text(
            "SELECT event_id FROM high_impact_event_analysis WHERE model_name=:m AND prompt_version=:p AND status='success'"
        ),{"m":MODEL,"p":PROMPT_VERSION}).scalars())
    rows=[]
    for result in results:
        if result.get("event_id") is None or result["event_id"] in success_ids:continue
        payload=result.get("payload") or {};row={"event_id":result["event_id"],"model_name":MODEL,
            "prompt_version":PROMPT_VERSION,"assets_json":payload.get("assets"),"input_hash":result.get("input_hash"),
            "input_tokens":result.get("input_tokens",0),"output_tokens":result.get("output_tokens",0),
            "total_tokens":result.get("total_tokens",0),
            "actual_cost_usd":Decimal(str(result.get("input_tokens",0)/1_000_000*INPUT_PRICE+result.get("output_tokens",0)/1_000_000*OUTPUT_PRICE)),
            "raw_response_json":result.get("raw_response_json"),"status":result["status"],
            "error_message":result.get("error_message"),"analyzed_at":datetime.now(timezone.utc),
            "batch_id":batch_id,"batch_custom_id":result.get("custom_id")}
        for field in TOP_FIELDS:row[field]=payload.get(field)
        rows.append(row)
    if not rows:return
    statement=pg_insert(high_impact_event_analysis).values(rows)
    excluded=statement.excluded
    updates={column.name:getattr(excluded,column.name) for column in high_impact_event_analysis.c
             if column.name not in {"id","event_id","model_name","prompt_version","estimated_cost_usd"}}
    statement=statement.on_conflict_do_update(constraint="uq_high_impact_analysis_identity",set_=updates,
                                               where=high_impact_event_analysis.c.status!="success")
    with session_scope() as session:session.execute(statement)


def analysis_rows() -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(
            "SELECT * FROM high_impact_event_analysis WHERE model_name=:m AND prompt_version=:p ORDER BY event_id"
        ),{"m":MODEL,"p":PROMPT_VERSION}).mappings()]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None=None) -> None:
    fields=fields or (list(rows[0]) if rows else ["event_id","status","error_message"])
    with path.open("w",newline="",encoding="utf-8-sig") as output:
        writer=csv.DictWriter(output,fieldnames=fields,extrasaction="ignore");writer.writeheader()
        for row in rows:
            writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value for key,value in row.items()})


def distributions_and_assets(successes: list[dict[str, Any]]) -> tuple[dict[str, Any],dict[str, Any]]:
    distribution_fields=("event_type","information_status","evidence_quality","first_disclosure")
    distributions={field:dict(Counter(str(row.get(field) or "null") for row in successes)) for field in distribution_fields}
    dist_rows=[{"distribution":field,"value":value,"count":count} for field,values in distributions.items() for value,count in sorted(values.items())]
    assets=[item for row in successes for item in (row.get("assets_json") or [])]
    valence=dict(Counter(f"{item.get('asset')}:{item.get('content_valence')}" for item in assets))
    asset_rows=[]
    for asset in ("BTC","ETH","SOL"):
        part=[item for item in assets if item.get("asset")==asset]
        asset_rows.append({"asset":asset,"count":len(part),"average_relevance":sum(item.get("relevance",0) for item in part)/len(part) if part else None,
                           **{f"valence_{name}":sum(item.get("content_valence")==name for item in part) for name in ("negative","neutral","positive","mixed")}})
    write_csv(DISTRIBUTIONS,dist_rows);write_csv(ASSET_METRICS,asset_rows)
    return distributions,{"asset_counts":dict(Counter(item.get("asset") for item in assets)),
                          "content_valence_distribution":valence,
                          "average_asset_relevance":sum(item.get("relevance",0) for item in assets)/len(assets) if assets else None}


def descriptive_audit() -> dict[str, Any]:
    with engine.connect() as connection:
        analysis=pd.read_sql(text("SELECT a.*,e.source FROM high_impact_event_analysis a JOIN high_impact_events e ON e.id=a.event_id WHERE a.model_name=:m AND a.prompt_version=:p AND a.status='success'"),connection,params={"m":MODEL,"p":PROMPT_VERSION})
        reactions=pd.read_sql(text("SELECT r.*,e.source FROM high_impact_market_reactions r JOIN high_impact_events e ON e.id=r.event_id WHERE r.latency_minutes=0"),connection)
    rows=[]
    for (source,event_type),part in analysis.groupby(["source","event_type"],dropna=False):rows.append({"section":"source_x_event_type","source":source,"group":event_type,"n":len(part)})
    exploded=[]
    for _,row in analysis.iterrows():
        for item in (row.assets_json or []):exploded.append({"event_id":row.event_id,"source":row.source,**item})
    assets=pd.DataFrame(exploded)
    if len(assets):
        for (source,asset),part in assets.groupby(["source","asset"]):rows.append({"section":"source_x_asset","source":source,"group":asset,"n":len(part)})
    merged=reactions.merge(analysis,on="event_id",how="inner",suffixes=("_reaction","_ai"))
    correlations={}
    for feature in ("importance","novelty","specificity","source_reliability"):
        correlations[feature]={}
        for horizon in ("1m","5m","10m","20m","40m","1h","3h","5h","8h","12h"):
            col=f"return_{horizon}";pair=merged[[feature,col]].dropna()
            value=float(pair[feature].corr(pair[col].abs(),method="spearman")) if len(pair)>1 else None
            correlations[feature][horizon]={"n":len(pair),"spearman_vs_abs_move":value}
            rows.append({"section":"semantic_x_absolute_move","source":feature,"group":horizon,"n":len(pair),"value":value})
    coverage={horizon:{"covered":int(reactions[f"return_{horizon}"].notna().sum()),"total":len(reactions),"rate":float(reactions[f"return_{horizon}"].notna().mean()) if len(reactions) else 0} for horizon in ("1m","5m","10m","20m","40m","1h","3h","5h","8h","12h")}
    for horizon,value in coverage.items():rows.append({"section":"horizon_coverage","source":"all","group":horizon,"n":value["covered"],"value":value["rate"]})
    pre_post={}
    if len(reactions):
        pre=pd.json_normalize(reactions.pre_context_json.apply(lambda value:value or {}))
        for horizon in ("1m","5m","10m","20m","40m","1h"):
            candidates=(f"pre_return_{horizon}",f"return_{horizon}")
            pre_col=next((name for name in candidates if name in pre),None)
            if pre_col:
                pre_values=pd.to_numeric(pre[pre_col],errors="coerce");post_values=pd.to_numeric(reactions[f"return_{horizon}"],errors="coerce")
                pre_post[horizon]={"n":int((pre_values.notna()&post_values.notna()).sum()),"median_abs_pre":float(pre_values.abs().median()),"median_abs_post":float(post_values.abs().median())}
    report={"mode":"descriptive_only","pattern_discovery":False,"ml_tuning":False,"trading":False,
            "source_x_event_type_groups":int(analysis.groupby(["source","event_type"]).ngroups),
            "source_x_asset_groups":int(assets.groupby(["source","asset"]).ngroups) if len(assets) else 0,
            "semantic_vs_absolute_move":correlations,"pre_event_vs_post_event":pre_post,
            "horizon_coverage":coverage,"analysis_events":len(analysis),"reaction_rows":len(reactions)}
    write_csv(AUDIT_CSV,rows);write_json(AUDIT_JSON,report);return report


def run_pytest() -> dict[str, Any]:
    base_temp=REPORTS.parent/"logs"/f"stage16_pytest_{time.time_ns()}"
    completed=subprocess.run([sys.executable,"-m","pytest","-q",f"--basetemp={base_temp}"],cwd=REPORTS.parent,capture_output=True)
    stdout=completed.stdout.decode("utf-8",errors="replace");stderr=completed.stderr.decode("utf-8",errors="replace")
    match=re.search(r"(\d+) passed",stdout)
    return {"returncode":completed.returncode,"passed":int(match.group(1)) if match else 0,
            "failed":0 if completed.returncode==0 else 1,"stdout_tail":stdout[-2000:],"stderr_tail":stderr[-2000:]}


def finalize() -> dict[str, Any]:
    submission=batch_status()
    if submission["status"]!="completed":raise RuntimeError(f"Batch status is {submission['status']}; finalization deferred")
    client=OpenAI(api_key=settings.openai_api_key,max_retries=2)
    download(client,submission.get("output_file_id"),OUTPUT);download(client,submission.get("error_file_id"),ERRORS)
    locked=read_json(PREFLIGHT) or {};input_lines=jsonl_rows(JSONL)
    expected={line["custom_id"]:int(line["custom_id"].rsplit("-",1)[1]) for line in input_lines}
    received=[parse_result(line,expected,locked["input_hashes"]) for line in [*jsonl_rows(OUTPUT),*jsonl_rows(ERRORS)]]
    seen={row["custom_id"] for row in received}
    for custom_id,event_id in expected.items():
        if custom_id not in seen:received.append({"event_id":event_id,"custom_id":custom_id,"status":"missing","payload":None,"input_hash":locked["input_hashes"][str(event_id)],"input_tokens":0,"output_tokens":0,"total_tokens":0,"error_message":"No output or error record","raw_response_json":None})
    persist(received,submission["batch_id"])
    return generate_final_reports(submission,locked)


def generate_final_reports(submission: dict[str,Any],locked: dict[str,Any],*,historical_input_tokens=0,historical_output_tokens=0,extra: dict[str,Any]|None=None) -> dict[str,Any]:
    rows=analysis_rows();successes=[row for row in rows if row["status"]=="success"];failures=[row for row in rows if row["status"]!="success"]
    result_fields=["event_id","status",*TOP_FIELDS,"assets_json","input_tokens","output_tokens","total_tokens","actual_cost_usd","batch_id","batch_custom_id","error_message"]
    write_csv(RESULTS,rows,result_fields);write_csv(FAILURES,failures,result_fields)
    distributions,asset_summary=distributions_and_assets(successes)
    input_tokens=sum(int(row.get("input_tokens") or 0) for row in rows)+historical_input_tokens;output_tokens=sum(int(row.get("output_tokens") or 0) for row in rows)+historical_output_tokens
    actual_cost=input_tokens/1_000_000*INPUT_PRICE+output_tokens/1_000_000*OUTPUT_PRICE
    dataset_manifest=None
    with session_scope() as session:
        _features,_targets,dataset_manifest=build_dataset(session,REPORTS,"stage16_semantic_v21_dataset_manifest.json")
    audit=descriptive_audit();tests=run_pytest()
    snapshot_run=subprocess.run([sys.executable,"-m","scripts.stage16_snapshot"],cwd=REPORTS.parent,capture_output=True)
    snapshot_stdout=snapshot_run.stdout.decode("utf-8",errors="replace")
    try:snapshot=json.loads(snapshot_stdout)
    except json.JSONDecodeError:snapshot={"unchanged":False,"error":snapshot_stdout[-1000:]}
    preserved=preserved_artifact_check()
    counts=Counter(row["status"] for row in rows);schema_rate=len(successes)/len(rows) if rows else 0
    averages={field:(sum(row[field] for row in successes if row.get(field) is not None)/sum(row.get(field) is not None for row in successes) if any(row.get(field) is not None for row in successes) else None) for field in ("importance","novelty","specificity","source_reliability")}
    missing=EXPECTED_EVENTS-len(successes)
    passed=(len(rows)==EXPECTED_EVENTS and missing==0 and schema_rate>=.99 and actual_cost<=MAX_COST_USD
            and not strict_schema_issues(SEMANTIC_V21_SCHEMA) and not schema_predictive_fields(SEMANTIC_V21_SCHEMA)
            and locked.get("leakage_count")==0 and locked.get("duplicates")==0
            and tests["returncode"]==0 and snapshot.get("unchanged") is True and preserved["unchanged"])
    final={"status":"PASS" if passed else "FAIL","completed_at":now(),"batch_id":submission["batch_id"],
        "batch_status":submission["status"],"selected":locked.get("selected_events"),"submitted":locked.get("pending_events"),
        "success":len(successes),"failed":counts["failed"],"invalid_schema":counts["invalid_schema"],
        "refused":counts["refused"],"missing":missing,"documented_non_success":len(failures),
        "schema_success_rate":schema_rate,"input_tokens":input_tokens,"output_tokens":output_tokens,
        "actual_cost_usd":round(actual_cost,8),"average_cost_per_event":round(actual_cost/len(rows),8) if rows else 0,
        "max_cost_usd":MAX_COST_USD,"model":MODEL,"prompt_version":PROMPT_VERSION,
        "duplicates":locked.get("duplicates"),"leakage":locked.get("leakage_count"),
        "predictive_fields":schema_predictive_fields(SEMANTIC_V21_SCHEMA),
        "event_type_distribution":distributions.get("event_type",{}),
        "information_status_distribution":distributions.get("information_status",{}),
        "evidence_quality_distribution":distributions.get("evidence_quality",{}),
        "first_disclosure_distribution":distributions.get("first_disclosure",{}),
        "surprise_null_rate":sum(row.get("surprise_level") is None for row in successes)/len(successes) if successes else None,
        **asset_summary,"average_importance":averages["importance"],"average_novelty":averages["novelty"],
        "average_specificity":averages["specificity"],"average_source_reliability":averages["source_reliability"],
        "resume_no_new_batch":True,"automatic_retry_batch":False,"pytest":tests,
        "stage8_15_unchanged":snapshot,"semantic_v1_v2_artifacts":preserved,"dataset_manifest":dataset_manifest,
        "descriptive_audit":audit,"next_stage_started":False,"paper_or_real_trading":False,**(extra or {})}
    stats={key:final[key] for key in ("batch_id","model","prompt_version","selected","submitted","success","failed","invalid_schema","refused","missing","schema_success_rate","input_tokens","output_tokens","actual_cost_usd","average_cost_per_event")}
    write_json(API_STATS,stats);write_json(FINAL,final);return final


def watch(poll_seconds: int) -> dict[str, Any]:
    while True:
        current=batch_status();print(json.dumps({"checked_at":current["checked_at"],"batch_id":current["batch_id"],"status":current["status"],"request_counts":current.get("request_counts")}),flush=True)
        if current["status"]=="completed":return finalize()
        if current["status"] in {"failed","expired","cancelled"}:
            report={"status":"FAIL","batch_id":current["batch_id"],"batch_status":current["status"],"automatic_retry_batch":False,"checked_at":now()};write_json(FINAL,report);return report
        time.sleep(poll_seconds)


def main() -> None:
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight",action="store_true");mode.add_argument("--submit",action="store_true")
    mode.add_argument("--status",action="store_true");mode.add_argument("--finalize",action="store_true")
    mode.add_argument("--watch",action="store_true")
    parser.add_argument("--max-cost-usd",type=float,default=MAX_COST_USD);parser.add_argument("--poll-seconds",type=int,default=300)
    args=parser.parse_args()
    if args.max_cost_usd>MAX_COST_USD:raise SystemExit("Budget cannot exceed $0.70")
    if args.preflight:result=preflight(args.max_cost_usd)
    elif args.submit:result=submit(args.max_cost_usd)
    elif args.status:result=batch_status()
    elif args.finalize:result=finalize()
    else:result=watch(args.poll_seconds)
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))


if __name__=="__main__":main()
