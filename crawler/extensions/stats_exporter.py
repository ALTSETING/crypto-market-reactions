"""Persist per-spider Scrapy statistics as JSON."""
import json
from datetime import datetime, timezone
from pathlib import Path
from scrapy import signals

class CrawlStatsExporter:
    def __init__(self, stats): self.stats = stats
    @classmethod
    def from_crawler(cls, crawler):
        extension = cls(crawler.stats)
        crawler.signals.connect(extension.spider_closed, signal=signals.spider_closed)
        return extension
    def spider_closed(self, spider, reason):
        output = Path("reports"); output.mkdir(parents=True, exist_ok=True)
        data = dict(self.stats.get_stats())
        data.update({"source": spider.source, "finish_reason": reason, "exported_at": datetime.now(timezone.utc).isoformat()})
        serializable = {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in data.items()}
        (output / f"crawl_stats_{spider.source}.json").write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")
