from datetime import date
from high_impact_sources.parsers.timestamp_parser import parse_timestamp
from high_impact_sources.schemas import HighImpactEvent
from .base_source import BaseSource

class EthereumGitHubSource(BaseSource):
    name="ethereum_github";source_type="github";platform="github";min_interval=1.05
    repos=("ethereum/go-ethereum","ethereum/consensus-specs","ethereum/execution-specs")
    def fetch(self,start: date|None=None,end: date|None=None,limit: int|None=None):
        events=[];remaining=limit
        for repo in self.repos:
            page=1
            while page<=10 and (remaining is None or remaining>0):
                size=min(100,remaining) if remaining else 100
                url=f"https://api.github.com/repos/{repo}/releases?per_page={size}&page={page}"
                rows=self.get(url,api=True).json()
                if not rows:break
                stop=False
                for row in rows:
                    raw=row.get("published_at") or row.get("created_at")
                    if not raw:continue
                    published=parse_timestamp(raw)
                    if start and published.date()<start:stop=True;continue
                    if end and published.date()>end:continue
                    body=(row.get("body") or row.get("name") or row.get("tag_name") or "").strip()
                    events.append(HighImpactEvent(source=self.name,source_type=self.source_type,platform=self.platform,url=row["html_url"],canonical_url=row["html_url"],external_id=str(row["id"]),author_name=(row.get("author") or {}).get("login"),author_handle=(row.get("author") or {}).get("login"),title=f"{repo} {row.get('name') or row.get('tag_name')}",body=body,published_at=published,modified_at=parse_timestamp(row["updated_at"]) if row.get("updated_at") else None,time_source="github_release_published_at",time_confidence=1.0,raw_metadata_json={"repository":repo,"tag_name":row.get("tag_name"),"draft":row.get("draft"),"prerelease":row.get("prerelease")}))
                    if remaining is not None:
                        remaining-=1
                        if remaining<=0:break
                if stop or len(rows)<size:break
                page+=1
        return sorted(events,key=lambda x:x.published_at,reverse=True)
    def availability(self):
        return {**super().availability(),"channels":"official repository releases only (not commits)","history_depth":"paginated release history; up to 10 pages/repository in Phase 1","timestamp_precision":"GitHub API ISO seconds","rate_limit":"60 requests/hour unauthenticated; conditional polling prepared","restrictions":"security advisories may require authenticated scopes; no key used in Phase 1"}
