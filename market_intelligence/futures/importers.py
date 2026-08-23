from __future__ import annotations
from datetime import datetime,timedelta,timezone
from sqlalchemy import func,select
from sqlalchemy.dialects.postgresql import insert
from market_intelligence.models import futures_funding_rates,futures_open_interest,futures_long_short_ratios,futures_taker_volume
from .binance_futures_client import BinanceFuturesClient

def _dt(ms):return datetime.fromtimestamp(int(ms)/1000,tz=timezone.utc)
def _upsert(session,table,rows,keys):
    if not rows:return 0
    base=insert(table)
    statement=base.values(rows).on_conflict_do_update(index_elements=keys,set_={c.name:getattr(base.excluded,c.name) for c in table.columns if c.name not in {"id","created_at",*keys}})
    session.execute(statement);session.commit();return len(rows)
def _resume(session,table,column,symbol,start,step):
    latest=session.scalar(select(func.max(column)).where(table.c.symbol==symbol));return max(start,latest+step) if latest else start

def import_funding(session,client:BinanceFuturesClient,symbol,start,end,resume=True):
    cursor=_resume(session,futures_funding_rates,futures_funding_rates.c.funding_time,symbol,start,timedelta(milliseconds=1)) if resume else start;count=0
    while cursor<=end:
        batch=[item for item in client.funding(symbol,cursor,end) if cursor<=_dt(item["fundingTime"])<=end];rows=[{"symbol":item["symbol"],"funding_time":_dt(item["fundingTime"]),"funding_rate":item["fundingRate"],"mark_price":item.get("markPrice") or None} for item in batch]
        count+=_upsert(session,futures_funding_rates,rows,["symbol","funding_time"])
        if not batch or len(batch)<1000:break
        cursor=_dt(batch[-1]["fundingTime"])+timedelta(milliseconds=1)
    return count

def _paged_stats(session,client,symbol,start,end,kind,period="5m",resume=True):
    table,column={"oi":(futures_open_interest,futures_open_interest.c.timestamp),"taker":(futures_taker_volume,futures_taker_volume.c.timestamp),"global":(futures_long_short_ratios,futures_long_short_ratios.c.timestamp),"top_account":(futures_long_short_ratios,futures_long_short_ratios.c.timestamp),"top_position":(futures_long_short_ratios,futures_long_short_ratios.c.timestamp)}[kind]
    if resume:
        query=select(func.max(column)).where(table.c.symbol==symbol)
        if "period" in table.c:query=query.where(table.c.period==period)
        if kind in ("global","top_account","top_position"):query=query.where(table.c.ratio_type==kind)
        latest=session.scalar(query);cursor=max(start,latest+timedelta(minutes=5)) if latest else start
    else:cursor=start
    count=0
    while cursor<=end:
        window_end=min(end,cursor+timedelta(minutes=5*499))
        batch=client.open_interest(symbol,cursor,window_end,period) if kind=="oi" else client.taker(symbol,cursor,window_end,period) if kind=="taker" else client.ratio(symbol,cursor,window_end,kind,period)
        batch=[item for item in batch if cursor<=_dt(item["timestamp"])<=window_end]
        if kind=="oi":rows=[{"symbol":symbol,"timestamp":_dt(x["timestamp"]),"open_interest":x["sumOpenInterest"],"open_interest_value":x.get("sumOpenInterestValue"),"period":period} for x in batch];keys=["symbol","timestamp","period"]
        elif kind=="taker":rows=[{"symbol":symbol,"timestamp":_dt(x["timestamp"]),"buy_sell_ratio":x["buySellRatio"],"buy_volume":x.get("buyVol"),"sell_volume":x.get("sellVol"),"period":period} for x in batch];keys=["symbol","timestamp","period"]
        else:rows=[{"symbol":symbol,"timestamp":_dt(x["timestamp"]),"ratio_type":kind,"long_account":x.get("longAccount"),"short_account":x.get("shortAccount"),"long_short_ratio":x["longShortRatio"],"period":period} for x in batch];keys=["symbol","timestamp","ratio_type","period"]
        count+=_upsert(session,table,rows,keys);cursor=window_end+timedelta(milliseconds=1)
    return count
def import_open_interest(session,client,symbol,start,end,resume=True):return _paged_stats(session,client,symbol,start,end,"oi",resume=resume)
def import_long_short(session,client,symbol,start,end,resume=True):return sum(_paged_stats(session,client,symbol,start,end,k,resume=resume) for k in ("global","top_account","top_position"))
def import_taker(session,client,symbol,start,end,resume=True):return _paged_stats(session,client,symbol,start,end,"taker",resume=resume)
