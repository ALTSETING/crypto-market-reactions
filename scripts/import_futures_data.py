import argparse,json
from datetime import datetime,timedelta,timezone
from database.db import SessionLocal
from market_intelligence.futures import BinanceFuturesClient
from market_intelligence.futures.importers import import_funding,import_open_interest,import_long_short,import_taker
def dt(value):return datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if "+" not in value and not value.endswith("Z") else datetime.fromisoformat(value.replace("Z","+00:00"))
def main():
 p=argparse.ArgumentParser();p.add_argument("--start",required=True);p.add_argument("--end",required=True);p.add_argument("--symbols",nargs="+",default=["ETHUSDT","BTCUSDT"]);p.add_argument("--resume",action="store_true");a=p.parse_args();start,end=dt(a.start),dt(a.end);stats={};client=BinanceFuturesClient()
 # Official statistics endpoints expose only the latest 30 days.
 # Keep a one-day safety margin inside Binance's rolling latest-30-days boundary.
 stats_start=max(start,datetime.now(timezone.utc)-timedelta(days=29))
 with SessionLocal() as s:
  for symbol in a.symbols:
   stats[symbol]={"funding":import_funding(s,client,symbol,start,end,a.resume),"open_interest":import_open_interest(s,client,symbol,stats_start,end,a.resume) if stats_start<=end else 0,"long_short":import_long_short(s,client,symbol,stats_start,end,a.resume) if stats_start<=end else 0,"taker":import_taker(s,client,symbol,stats_start,end,a.resume) if stats_start<=end else 0}
 print(json.dumps(stats,indent=2))
if __name__=="__main__":main()
