from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from hashlib import sha256
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests
USER_AGENT="ETHMarketIntelligenceResearchBot/1.0 contact=research@example.com"
@dataclass(frozen=True)
class PrimarySourceEvent:
    source:str;source_type:str;url:str;title:str;body:str;published_at:datetime
    modified_at:datetime|None=None;canonical_url:str|None=None;author:str|None=None;time_source:str="official_metadata";time_confidence:float=1.0;primary_source:bool=True
    discovered_at:datetime=field(default_factory=lambda:datetime.now(timezone.utc))
    @property
    def content_hash(self):return sha256((self.title.strip()+"\n"+self.body.strip()).encode()).hexdigest()
    def as_dict(self):return {**asdict(self),"content_hash":self.content_hash}
class BasePrimarySource:
    source="base";source_type="project_blog";start_url=""
    def __init__(self,timeout=30):self.timeout=timeout;self.session=requests.Session();self.session.headers.update({"User-Agent":USER_AGENT,"Accept":"text/html,application/xml,application/rss+xml,application/json"})
    def robots_allowed(self,url):
        parsed=urlparse(url);robots=f"{parsed.scheme}://{parsed.netloc}/robots.txt";parser=RobotFileParser(robots)
        try:
            response=self.session.get(robots,timeout=self.timeout)
            if response.status_code==404:return True
            response.raise_for_status();parser.parse(response.text.splitlines());return parser.can_fetch(USER_AGENT,url)
        except Exception:return False
    def get(self,url):
        if not self.robots_allowed(url):raise PermissionError(f"robots.txt disallows {url}")
        response=self.session.get(url,timeout=self.timeout);response.raise_for_status();return response
    def fetch(self,limit=20):raise NotImplementedError
