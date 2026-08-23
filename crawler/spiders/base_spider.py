"""Common sitemap-based news spider."""
from datetime import datetime, timezone
import scrapy
from scrapy import signals
from loguru import logger
from scrapy.spiders import SitemapSpider
from crawler.items import NewsArticleItem
from crawler.parsers.article_parser import parse_article

class BaseNewsSpider(SitemapSpider):
    """Discover article URLs via sitemaps and delegate HTML parsing."""
    source: str = "unknown"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.request_scheduled, signal=signals.request_scheduled)
        return spider

    def request_scheduled(self, request, spider):
        if getattr(request.callback, "__name__", "") == "parse_article_response":
            self.crawler.stats.inc_value("audit/discovered_urls")

    def __init__(self, start: str | None = None, end: str | None = None, symbols: str | None = None, resume: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_date = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else None
        self.end_date = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else None
        self.symbols = set(symbols.split(",")) if symbols else set()
        self.resume = str(resume).lower() not in {"false", "0", "no"}

    def sitemap_filter(self, entries):
        for entry in entries:
            lastmod = entry.get("lastmod")
            if lastmod:
                value = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
                if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
                if self.start_date and value < self.start_date: continue
            yield entry

    def parse_article_response(self, response: scrapy.http.Response):
        try:
            data = parse_article(response.text, response.url, self.source, datetime.now(timezone.utc))
            published_at = data.get("published_at")
            if self.start_date and published_at and published_at < self.start_date:
                self.crawler.stats.inc_value("audit/rejected_articles")
                self.crawler.stats.inc_value("audit/rejection_reasons/date_before_start")
                return
            if self.end_date and published_at and published_at >= self.end_date:
                self.crawler.stats.inc_value("audit/rejected_articles")
                self.crawler.stats.inc_value("audit/rejection_reasons/date_after_end")
                return
            if self.symbols:
                data["assets"] = [asset for asset in data["assets"] if asset["symbol"] in self.symbols]
            yield NewsArticleItem(**data, event_group_id=None, is_valid=True)
        except Exception as exc:
            logger.exception("Article parse failed for {}: {}", response.url, exc)
