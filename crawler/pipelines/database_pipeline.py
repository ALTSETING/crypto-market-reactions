"""Transactional article persistence pipeline."""
from loguru import logger
from database.db import session_scope
from database.repositories.news_repository import NewsRepository

class DatabasePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(); instance.stats = crawler.stats; return instance

    def process_item(self, item):
        with session_scope() as session:
            article = NewsRepository(session).add(item)
            logger.info("Saved article id={} source={} url={}", article.id, item["source"], item["url"])
            self.stats.inc_value("audit/saved_articles")
        return item
