import argparse,json
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from database.db import SessionLocal
from market_intelligence.models import primary_source_events,event_information_timeline
from market_intelligence.primary_sources import source_registry
from market_intelligence.timing.first_information_detector import match_primary_to_media

def main():
 p=argparse.ArgumentParser();p.add_argument("--sources",nargs="+",default=list(source_registry));p.add_argument("--limit",type=int,default=20);a=p.parse_args();stats=[]
 with SessionLocal() as s:
  for name in a.sources:
   adapter=source_registry[name]();events=[];error=None
   try:events=adapter.fetch(a.limit)
   except Exception as exc:error=f"{type(exc).__name__}: {exc}"
   relevant=[]
   for event in events:
    text_value=(event.title+" "+event.body).lower()
    if name=="ethereum_foundation" or any(word in text_value for word in ("ethereum","ether"," eth ","etf")):relevant.append(event)
   for event in relevant:
    data=event.as_dict();data.pop("author",None);data.pop("primary_source",None);data.update({"assets_json":'["ETH"]',"is_valid":True})
    s.execute(insert(primary_source_events).values(data).on_conflict_do_nothing())
   s.commit();stats.append({"source":name,"tested":True,"fetched":len(events),"eth_relevant":len(relevant),"error":error or ""})
  primary=pd.read_sql(text("SELECT id,source,source_type,title,published_at FROM primary_source_events ORDER BY published_at"),s.connection())
  media=pd.read_sql(text("SELECT e.event_key,e.news_id,n.title,e.published_at,e.article_count_in_event FROM (SELECT * FROM (VALUES (NULL)) v(x) WHERE false) z RIGHT JOIN news_articles n ON false"),s.connection()) if False else pd.read_parquet("reports/stage12_eth_event_index.parquet").query("coverage_status == 'included'")
  titles=pd.read_sql(text("SELECT id AS news_id,title FROM news_articles"),s.connection());media=media.merge(titles,on="news_id",validate="one_to_one")
  primary["published_at"]=pd.to_datetime(primary.published_at,utc=True);media["published_at"]=pd.to_datetime(media.published_at,utc=True)
  matches=match_primary_to_media(primary,media)
  match_map=matches.set_index("event_key").to_dict("index") if not matches.empty else {}
  primary_by_id=primary.set_index("id") if not primary.empty else primary
  for row in media.itertuples(index=False):
   match=match_map.get(row.event_key);primary_row=primary_by_id.loc[match["primary_id"]] if match else None
   primary_time=pd.Timestamp(primary_row.published_at).to_pydatetime() if match else None;media_time=pd.Timestamp(row.published_at).to_pydatetime()
   values={"event_key":row.event_key,"earliest_primary_news_id":int(match["primary_id"]) if match else None,"earliest_media_news_id":int(row.news_id),"earliest_information_time":min(primary_time,media_time) if primary_time else media_time,"primary_source_time":primary_time,"media_source_time":media_time,"delay_seconds":int((media_time-primary_time).total_seconds()) if primary_time else None,"source_count":2 if match else 1,"article_count":int(row.article_count_in_event),"grouping_method":"tfidf_title_asset_time" if match else "media_event_only","grouping_confidence":float(match["similarity"]) if match else 0.0}
   base=insert(event_information_timeline);s.execute(base.values(values).on_conflict_do_update(index_elements=["event_key"],set_={key:getattr(base.excluded,key) for key in values if key!="event_key"}))
  s.commit()
 Path("reports").mkdir(exist_ok=True);pd.DataFrame(stats).to_csv("reports/stage135_primary_source_stats.csv",index=False)
 print(json.dumps({"sources":stats,"stored":len(primary),"timeline_rows":len(media),"primary_matches":len(matches)},indent=2))
if __name__=="__main__":main()
