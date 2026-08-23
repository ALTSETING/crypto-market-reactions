import json
from datetime import timezone
from bs4 import BeautifulSoup
from dateparser import parse as parse_date
from .base_source import BasePrimarySource,PrimarySourceEvent
class EthereumFoundationSource(BasePrimarySource):
    source="ethereum_foundation";source_type="protocol";start_url="https://blog.ethereum.org/"
    def fetch(self,limit=20):
        soup=BeautifulSoup(self.get(self.start_url).text,"html.parser");events=[];seen=set()
        for link in soup.select('a[href^="/"]'):
            href=link.get("href","");url="https://blog.ethereum.org"+href
            if url in seen or len(href.split("/"))<4:continue
            seen.add(url)
            try:
                page=BeautifulSoup(self.get(url).text,"html.parser");body=page.select_one("article") or page.select_one("main");posting=None
                for node in page.select('script[type="application/ld+json"]'):
                    data=json.loads(node.string or "{}")
                    for item in data.get("@graph",[]) if isinstance(data,dict) else []:
                        if item.get("@type")=="BlogPosting":posting=item;break
                if not posting or not body:continue
                published=parse_date(posting["datePublished"]);published=published.replace(tzinfo=published.tzinfo or timezone.utc).astimezone(timezone.utc)
                modified=parse_date(posting.get("dateModified")) if posting.get("dateModified") else None
                if modified:modified=modified.replace(tzinfo=modified.tzinfo or timezone.utc).astimezone(timezone.utc)
                events.append(PrimarySourceEvent(self.source,self.source_type,url,posting["headline"],body.get_text(" ",strip=True),published,modified_at=modified,canonical_url=url,time_source="json_ld"))
            except Exception:continue
            if len(events)>=limit:break
        return events
