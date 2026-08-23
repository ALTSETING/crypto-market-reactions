from crawler.spiders.base_spider import BaseNewsSpider

class CryptoSlateSpider(BaseNewsSpider):
    name = "cryptoslate"; source = "cryptoslate"
    allowed_domains = ["cryptoslate.com"]
    sitemap_urls = ["https://cryptoslate.com/news-sitemap.xml"]
    sitemap_rules = [(r"/news/", "parse_article_response")]
