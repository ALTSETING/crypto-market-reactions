"""Database-backed exact duplicate filtering."""
from sqlalchemy import or_, select
from scrapy.exceptions import DropItem
from database.db import session_scope
from database.models import NewsArticle

class DuplicatePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(); instance.stats = crawler.stats; return instance

    def process_item(self, item):
        conditions = [NewsArticle.url == item["url"], NewsArticle.content_hash == item["content_hash"]]
        if item.get("canonical_url"):
            conditions.append(NewsArticle.canonical_url == item["canonical_url"])
        with session_scope() as session:
            if session.scalar(select(NewsArticle.id).where(or_(*conditions)).limit(1)):
                self.stats.inc_value("audit/duplicates")
                raise DropItem("duplicate URL, canonical URL, or content hash")
        return item
