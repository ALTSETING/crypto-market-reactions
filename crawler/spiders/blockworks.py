from crawler.spiders.base_spider import BaseNewsSpider

class BlockworksSpider(BaseNewsSpider):
    name = "blockworks"; source = "blockworks"
    allowed_domains = ["blockworks.co"]
    sitemap_urls = ["https://blockworks.co/sitemap.xml"]
    sitemap_rules = [(r"/news/", "parse_article_response")]
