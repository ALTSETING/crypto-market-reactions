"""Import free official Stage 16 history with idempotent resume."""
from __future__ import annotations
import argparse,csv,json
from collections import Counter
from datetime import date
from pathlib import Path
from database.db import session_scope
from high_impact_sources.config import REPORTS
from high_impact_sources.parsers.crypto_relevance_detector import detect_crypto_relevance
from high_impact_sources.pipelines.database_pipeline import persist_events
from high_impact_sources.pipelines.duplicate_pipeline import deduplicate
from high_impact_sources.pipelines.event_grouping_pipeline import group_events
from high_impact_sources.pipelines.validation_pipeline import validate_event
from high_impact_sources.registry import REGISTRY,get_source

def parse_date(value):return date.fromisoformat(value) if value else None
def availability_audit():
    rows=[get_source(name).availability() for name in REGISTRY]
    keys=sorted({k for row in rows for k in row})
    REPORTS.mkdir(parents=True,exist_ok=True)
    with (REPORTS/"stage16_source_availability.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(rows)
    (REPORTS/"stage16_source_availability.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding="utf-8")
    return rows

def run(source,start=None,end=None,resume=False,dry_run=False,limit=None,output_report=None):
    adapter=get_source(source); fetched=adapter.fetch(parse_date(start),parse_date(end),limit)
    for event in fetched:
        event.assets,event.crypto_relevance,hits=detect_crypto_relevance(f"{event.title or ''}\n{event.body}")
        event.raw_metadata_json["relevance_hits"]=hits
    unique,in_batch_duplicates=deduplicate(fetched);group_events(unique)
    accepted=[];rejected=[];rejected_events=[]
    for event in unique:
        valid,reason=validate_event(event)
        if valid:accepted.append(event)
        else:
            rejected.append({"url":event.url,"reason":reason})
            if reason=="below_crypto_relevance_threshold":
                event.assets=[];event.raw_metadata_json.update({"status":"rejected","rejection_reason":reason});rejected_events.append(event)
    persistence={"inserted":0,"duplicates":0,"assets_inserted":0}
    if not dry_run:
        with session_scope() as session:persistence=persist_events(session,[*accepted,*rejected_events])
    stats={"source":source,"start":start,"end":end,"resume":resume,"dry_run":dry_run,"fetched":len(fetched),"accepted":len(accepted),"rejected":len(rejected),"rejection_reasons":dict(Counter(x["reason"] for x in rejected)),"in_batch_duplicates":len(in_batch_duplicates),**persistence,"asset_counts":dict(Counter(a for e in accepted for a in e.assets)),"earliest":min((e.published_at.isoformat() for e in fetched),default=None),"latest":max((e.published_at.isoformat() for e in fetched),default=None)}
    path=Path(output_report) if output_report else REPORTS/f"stage16_import_{source}.json"
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False));return stats

def main():
    p=argparse.ArgumentParser();p.add_argument("--source",required=True,choices=REGISTRY);p.add_argument("--start");p.add_argument("--end");p.add_argument("--resume",action="store_true");p.add_argument("--dry-run",action="store_true");p.add_argument("--limit",type=int);p.add_argument("--output-report");args=p.parse_args()
    availability_audit();run(**vars(args))
if __name__=="__main__":main()
