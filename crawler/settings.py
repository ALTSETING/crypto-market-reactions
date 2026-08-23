"""Polite Scrapy defaults for historical research crawling."""
from app.config import settings as app_settings

BOT_NAME = "crypto_news"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"
ROBOTSTXT_OBEY = True
AUTOTHROTTLE_ENABLED = True
DOWNLOAD_DELAY = 1.5
CONCURRENT_REQUESTS_PER_DOMAIN = 2
RETRY_TIMES = 3
DOWNLOAD_TIMEOUT = 30
HTTPCACHE_ENABLED = True
USER_AGENT = app_settings.crawler_user_agent
ITEM_PIPELINES = {
    "crawler.pipelines.validation_pipeline.ValidationPipeline": 100,
    "crawler.pipelines.duplicate_pipeline.DuplicatePipeline": 200,
    "crawler.pipelines.database_pipeline.DatabasePipeline": 300,
}
LOG_LEVEL = app_settings.log_level
FEED_EXPORT_ENCODING = "utf-8"
EXTENSIONS = {"crawler.extensions.stats_exporter.CrawlStatsExporter": 500}
