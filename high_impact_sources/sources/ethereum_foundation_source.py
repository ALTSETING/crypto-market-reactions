import json
from datetime import date
from bs4 import BeautifulSoup
from high_impact_sources.parsers.content_cleaner import clean_content
from high_impact_sources.parsers.timestamp_parser import parse_timestamp
from high_impact_sources.schemas import HighImpactEvent
from .base_source import BaseSource

class EthereumFoundationSource(BaseSource):
    name="ethereum_foundation";source_type="protocol";platform="ethereum_blog";min_interval=1.0
    start_url="https://blog.ethereum.org/"
    def fetch(self,start: date|None=None,end: date|None=None,limit: int|None=None):
        soup=BeautifulSoup(self.get(self.start_url).text,"html.parser");links=[]
        for a in soup.select('a[href]'):
            href=a.get("href",""); url=href if href.startswith("http") else "https://blog.ethereum.org"+href
            if url.startswith("https://blog.ethereum.org/") and len(url.split("/"))>=6 and url not in links:links.append(url)
        events=[]
        for url in links:
            if limit and len(events)>=limit:break
            try: page=BeautifulSoup(self.get(url).text,"html.parser")
            except Exception:continue
            posting=None
            for node in page.select('script[type="application/ld+json"]'):
                try:data=json.loads(node.string or "{}")
                except json.JSONDecodeError:continue
                candidates=data.get("@graph",[]) if isinstance(data,dict) else data if isinstance(data,list) else []
                if isinstance(data,dict):candidates=[data,*candidates]
                posting=next((x for x in candidates if isinstance(x,dict) and x.get("@type") in ("BlogPosting","Article")),posting)
            if not posting or not posting.get("datePublished"):continue
            published=parse_timestamp(posting["datePublished"])
            if start and published.date()<start:continue
            if end and published.date()>end:continue
            article=page.select_one("article") or page.select_one("main")
            title=clean_content(str(posting.get("headline") or (page.title.string if page.title else "")))
            body=clean_content(str(article or ""))
            if not body:continue
            events.append(HighImpactEvent(source=self.name,source_type=self.source_type,platform=self.platform,url=url,canonical_url=url,external_id=url.rstrip('/').split('/')[-1],title=title,body=body,published_at=published,modified_at=parse_timestamp(posting["dateModified"]) if posting.get("dateModified") else None,time_source="official_json_ld",time_confidence=.98,raw_metadata_json={"publisher":"Ethereum Foundation Blog"}))
        return events
    def availability(self):
        return {**super().availability(),"channels":"official blog announcements/protocol/security posts","history_depth":"public official archive/index depth","timestamp_precision":"ISO JSON-LD","rate_limit":"polite 1 request/second","restrictions":"robots fail-closed; no protected pages"}
