"""Stage 16 semantic v2 dry-run and local v1/v2 A/B preflight. Never calls OpenAI."""
import argparse,hashlib,json
import pandas as pd
from sqlalchemy import text
from database.db import session_scope
from high_impact_sources.analysis.ai_analyzer import (PRICES,SEMANTIC_V1_PROMPT_VERSION,SEMANTIC_V1_SCHEMA,SEMANTIC_V1_SYSTEM_PROMPT,SEMANTIC_V2_SCHEMA,SEMANTIC_V2_SYSTEM_PROMPT,batch_request,compact_input,dry_run_row,leakage_fields,representative_output_tokens,schema_predictive_fields,strict_schema_issues)
from high_impact_sources.config import REPORTS

PROMPT_VERSION="high_impact_semantic_v2"

def totals(frame):
    input_tokens=int(frame.input_tokens.sum()) if len(frame) else 0;output_tokens=int(frame.estimated_output_tokens.sum()) if len(frame) else 0
    return {"events":len(frame),"input_tokens":input_tokens,"output_tokens":output_tokens,"mean_input_tokens":float(frame.input_tokens.mean()) if len(frame) else 0,"median_input_tokens":float(frame.input_tokens.median()) if len(frame) else 0,"p95_input_tokens":float(frame.input_tokens.quantile(.95)) if len(frame) else 0,"max_input_tokens":int(frame.input_tokens.max()) if len(frame) else 0,"batch_costs":{model:input_tokens/1e6*rates["input"]+output_tokens/1e6*rates["output"] for model,rates in PRICES.items()}}

def main():
    p=argparse.ArgumentParser();p.add_argument("--dry-run",action="store_true",required=True);p.add_argument("--model",default="gpt-5-mini",choices=tuple(PRICES));args=p.parse_args()
    with session_scope() as session:rows=session.execute(text("SELECT id,source,source_type,platform,author_name,published_at,title,body FROM high_impact_events WHERE status='accepted' ORDER BY id")).mappings().all()
    class Obj:
        def __init__(self,d):self.__dict__.update(d);self.assets=[]
    objects=[Obj(dict(row)) for row in rows]
    v1_output=representative_output_tokens("v1");v2_output=representative_output_tokens("v2")
    v1=pd.DataFrame([dry_run_row(row,args.model,v1_output,schema=SEMANTIC_V1_SCHEMA,system_prompt=SEMANTIC_V1_SYSTEM_PROMPT,prompt_version=SEMANTIC_V1_PROMPT_VERSION,input_builder=compact_input) for row in objects])
    v2=pd.DataFrame([dry_run_row(row,args.model,v2_output,schema=SEMANTIC_V2_SCHEMA,system_prompt=SEMANTIC_V2_SYSTEM_PROMPT,prompt_version=PROMPT_VERSION,input_builder=compact_input) for row in objects])
    REPORTS.mkdir(parents=True,exist_ok=True);v2.to_csv(REPORTS/"stage16_ai_results.csv",index=False,encoding="utf-8-sig");v2.to_csv(REPORTS/"stage16_ai_semantic_v2_results.csv",index=False,encoding="utf-8-sig");v1.to_csv(REPORTS/"stage16_ai_semantic_v1_dryrun_comparator.csv",index=False,encoding="utf-8-sig")
    requests=[batch_request(row,args.model,600,schema=SEMANTIC_V2_SCHEMA,system_prompt=SEMANTIC_V2_SYSTEM_PROMPT,prompt_version=PROMPT_VERSION,input_builder=compact_input) for row in objects];custom_ids=[row["custom_id"] for row in requests]
    jsonl_path=REPORTS/f"stage16_{PROMPT_VERSION}_preflight.jsonl";previous_hash=hashlib.sha256(jsonl_path.read_bytes()).hexdigest() if jsonl_path.exists() else None
    jsonl_text="".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in requests);jsonl_path.write_text(jsonl_text,encoding="utf-8");new_hash=hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    parsed=[json.loads(line) for line in jsonl_text.splitlines() if line.strip()];jsonl_leakage=[{"custom_id":row["custom_id"],"fields":leakage_fields(row["body"]["input"])} for row in parsed if leakage_fields(row["body"]["input"])]
    v1_stats=totals(v1);v2_stats=totals(v2)
    v1_top=set(SEMANTIC_V1_SCHEMA["schema"]["properties"]);v2_top=set(SEMANTIC_V2_SCHEMA["schema"]["properties"]);v1_asset=set(SEMANTIC_V1_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"]);v2_asset=set(SEMANTIC_V2_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"])
    comparison={"mode":"local_dry_run_ab","api_requests":0,"same_events":len(v1)==len(v2),"events":len(v2),"model":args.model,"v1":{"prompt_version":SEMANTIC_V1_PROMPT_VERSION,"representative_output_tokens_per_event":v1_output,"schema_strict":not strict_schema_issues(SEMANTIC_V1_SCHEMA),**v1_stats},"v2":{"prompt_version":PROMPT_VERSION,"representative_output_tokens_per_event":v2_output,"schema_strict":not strict_schema_issues(SEMANTIC_V2_SCHEMA),**v2_stats},"delta":{"input_tokens":v2_stats["input_tokens"]-v1_stats["input_tokens"],"output_tokens":v2_stats["output_tokens"]-v1_stats["output_tokens"],"batch_costs":{model:v2_stats["batch_costs"][model]-v1_stats["batch_costs"][model] for model in PRICES}},"new_top_level_fields":sorted(v2_top-v1_top),"new_asset_fields":sorted(v2_asset-v1_asset)}
    report={"status":"PASS","mode":"dry_run","api_requests":0,"batch_uploaded":False,"batch_submitted":False,"events":len(v2),"model":args.model,"prompt_version":PROMPT_VERSION,"schema_strict":not strict_schema_issues(SEMANTIC_V2_SCHEMA),"strict_schema_issues":strict_schema_issues(SEMANTIC_V2_SCHEMA),"nullable_fields":{"regulatory_strength":{"schema_type":["integer","null"],"required":True,"null_allowed":True}},"schema_predictive_fields":schema_predictive_fields(SEMANTIC_V2_SCHEMA),"leakage_violations":int(v2.leakage.sum())+len(jsonl_leakage) if len(v2) else len(jsonl_leakage),"input_tokens":v2_stats["input_tokens"],"estimated_output_tokens":v2_stats["output_tokens"],"token_stats":{key:v2_stats[key] for key in ("mean_input_tokens","median_input_tokens","p95_input_tokens","max_input_tokens")},"estimates":{model:{"input_tokens":v2_stats["input_tokens"],"output_tokens":v2_stats["output_tokens"],"batch_estimated_cost_usd":cost} for model,cost in v2_stats["batch_costs"].items()},"pricing_basis":"official Batch API per-million-token prices checked 2026-07-19","jsonl":{"path":str(jsonl_path),"bytes":jsonl_path.stat().st_size,"sha256":new_hash,"lines":len(parsed),"valid_json_lines":len(parsed),"unique_custom_ids":len(set(custom_ids)),"duplicate_custom_ids":len(custom_ids)-len(set(custom_ids)),"endpoint":"/v1/responses","single_model":len({row['body']['model'] for row in parsed})==1,"deterministic_resume":jsonl_text=="".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in requests),"previous_hash_match":previous_hash in (None,new_hash)},"semantic_only":True,"market_reactions_added_by":"python_after_ai_only","system_prompt":SEMANTIC_V2_SYSTEM_PROMPT,"comparison_report":"stage16_semantic_v1_vs_v2.json"}
    for name in ("stage16_ai_cost_estimate.json","stage16_ai_semantic_preflight.json","stage16_semantic_v2_preflight.json"):(REPORTS/name).write_text(json.dumps(report,indent=2),encoding="utf-8")
    (REPORTS/"stage16_semantic_v1_vs_v2.json").write_text(json.dumps(comparison,indent=2),encoding="utf-8")
    print(json.dumps({"preflight":report,"comparison":comparison}))
if __name__=="__main__":main()
