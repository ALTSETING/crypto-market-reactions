"""Non-production one-shot polling preflight. Continuous polling is intentionally disabled."""
import argparse,json
from datetime import datetime,timezone
from high_impact_sources.registry import get_source

def main():
    p=argparse.ArgumentParser();p.add_argument("--source",required=True);p.add_argument("--dry-run",action="store_true",required=True);args=p.parse_args()
    source=get_source(args.source);print(json.dumps({"source":args.source,"mode":"dry_run","production_polling":False,"checked_at":datetime.now(timezone.utc).isoformat(),"availability":source.availability()}))
if __name__=="__main__":main()
