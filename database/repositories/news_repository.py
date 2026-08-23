"""Persistence operations for news and event grouping."""
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from analysis.event_grouper import new_event_group_id, title_similarity
from database.models import NewsArticle, NewsAsset

class NewsRepository:
    def __init__(self, session: Session): self.session = session

    def _event_group(self, item) -> str:
        since = item["published_at"] - timedelta(hours=24)
        symbols = {asset["symbol"] for asset in item["assets"]}
        candidates = self.session.scalars(select(NewsArticle).join(NewsArticle.assets).where(NewsArticle.published_at >= since, NewsAsset.symbol.in_(symbols))).unique()
        for candidate in candidates:
            if title_similarity(item["title"], candidate.title) >= 0.80:
                return candidate.event_group_id or new_event_group_id()
        return new_event_group_id()

    def add(self, item) -> NewsArticle:
        article = NewsArticle(**{key: item.get(key) for key in ("source", "url", "canonical_url", "title", "body", "author", "published_at", "modified_at", "discovered_at", "crawled_at", "published_at_raw", "time_source", "time_confidence", "content_hash", "is_valid")}, event_group_id=self._event_group(item))
        article.assets = [NewsAsset(**asset) for asset in item["assets"]]
        self.session.add(article); self.session.flush()
        return article
