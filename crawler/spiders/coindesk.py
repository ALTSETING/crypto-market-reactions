import re
import scrapy
from crawler.spiders.base_spider import BaseNewsSpider

class CoinDeskSpider(BaseNewsSpider):
    name = "coindesk"; source = "coindesk"
    allowed_domains = ["coindesk.com", "www.coindesk.com"]
    sitemap_urls = ["https://www.coindesk.com/sitemap-index.xml"]
    sitemap_rules = [(r"/markets/|/business/|/policy/|/tech/|/web3/", "parse_article_response")]

    async def start(self):
        async for request in super().start():
            yield request
        first_year = self.start_date.year if self.start_date else 2013
        last_year = self.end_date.year if self.end_date else first_year
        for year in range(first_year, last_year + 1):
            yield scrapy.Request(f"https://www.coindesk.com/sitemap/archive/{year}/1", callback=self.parse_archive)

    def parse_archive(self, response):
        article_pattern = re.compile(r"/\d{4}/\d{2}/\d{2}/")
        archive_pattern = re.compile(r"^/sitemap/archive/\d{4}/\d+$")
        for href in set(response.css("a::attr(href)").getall()):
            if article_pattern.search(href):
                yield response.follow(href, callback=self.parse_article_response)
            elif archive_pattern.match(href):
                yield response.follow(href, callback=self.parse_archive)
