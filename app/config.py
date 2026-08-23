"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_ASSETS = {
    "BTC": {"symbol": "BTCUSDT", "names": ["bitcoin", "btc", "$btc"]},
    "ETH": {"symbol": "ETHUSDT", "names": ["ethereum", "ether", "eth", "$eth"]},
    "SOL": {"symbol": "SOLUSDT", "names": ["solana", "sol", "$sol"]},
}


class Settings(BaseSettings):
    """Validated runtime settings."""

    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/crypto_news"
    )
    log_level: str = "INFO"
    binance_base_url: str = "https://api.binance.com"
    crawler_user_agent: str = "CryptoNewsResearchBot/1.0"
    openai_api_key: str | None = None
    openai_analysis_model: str = "gpt-5-nano"
    openai_validation_model: str = "gpt-5-mini"
    openai_max_article_tokens: int = 900
    openai_max_output_tokens: int = 140

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()


settings = get_settings()
