from __future__ import annotations
import time
from datetime import datetime,timezone
import requests

class BinanceFuturesClient:
    base_url="https://fapi.binance.com"
    def __init__(self,timeout=30,retries=4):
        self.timeout=timeout;self.retries=retries;self.session=requests.Session();self.session.headers["User-Agent"]="ETHMarketIntelligenceResearchBot/1.0"
    def get(self,path,params):
        for attempt in range(self.retries):
            try:
                response=self.session.get(self.base_url+path,params=params,timeout=self.timeout)
                if response.status_code in (418,429):time.sleep(min(2**attempt,15));continue
                response.raise_for_status();return response.json()
            except requests.RequestException:
                if attempt+1==self.retries:raise
                time.sleep(min(2**attempt,10))
        return []
    @staticmethod
    def ms(value:datetime):return int(value.astimezone(timezone.utc).timestamp()*1000)
    def funding(self,symbol,start,end,limit=1000):return self.get("/fapi/v1/fundingRate",{"symbol":symbol,"startTime":self.ms(start),"endTime":self.ms(end),"limit":limit})
    def open_interest(self,symbol,start,end,period="5m",limit=500):return self.get("/futures/data/openInterestHist",{"symbol":symbol,"period":period,"startTime":self.ms(start),"endTime":self.ms(end),"limit":limit})
    def ratio(self,symbol,start,end,ratio_type="global",period="5m",limit=500):
        path={"global":"/futures/data/globalLongShortAccountRatio","top_account":"/futures/data/topLongShortAccountRatio","top_position":"/futures/data/topLongShortPositionRatio"}[ratio_type]
        return self.get(path,{"symbol":symbol,"period":period,"startTime":self.ms(start),"endTime":self.ms(end),"limit":limit})
    def taker(self,symbol,start,end,period="5m",limit=500):return self.get("/futures/data/takerlongshortRatio",{"symbol":symbol,"period":period,"startTime":self.ms(start),"endTime":self.ms(end),"limit":limit})
