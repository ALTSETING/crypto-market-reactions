from crawler.spiders.base_spider import BaseNewsSpider

class DecryptSpider(BaseNewsSpider):
    name = "decrypt"; source = "decrypt"
    allowed_domains = ["decrypt.co"]
    sitemap_urls = ["https://decrypt.co/sitemap_index.xml"]
    sitemap_rules = [(r"decrypt\.co/\d+", "parse_article_response")]
