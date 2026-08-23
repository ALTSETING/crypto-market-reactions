import json
from datetime import timezone
from bs4 import BeautifulSoup
from dateparser import parse as parse_date
from .base_source import BasePrimarySource,PrimarySourceEvent
class BinanceAnnouncementsSource(BasePrimarySource):
    source="binance_announcements";source_type="exchange";start_url="https://www.binance.com/en/support/announcement"
    def fetch(self,limit=20):
        soup=BeautifulSoup(self.get(self.start_url).text,"html.parser");events=[]
        for node in soup.select('script[type="application/ld+json"]'):
            try:data=json.loads(node.string or "{}")
            except json.JSONDecodeError:continue
            for item in data if isinstance(data,list) else [data]:
                title=item.get("headline") or item.get("name");url=item.get("url");raw=item.get("datePublished")
                if not(title and url and raw):continue
                published=parse_date(raw);published=published.replace(tzinfo=published.tzinfo or timezone.utc).astimezone(timezone.utc)
                events.append(PrimarySourceEvent(self.source,self.source_type,url,title,item.get("description",title),published,canonical_url=url,time_source="json_ld"))
                if len(events)>=limit:return events
        return events
