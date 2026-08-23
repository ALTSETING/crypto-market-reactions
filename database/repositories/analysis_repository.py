"""Repository helpers for ETH news analysis persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database.models import NewsArticle, NewsAsset, NewsAnalysis


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_eth_news_candidates(self, limit: int | None = None) -> list[NewsArticle]:
        statement = (
            select(NewsArticle)
            .join(NewsAsset, NewsArticle.id == NewsAsset.news_id)
            .where((NewsAsset.asset == "ETH") | (NewsAsset.symbol == "ETHUSDT"))
            .where(NewsArticle.is_valid.is_(True))
            .options(selectinload(NewsArticle.assets))
            .group_by(NewsArticle.id)
            .order_by(NewsArticle.published_at, NewsArticle.id)
        )
        candidates = list(self.session.scalars(statement).unique().all())

        # URL is already unique in PostgreSQL.  Canonical URL/content hash are
        # de-duplicated defensively without collapsing distinct event-group articles.
        result: list[NewsArticle] = []
        canonical_urls: set[str] = set()
        content_hashes: set[str] = set()
        for article in candidates:
            canonical = (article.canonical_url or "").strip()
            content_hash = (article.content_hash or "").strip()
            if canonical and canonical in canonical_urls:
                continue
            if content_hash and content_hash in content_hashes:
                continue
            if canonical:
                canonical_urls.add(canonical)
            if content_hash:
                content_hashes.add(content_hash)
            result.append(article)
            if limit is not None and len(result) >= limit:
                break
        return result

    def get_successful_analysis_ids(self, model_name: str, prompt_version: str) -> set[int]:
        statement = select(NewsAnalysis.news_id).where(
            NewsAnalysis.asset_focus == "ETH",
            NewsAnalysis.model_name == model_name,
            NewsAnalysis.prompt_version == prompt_version,
            NewsAnalysis.status == "success",
        )
        return set(self.session.scalars(statement).all())

    def get_existing_analysis(self, news_id: int, model_name: str, prompt_version: str) -> NewsAnalysis | None:
        statement = select(NewsAnalysis).where(
            NewsAnalysis.news_id == news_id,
            NewsAnalysis.asset_focus == "ETH",
            NewsAnalysis.model_name == model_name,
            NewsAnalysis.prompt_version == prompt_version,
            NewsAnalysis.status == "success",
        )
        return self.session.scalar(statement)

    def save_analysis(self, analysis: NewsAnalysis) -> NewsAnalysis:
        self.session.add(analysis)
        self.session.commit()
        self.session.refresh(analysis)
        return analysis
