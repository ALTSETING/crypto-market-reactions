"""Reject incomplete or low-confidence articles."""
from scrapy.exceptions import DropItem

class ValidationPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(); instance.stats = crawler.stats; return instance

    def reject(self, reason: str):
        self.stats.inc_value("audit/rejected_articles")
        self.stats.inc_value(f"audit/rejection_reasons/{reason}")
        raise DropItem(reason)

    def process_item(self, item):
        if not item.get("title"): self.reject("missing_title")
        if not item.get("body") or len(item["body"]) < 300: self.reject("body_shorter_than_300")
        if not item.get("published_at"): self.reject("missing_publication_time")
        if float(item.get("time_confidence", 0)) < 0.70: self.reject("low_time_confidence")
        if not item.get("assets"): self.reject("no_supported_assets")
        return item
