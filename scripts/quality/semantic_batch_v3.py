"""Prepare, submit, monitor, and validate the approval-gated V3 semantic batch.

This script never writes production.  Submission is refused when the hard
maximum token cost exceeds the user-approved USD ceiling.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import tiktoken
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/backfill_v3/semantic_batch"
REPORTS = ROOT / "reports"
INPUT_JSONL = OUT / "semantic_v3_requests.jsonl"
MANIFEST = OUT / "semantic_v3_manifest.parquet"
OUTPUT_JSONL = OUT / "semantic_v3_output.jsonl"
RESULTS = OUT / "semantic_v3_results.parquet"
STATUS = REPORTS / "SEMANTIC_BATCH_V3_STATUS.json"
MODEL = "gpt-5-mini"
MAX_OUTPUT_TOKENS = 180
APPROVED_CAP_USD = 0.58
# Official standard rates are $0.25/$2.00 per MTok; Batch is 50% lower.
BATCH_INPUT_USD_PER_M = 0.125
BATCH_OUTPUT_USD_PER_M = 1.00
SYSTEM = (
    "Classify one crypto event using only supplied evidence. Importance is market significance for BTC/ETH/SOL "
    "from 0 to 1, not writing quality. For github_commit or regulatory_filing, sentiment is usually conceptually "
    "not applicable: use sentiment_label=not_applicable and sentiment_score=null unless the evidence clearly "
    "describes directional market impact. Never infer facts absent from the evidence. Keep rationale under 20 words."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment_label": {"type": "string", "enum": ["positive", "negative", "neutral", "mixed", "not_applicable"]},
        "sentiment_score": {"type": ["number", "null"], "minimum": -1, "maximum": 1},
        "importance": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["sentiment_label", "sentiment_score", "importance", "confidence", "rationale"],
    "additionalProperties": False,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    for path in (ROOT / ".env.openai.local", ROOT.parent / ".env.openai.local"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def records() -> pd.DataFrame:
    gaps = pd.read_csv(REPORTS / "SEMANTIC_GAPS_V3.csv")
    inventory = pd.read_parquet(
        ROOT / "data/stage18b/canonical_inventory.parquet", columns=["canonical_event_id", "body"]
    )
    inventory["body"] = inventory.body.fillna("").astype(str)
    inventory["body_chars"] = inventory.body.str.len()
    inventory = inventory.sort_values("body_chars").drop_duplicates("canonical_event_id", keep="last")
    old = gaps.merge(inventory, left_on="event_id", right_on="canonical_event_id", how="left", validate="one_to_one")
    old = old[["event_id", "title", "source", "record_type", "body"]].copy()
    old["dataset_scope"] = "existing_gap"

    candidates = pd.read_parquet(ROOT / "data/backfill_v3/historical_candidates_qa.parquet")
    candidates = candidates[candidates.quality_status.eq("accepted")].copy()
    candidates = candidates.rename(columns={"candidate_id": "event_id"})
    candidates["body"] = ""
    candidates["dataset_scope"] = "new_candidate"
    candidates = candidates[["event_id", "title", "source", "record_type", "body", "dataset_scope"]]
    result = pd.concat([old, candidates], ignore_index=True)
    if len(result) != 1_508 or result.event_id.nunique() != len(result):
        raise RuntimeError("semantic input identity gate failed")
    return result


def prompt(row: Any) -> str:
    body = str(row.body or "")[:10_000]
    return (
        f"event_id: {row.event_id}\nsource: {row.source}\nrecord_type: {row.record_type}\n"
        f"title: {row.title}\nevidence:\n{body or '[title only; no article body retained]'}"
    )


def request(row: Any) -> dict[str, Any]:
    return {
        "custom_id": row.event_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": MODEL,
            "instructions": SYSTEM,
            "input": prompt(row),
            "reasoning": {"effort": "minimal"},
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "text": {"verbosity": "low", "format": {"type": "json_schema", "name": "semantic_v3", "strict": True, "schema": SCHEMA}},
            "store": False,
        },
    }


def token_count(value: dict[str, Any], encoding: Any) -> int:
    # Count serialized request body plus a small fixed message-framing margin.
    return len(encoding.encode(json.dumps(value["body"], ensure_ascii=False, separators=(",", ":")))) + 12


def prepare() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = records()
    encoding = tiktoken.get_encoding("o200k_base")
    requests = [request(row) for row in frame.itertuples(index=False)]
    input_tokens = [token_count(value, encoding) for value in requests]
    hard_max_cost = sum(input_tokens) / 1_000_000 * BATCH_INPUT_USD_PER_M + len(requests) * MAX_OUTPUT_TOKENS / 1_000_000 * BATCH_OUTPUT_USD_PER_M
    if hard_max_cost > APPROVED_CAP_USD:
        raise RuntimeError(f"hard maximum ${hard_max_cost:.4f} exceeds approved ${APPROVED_CAP_USD:.2f}")
    INPUT_JSONL.write_text("".join(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n" for value in requests), encoding="utf-8")
    frame = frame.assign(estimated_input_tokens=input_tokens)
    frame.drop(columns=["body"]).to_parquet(MANIFEST, index=False)
    payload = {
        "status": "prepared_not_submitted",
        "prepared_at": now(),
        "model": MODEL,
        "requests": len(requests),
        "estimated_input_tokens": sum(input_tokens),
        "hard_max_output_tokens": len(requests) * MAX_OUTPUT_TOKENS,
        "estimated_input_cost_usd": round(sum(input_tokens) / 1_000_000 * BATCH_INPUT_USD_PER_M, 6),
        "hard_max_total_cost_usd": round(hard_max_cost, 6),
        "approved_cap_usd": APPROVED_CAP_USD,
        "input_sha256": __import__("hashlib").sha256(INPUT_JSONL.read_bytes()).hexdigest(),
        "production_updated": False,
    }
    STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return payload


def client() -> OpenAI:
    key = load_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)


def submit() -> dict[str, Any]:
    state = prepare()
    if state["hard_max_total_cost_usd"] > APPROVED_CAP_USD:
        raise RuntimeError("approved cost cap exceeded")
    if not load_key():
        state.update({"status": "blocked_missing_api_key", "blocked_at": now(), "required_action": "configure OPENAI_API_KEY"})
        STATUS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(state, indent=2))
        raise RuntimeError("OPENAI_API_KEY is not configured")
    api = client()
    with INPUT_JSONL.open("rb") as source:
        uploaded = api.files.create(file=source, purpose="batch")
    batch = api.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={"job": "news-quality-v3-semantics", "requests": "1508", "cap_usd": "0.58"},
    )
    state.update({
        "status": batch.status,
        "submitted_at": now(),
        "input_file_id": uploaded.id,
        "batch_id": batch.id,
        "request_counts": batch.request_counts.model_dump() if batch.request_counts else None,
    })
    STATUS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, indent=2))
    return state


def poll(verbose: bool = True) -> dict[str, Any]:
    state = json.loads(STATUS.read_text(encoding="utf-8"))
    batch_id = state.get("batch_id")
    if not batch_id:
        raise RuntimeError("no submitted batch_id")
    batch = client().batches.retrieve(batch_id)
    state.update({
        "status": batch.status,
        "polled_at": now(),
        "output_file_id": batch.output_file_id,
        "error_file_id": batch.error_file_id,
        "request_counts": batch.request_counts.model_dump() if batch.request_counts else None,
        "usage": batch.usage.model_dump() if getattr(batch, "usage", None) else None,
    })
    if state.get("usage"):
        usage = state["usage"]
        actual = usage["input_tokens"] / 1_000_000 * BATCH_INPUT_USD_PER_M + usage["output_tokens"] / 1_000_000 * BATCH_OUTPUT_USD_PER_M
        state["actual_estimated_cost_usd"] = round(actual, 6)
        if actual > APPROVED_CAP_USD:
            state["cost_gate"] = "FAIL_OVER_APPROVED_CAP"
    STATUS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(json.dumps(state, indent=2))
    return state


def response_text(body: dict[str, Any]) -> str:
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    raise ValueError("response has no output_text")


def collect() -> dict[str, Any]:
    state = poll(verbose=False)
    if state["status"] != "completed":
        raise RuntimeError(f"batch is {state['status']}, not completed")
    if state.get("cost_gate") == "FAIL_OVER_APPROVED_CAP":
        raise RuntimeError("actual cost exceeds approved cap")
    api = client()
    OUTPUT_JSONL.write_bytes(api.files.content(state["output_file_id"]).read())
    manifest = pd.read_parquet(MANIFEST).set_index("event_id")
    rows, errors = [], []
    for line in OUTPUT_JSONL.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        event_id = item.get("custom_id")
        response = item.get("response") or {}
        if response.get("status_code") != 200:
            errors.append({"event_id": event_id, "error": item.get("error") or response})
            continue
        try:
            value = json.loads(response_text(response["body"]))
            rows.append({"event_id": event_id, **value})
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"event_id": event_id, "error": str(exc)})
    result = pd.DataFrame(rows)
    if errors or len(result) != len(manifest) or result.event_id.nunique() != len(manifest):
        (REPORTS / "SEMANTIC_BATCH_V3_ERRORS.json").write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"semantic response coverage failed: {len(result)}/{len(manifest)}, errors={len(errors)}")
    if not result.importance.between(0, 1).all() or not result.confidence.between(0, 1).all():
        raise RuntimeError("semantic numeric range validation failed")
    applicable = result.sentiment_label.ne("not_applicable")
    if result.loc[applicable, "sentiment_score"].isna().any() or result.loc[~applicable, "sentiment_score"].notna().any():
        raise RuntimeError("semantic sentiment applicability validation failed")
    result = result.merge(manifest.reset_index(), on="event_id", how="left", validate="one_to_one")
    result.to_parquet(RESULTS, index=False)
    state.update({
        "validation_status": "PASS",
        "validated_rows": len(result),
        "existing_gap_rows": int(result.dataset_scope.eq("existing_gap").sum()),
        "new_candidate_rows": int(result.dataset_scope.eq("new_candidate").sum()),
        "validated_at": now(),
        "production_updated": False,
    })
    STATUS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, indent=2))
    return state


def monitor() -> dict[str, Any]:
    while True:
        state = poll(verbose=False)
        counts = state.get("request_counts") or {}
        print(json.dumps({
            "polled_at": state.get("polled_at"), "status": state["status"],
            "completed": counts.get("completed", 0), "failed": counts.get("failed", 0),
            "total": counts.get("total", 0), "estimated_cost_usd": state.get("actual_estimated_cost_usd", 0),
        }), flush=True)
        if state.get("cost_gate") == "FAIL_OVER_APPROVED_CAP":
            raise RuntimeError("actual cost exceeds approved cap; stopped before collection")
        if state["status"] == "completed":
            return collect()
        if state["status"] in {"failed", "expired", "cancelled"}:
            raise RuntimeError(f"batch ended with status {state['status']}")
        time.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "submit", "poll", "collect", "monitor"])
    args = parser.parse_args()
    {"prepare": prepare, "submit": submit, "poll": poll, "collect": collect, "monitor": monitor}[args.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
