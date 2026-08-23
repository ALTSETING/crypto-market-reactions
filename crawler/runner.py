"""Programmatic Scrapy runner."""
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from crawler.spiders.coindesk import CoinDeskSpider
from crawler.spiders.cointelegraph import CointelegraphSpider
from crawler.spiders.decrypt import DecryptSpider

SPIDERS = {"coindesk": CoinDeskSpider, "cointelegraph": CointelegraphSpider, "decrypt": DecryptSpider}

def run_spiders(source: str = "all", start: str | None = None, end: str | None = None, symbols: list[str] | None = None, resume: bool = True) -> None:
    process = CrawlerProcess(get_project_settings())
    selected = SPIDERS.values() if source == "all" else [SPIDERS[source]]
    spider_args = {"start": start, "end": end, "symbols": ",".join(symbols or []), "resume": resume}
    for spider in selected: process.crawl(spider, **spider_args)
    process.start()
