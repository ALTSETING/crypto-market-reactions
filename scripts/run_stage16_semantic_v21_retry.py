"""Single authorized retry Batch for the 28 truncated Stage 16 v2.1 records."""
from __future__ import annotations
import argparse,hashlib,json,sys,time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openai import OpenAI
from sqlalchemy import text

from app.config import settings
from database.db import engine
from high_impact_sources.analysis.ai_analyzer import (batch_request,dry_run_row,leakage_fields,
    representative_output_tokens,schema_predictive_fields,strict_schema_issues)
from high_impact_sources.config import PROMPT_VERSION,REPORTS
from high_impact_sources.schemas import SEMANTIC_V21_SCHEMA
from scripts.run_stage16_semantic_v21_batch import (MODEL,INPUT_PRICE,OUTPUT_PRICE,MAX_COST_USD,
    PREFLIGHT,FINAL,API_STATS,analysis_rows,batch_status as original_status,download,
    generate_final_reports,jsonl_rows,load_events,mark_submitted,now,parse_result,persist,
    read_json,sha256,write_json)

RETRY_MAX_OUTPUT_TOKENS=400
RETRY_MAX_COST_USD=.03
EXPECTED_RETRY=28
JSONL_LIMIT_BYTES=200*1024*1024
JSONL=REPORTS/"stage16_semantic_v21_retry_input.jsonl"
PREFLIGHT_RETRY=REPORTS/"stage16_semantic_v21_retry_preflight.json"
SUBMISSION_RETRY=REPORTS/"stage16_semantic_v21_retry_batch_submission.json"
OUTPUT_RETRY=REPORTS/"stage16_semantic_v21_retry_output.jsonl"
ERROR_RETRY=REPORTS/"stage16_semantic_v21_retry_errors.jsonl"
STATS_RETRY=REPORTS/"stage16_semantic_v21_retry_api_stats.json"

def status_rows():
    with engine.connect() as c:
        return [dict(x) for x in c.execute(text("SELECT event_id,status,input_tokens,output_tokens,actual_cost_usd FROM high_impact_event_analysis WHERE model_name=:m AND prompt_version=:p ORDER BY event_id"),{"m":MODEL,"p":PROMPT_VERSION}).mappings()]

def current(write_jsonl=False):
    statuses=status_rows();invalid={int(x["event_id"]):x for x in statuses if x["status"]=="invalid_schema"};success={int(x["event_id"]) for x in statuses if x["status"]=="success"}
    events=[x for x in load_events() if x.id in invalid]
    output_estimate=representative_output_tokens("v21",False)
    dry=[dry_run_row(x,MODEL,output_estimate) for x in events]
    lines=[]
    for event in events:
        line=batch_request(event,MODEL,RETRY_MAX_OUTPUT_TOKENS);line["custom_id"]=f"high-impact-semantic-v2-1-retry1-{event.id}";lines.append(line)
    ids=[x.id for x in events];custom=[x["custom_id"] for x in lines]
    leakage=[x["custom_id"] for x in lines if leakage_fields(json.dumps(x,ensure_ascii=False))]
    input_tokens=sum(x["input_tokens"] for x in dry);expected_output=len(events)*output_estimate;max_output=len(events)*RETRY_MAX_OUTPUT_TOKENS
    estimated=input_tokens/1e6*INPUT_PRICE+expected_output/1e6*OUTPUT_PRICE;maximum=input_tokens/1e6*INPUT_PRICE+max_output/1e6*OUTPUT_PRICE
    prior_input=sum(int(x["input_tokens"] or 0) for x in statuses);prior_output=sum(int(x["output_tokens"] or 0) for x in statuses)
    prior_cost=prior_input/1e6*INPUT_PRICE+prior_output/1e6*OUTPUT_PRICE
    text_value="".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in lines);size=len(text_value.encode())
    original=read_json(PREFLIGHT) or {};same_inputs=all(original.get("input_hashes",{}).get(str(x["event_id"]))==x["input_hash"] for x in dry)
    existing=read_json(SUBMISSION_RETRY)
    checks={"retry_selected_28":len(events)==EXPECTED_RETRY,"retry_unique_event_ids_28":len(set(ids))==EXPECTED_RETRY,
        "success_excluded_686":len(success)==686 and not(set(ids)&success),"duplicate_custom_id_zero":len(custom)==len(set(custom)),
        "leakage_zero":not leakage,"predictive_fields_zero":not schema_predictive_fields(SEMANTIC_V21_SCHEMA),
        "strict_schema_issues_zero":not strict_schema_issues(SEMANTIC_V21_SCHEMA),"same_compact_input":same_inputs,
        "model":MODEL=="gpt-5-mini","prompt_version":PROMPT_VERSION=="high_impact_semantic_v2_1",
        "max_output_tokens_400":RETRY_MAX_OUTPUT_TOKENS==400,"estimated_retry_cost_lte_003":estimated<=RETRY_MAX_COST_USD,
        "cumulative_max_cost_lte_070":prior_cost+maximum<=MAX_COST_USD,"jsonl_below_limit":size<JSONL_LIMIT_BYTES,
        "api_key_present":bool(settings.openai_api_key),"no_existing_retry_submission":not(existing and existing.get("batch_id"))}
    report={"status":"PREFLIGHT_PASS" if all(checks.values()) else "PREFLIGHT_FAIL","created_at":now(),"api_requests":0,
        "retry_selected":len(events),"unique_event_ids":len(set(ids)),"success_excluded":len(success),"duplicates":len(custom)-len(set(custom)),
        "model":MODEL,"prompt_version":PROMPT_VERSION,"max_output_tokens":RETRY_MAX_OUTPUT_TOKENS,"include_reason":False,
        "leakage":len(leakage),"predictive_fields":schema_predictive_fields(SEMANTIC_V21_SCHEMA),"strict_schema_issues":strict_schema_issues(SEMANTIC_V21_SCHEMA),
        "estimated_input_tokens":input_tokens,"estimated_output_tokens":expected_output,"maximum_output_tokens":max_output,
        "estimated_retry_cost_usd":round(estimated,8),"maximum_retry_cost_usd":round(maximum,8),
        "prior_actual_cost_usd":round(prior_cost,8),"cumulative_estimated_cost_usd":round(prior_cost+estimated,8),
        "cumulative_maximum_cost_usd":round(prior_cost+maximum,8),"retry_max_cost_usd":RETRY_MAX_COST_USD,"total_max_cost_usd":MAX_COST_USD,
        "prior_invalid_input_tokens":sum(int(x["input_tokens"] or 0) for x in invalid.values()),"prior_invalid_output_tokens":sum(int(x["output_tokens"] or 0) for x in invalid.values()),
        "event_ids":ids,"input_hashes":{str(x["event_id"]):x["input_hash"] for x in dry},"custom_ids":custom,
        "jsonl":{"path":str(JSONL.relative_to(REPORTS.parent)),"bytes":size,"lines":len(lines),"sha256":hashlib.sha256(text_value.encode()).hexdigest()},"checks":checks}
    if write_jsonl:
        JSONL.write_text(text_value,encoding="utf-8",newline="\n");write_json(PREFLIGHT_RETRY,report)
    return events,lines,report

def preflight():
    _,_,report=current(True)
    if report["status"]!="PREFLIGHT_PASS":raise RuntimeError("Retry preflight failed")
    return report

def submit():
    existing=read_json(SUBMISSION_RETRY)
    if existing and existing.get("batch_id"):return existing|{"resume_no_new_batch":True}
    events,lines,report=current(False);locked=read_json(PREFLIGHT_RETRY)
    if not locked or locked["status"]!="PREFLIGHT_PASS" or locked["jsonl"]["sha256"]!=sha256(JSONL) or locked["input_hashes"]!=report["input_hashes"]:raise RuntimeError("Retry inputs changed; no API request made")
    client=OpenAI(api_key=settings.openai_api_key,max_retries=2)
    with JSONL.open("rb") as source:uploaded=client.files.create(file=source,purpose="batch")
    batch=client.batches.create(input_file_id=uploaded.id,endpoint="/v1/responses",completion_window="24h",metadata={"stage":"16","retry":"1","prompt_version":PROMPT_VERSION,"semantic_only":"true"})
    result={"phase":"submitted","submitted_at":now(),"batch_id":batch.id,"input_file_id":uploaded.id,"status":batch.status,
        "retry_selected":len(events),"submitted":len(events),"model":MODEL,"prompt_version":PROMPT_VERSION,"max_output_tokens":RETRY_MAX_OUTPUT_TOKENS,
        "estimated_retry_cost_usd":locked["estimated_retry_cost_usd"],"maximum_retry_cost_usd":locked["maximum_retry_cost_usd"],
        "prior_batch_id":(read_json(REPORTS/"stage16_semantic_v21_batch_submission.json") or {}).get("batch_id"),
        "jsonl_sha256":sha256(JSONL),"automatic_third_batch":False,"duplicate_batch_guard":True}
    write_json(SUBMISSION_RETRY,result)
    estimate={"estimated_batch_cost_usd":locked["estimated_retry_cost_usd"]};mark_submitted(events,lines,batch.id,estimate)
    return result

def retry_status():
    submission=read_json(SUBMISSION_RETRY)
    if not submission or not submission.get("batch_id"):raise RuntimeError("No retry batch recorded")
    batch=OpenAI(api_key=settings.openai_api_key,max_retries=2).batches.retrieve(submission["batch_id"])
    submission.update({"status":batch.status,"checked_at":now(),"request_counts":batch.request_counts.model_dump() if batch.request_counts else None,"output_file_id":batch.output_file_id,"error_file_id":batch.error_file_id});write_json(SUBMISSION_RETRY,submission);return submission

def finalize():
    submission=retry_status()
    if submission["status"]!="completed":raise RuntimeError(f"Retry is {submission['status']}")
    client=OpenAI(api_key=settings.openai_api_key,max_retries=2);download(client,submission.get("output_file_id"),OUTPUT_RETRY);download(client,submission.get("error_file_id"),ERROR_RETRY)
    locked=read_json(PREFLIGHT_RETRY) or {};input_lines=jsonl_rows(JSONL);expected={x["custom_id"]:int(x["custom_id"].rsplit("-",1)[1]) for x in input_lines}
    received=[parse_result(x,expected,locked["input_hashes"]) for x in [*jsonl_rows(OUTPUT_RETRY),*jsonl_rows(ERROR_RETRY)]];seen={x["custom_id"] for x in received}
    for custom_id,event_id in expected.items():
        if custom_id not in seen:received.append({"event_id":event_id,"custom_id":custom_id,"status":"missing","payload":None,"input_hash":locked["input_hashes"][str(event_id)],"input_tokens":0,"output_tokens":0,"total_tokens":0,"error_message":"No retry output/error record","raw_response_json":None})
    persist(received,submission["batch_id"])
    retry_input=sum(x.get("input_tokens",0) for x in received);retry_output=sum(x.get("output_tokens",0) for x in received);counts={name:sum(x["status"]==name for x in received) for name in ("success","failed","invalid_schema","refused","missing")}
    original_locked=read_json(PREFLIGHT) or {};extra={"original_batch_id":submission.get("prior_batch_id"),"retry_batch_id":submission["batch_id"],"retry":{"selected":len(expected),**counts,"input_tokens":retry_input,"output_tokens":retry_output,"actual_cost_usd":round(retry_input/1e6*INPUT_PRICE+retry_output/1e6*OUTPUT_PRICE,8),"max_output_tokens":400,"automatic_third_batch":False,"event_custom_id_mapping_valid":set(expected)=={x["custom_id"] for x in received}},"resume_no_new_retry_batch":True}
    final=generate_final_reports(submission,original_locked,historical_input_tokens=locked["prior_invalid_input_tokens"],historical_output_tokens=locked["prior_invalid_output_tokens"],extra=extra)
    write_json(STATS_RETRY,extra["retry"]|{"batch_id":submission["batch_id"],"cumulative_actual_cost_usd":final["actual_cost_usd"]});return final

def watch(poll):
    while True:
        result=retry_status();print(json.dumps({"checked_at":result["checked_at"],"batch_id":result["batch_id"],"status":result["status"],"request_counts":result.get("request_counts")}),flush=True)
        if result["status"]=="completed":return finalize()
        if result["status"] in {"failed","expired","cancelled"}:
            failure={"status":"FAIL","retry_batch_id":result["batch_id"],"batch_status":result["status"],"automatic_third_batch":False};write_json(FINAL,failure);return failure
        time.sleep(poll)

def main():
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    for name in ("preflight","submit","status","finalize","watch"):mode.add_argument(f"--{name}",action="store_true")
    parser.add_argument("--poll-seconds",type=int,default=30);args=parser.parse_args()
    if args.preflight:result=preflight()
    elif args.submit:result=submit()
    elif args.status:result=retry_status()
    elif args.finalize:result=finalize()
    else:result=watch(args.poll_seconds)
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))

if __name__=="__main__":main()
