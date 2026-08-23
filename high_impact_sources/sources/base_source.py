"""Fail-closed official-source HTTP adapter base."""
from __future__ import annotations
import time
from datetime import date
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests
from high_impact_sources.config import ALLOWED_DOMAINS, USER_AGENT

class BaseSource:
    name="base"; source_type="other"; platform="other_official"; min_interval=1.0
    def __init__(self, timeout: int=30):
        self.timeout=timeout; self.session=requests.Session(); self._last=0.0
        self.session.headers.update({"User-Agent":USER_AGENT,"Accept":"application/json,application/xml,text/html;q=0.9"})
    def official_url(self,url: str) -> bool:
        return (urlparse(url).hostname or "").lower() in ALLOWED_DOMAINS.get(self.name,())
    def robots_allowed(self,url: str) -> bool:
        if not self.official_url(url): return False
        parsed=urlparse(url); robots=f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response=self.session.get(robots,timeout=self.timeout)
            if response.status_code==404:return True
            response.raise_for_status(); parser=RobotFileParser();parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT,url)
        except requests.RequestException:return False
    def get(self,url: str, *, api: bool=False, headers: dict|None=None):
        if not self.official_url(url):raise PermissionError(f"non-official domain: {url}")
        if not api and not self.robots_allowed(url):raise PermissionError(f"robots.txt blocks or could not be verified: {url}")
        wait=self.min_interval-(time.monotonic()-self._last)
        if wait>0:time.sleep(wait)
        response=self.session.get(url,headers=headers or {},timeout=self.timeout);self._last=time.monotonic();response.raise_for_status();return response
    def fetch(self,start: date|None=None,end: date|None=None,limit: int|None=None):raise NotImplementedError
    def availability(self) -> dict:return {"source":self.name,"status":"available","free_or_paid":"free","estimated_cost_usd":0.0}
