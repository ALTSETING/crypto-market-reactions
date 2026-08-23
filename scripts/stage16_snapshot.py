"""Record and verify that Stage 8-15 artifacts and legacy DB tables remain unchanged."""
import hashlib,json
from pathlib import Path
from sqlalchemy import inspect,text
from database.db import engine

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"reports"/"stage16_preflight_snapshot.json"
PATTERNS=("stage8*","stage9*","stage10*","stage11*","stage12*","stage13*","stage13a*","stage135*","stage14*","stage15*")
LEGACY=("news_articles","news_assets","market_candles","news_market_reactions","news_analysis","news_market_context_analysis","news_early_reactions","primary_source_events","event_information_timeline","futures_funding_rates","futures_open_interest","futures_long_short_ratios","futures_taker_volume","macro_market_data","onchain_metrics","etf_market_data")
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def capture():
    files={}
    for folder in (ROOT/"reports",ROOT/"data",ROOT/"datasets",ROOT/"patterns",ROOT/"models"):
        if not folder.exists():continue
        for path in folder.rglob("*"):
            if path.is_file() and (folder.name in ("patterns","models") or any(path.name.startswith(p[:-1]) for p in PATTERNS)):files[str(path.relative_to(ROOT))]=digest(path)
    counts={}
    with engine.connect() as c:
        existing=set(inspect(c).get_table_names())
        for table in LEGACY:
            if table in existing:counts[table]=c.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()
    return {"files":files,"legacy_counts":counts}
def main():
    current=capture()
    if OUT.exists():
        previous=json.loads(OUT.read_text(encoding="utf-8"));changed=[k for k,v in previous["files"].items() if current["files"].get(k)!=v];counts={k:[v,current["legacy_counts"].get(k)] for k,v in previous["legacy_counts"].items() if current["legacy_counts"].get(k)!=v};print(json.dumps({"unchanged":not changed and not counts,"changed_files":changed,"changed_counts":counts},indent=2));return
    OUT.write_text(json.dumps(current,indent=2),encoding="utf-8");print(json.dumps({"captured_files":len(current["files"]),"legacy_counts":current["legacy_counts"]},indent=2))
if __name__=="__main__":main()
