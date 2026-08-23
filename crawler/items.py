"""Scrapy item definition shared by news sources."""
import scrapy

class NewsArticleItem(scrapy.Item):
    source = scrapy.Field(); url = scrapy.Field(); canonical_url = scrapy.Field()
    title = scrapy.Field(); body = scrapy.Field(); author = scrapy.Field()
    published_at = scrapy.Field(); modified_at = scrapy.Field()
    discovered_at = scrapy.Field(); crawled_at = scrapy.Field()
    published_at_raw = scrapy.Field(); time_source = scrapy.Field()
    time_confidence = scrapy.Field(); content_hash = scrapy.Field()
    event_group_id = scrapy.Field(); is_valid = scrapy.Field(); assets = scrapy.Field()
