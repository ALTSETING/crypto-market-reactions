from datetime import timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from .base_source import BasePrimarySource,PrimarySourceEvent
class SECSource(BasePrimarySource):
    source="sec";source_type="regulator";start_url="https://www.sec.gov/news/pressreleases.rss"
    def fetch(self,limit=20):
        root=ElementTree.fromstring(self.get(self.start_url).content);events=[]
        for item in root.findall(".//item")[:limit]:
            title=(item.findtext("title") or "").strip();url=(item.findtext("link") or "").strip();body=(item.findtext("description") or "").strip();raw=item.findtext("pubDate")
            if title and url and raw:events.append(PrimarySourceEvent(self.source,self.source_type,url,title,body,parsedate_to_datetime(raw).astimezone(timezone.utc),canonical_url=url,time_source="rss_pubdate"))
        return events
