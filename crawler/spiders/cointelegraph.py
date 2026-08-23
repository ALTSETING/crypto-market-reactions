from crawler.spiders.base_spider import BaseNewsSpider

class CointelegraphSpider(BaseNewsSpider):
    name = "cointelegraph"; source = "cointelegraph"
    allowed_domains = ["cointelegraph.com"]
    sitemap_urls = ["https://cointelegraph.com/sitemap.xml"]
    sitemap_rules = [(r"/news/|/explained/|/magazine/", "parse_article_response")]
