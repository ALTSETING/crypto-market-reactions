import json
from collections import Counter
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from database.db import session_scope
from high_impact_sources.analysis.reaction_calculator import calculate_event_reaction,classify_pre_post
from high_impact_sources.config import ASSET_SYMBOLS,REPORTS
from high_impact_sources.models import high_impact_market_reactions
from ml.stage11_dataset_builder import load_candle_grid

def main():
    with session_scope() as session:
        events=session.execute(text("""SELECT e.id,e.published_at,a.asset FROM high_impact_events e JOIN high_impact_event_assets a ON a.event_id=e.id WHERE e.status='accepted' ORDER BY e.published_at,e.id""")).all()
        grids={symbol:load_candle_grid(session,symbol) for symbol in ASSET_SYMBOLS.values()};btc=grids["BTCUSDT"]
        rows=[];missing=[]
        for event_id,published,asset in events:
            result,reason=calculate_event_reaction(event_id,published,ASSET_SYMBOLS[asset],grids[ASSET_SYMBOLS[asset]],btc);rows.extend(result)
            if reason:missing.append({"event_id":event_id,"asset":asset,"reason":reason})
        if rows:session.execute(insert(high_impact_market_reactions).values(rows).on_conflict_do_update(index_elements=["event_id","symbol","latency_minutes"],set_={c:insert(high_impact_market_reactions).excluded[c] for c in rows[0] if c not in ("event_id","symbol","latency_minutes")}))
    frame=pd.DataFrame(rows);REPORTS.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(REPORTS/"stage16_market_reactions.parquet",index=False)
    comparisons=[]
    for row in rows:
        if row["latency_minutes"]:continue
        pre=row["pre_context_json"].get("pre_return_5m");post=row.get("return_5m")
        if pre is None or post is None:continue
        for threshold in (.10,.25,.50,1.0,2.0):comparisons.append({"event_id":row["event_id"],"symbol":row["symbol"],"threshold_pct":threshold,"pre_return_5m":pre,"post_return_5m":post,"reaction_class":classify_pre_post(pre,post,threshold)})
    pd.DataFrame(comparisons).to_csv(REPORTS/"stage16_pre_post_analysis.csv",index=False,encoding="utf-8-sig")
    stats={"event_assets":len(events),"reaction_rows":len(rows),"by_symbol":dict(Counter(r["symbol"] for r in rows)),"missing_windows":missing,"missing_count":len(missing),"horizons":[1,5,10,20,40,60,180,300,480,720],"latencies":[0,1,2,3,5]}
    (REPORTS/"stage16_reaction_stats.json").write_text(json.dumps(stats,indent=2),encoding="utf-8");print(json.dumps(stats))
if __name__=="__main__":main()
