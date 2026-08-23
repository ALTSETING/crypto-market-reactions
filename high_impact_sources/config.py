"""Configuration for the isolated Stage 16 research pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATASETS = ROOT / "datasets" / "stage16_high_impact_semantic_v21"
STAGE16_DATASET_VERSION = "stage16_high_impact_semantic_v21"
USER_AGENT = "HighImpactPrimarySourcesResearch/1.0 contact=research@example.com"
ASSET_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
HORIZONS = {"1m": 1, "5m": 5, "10m": 10, "20m": 20, "40m": 40,
            "1h": 60, "3h": 180, "5h": 300, "8h": 480, "12h": 720}
LATENCIES = (0, 1, 2, 3, 5)
PRE_WINDOWS = (1, 5, 10, 20, 40, 60, 180, 300, 480, 720)
RELEVANCE_THRESHOLD = 0.35
PROMPT_VERSION = "high_impact_semantic_v2_1"
AI_MODEL = "gpt-5-mini"
ALLOWED_DOMAINS = {
    "sec": ("sec.gov", "www.sec.gov", "data.sec.gov"),
    "ethereum_foundation": ("blog.ethereum.org", "ethereum.org"),
    "ethereum_github": ("api.github.com", "github.com"),
    "elon_musk": ("x.com", "api.x.com"),
    "donald_trump": ("truthsocial.com", "www.truthsocial.com"),
}
OFFICIAL_HANDLES = {"elon_musk": "elonmusk", "donald_trump": "realDonaldTrump"}
