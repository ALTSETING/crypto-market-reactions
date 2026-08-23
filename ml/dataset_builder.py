"""Build ML-ready tabular datasets from persisted reactions."""
from pathlib import Path
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import NewsArticle, NewsAsset, NewsMarketReaction

DATASET_COLUMNS = ["news_id", "source", "published_at", "asset", "symbol", "title", "body", "time_confidence", "return_5m", "return_15m", "return_30m", "return_1h", "return_4h", "return_24h", "max_return_1h", "min_return_1h", "volume_change_1h"]

def build_dataframe(session: Session) -> pd.DataFrame:
    """Return one row per news/asset reaction."""
    statement = select(NewsArticle.id.label("news_id"), NewsArticle.source, NewsArticle.published_at, NewsAsset.asset, NewsAsset.symbol, NewsArticle.title, NewsArticle.body, NewsArticle.time_confidence, NewsMarketReaction.return_5m, NewsMarketReaction.return_15m, NewsMarketReaction.return_30m, NewsMarketReaction.return_1h, NewsMarketReaction.return_4h, NewsMarketReaction.return_24h, NewsMarketReaction.max_return_1h, NewsMarketReaction.min_return_1h, NewsMarketReaction.volume_change_1h).join(NewsAsset, NewsAsset.news_id == NewsArticle.id).join(NewsMarketReaction, (NewsMarketReaction.news_id == NewsArticle.id) & (NewsMarketReaction.symbol == NewsAsset.symbol)).where(NewsArticle.is_valid.is_(True), NewsArticle.time_confidence >= 0.70).order_by(NewsArticle.published_at)
    rows = session.execute(statement).mappings().all()
    return pd.DataFrame(rows, columns=DATASET_COLUMNS)

def export_dataset(frame: pd.DataFrame, destination: str | Path) -> Path:
    """Export based on .csv or .parquet extension."""
    path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv": frame.to_csv(path, index=False)
    elif path.suffix.lower() in {".parquet", ".pq"}: frame.to_parquet(path, index=False)
    else: raise ValueError("destination must end with .csv, .parquet, or .pq")
    return path
