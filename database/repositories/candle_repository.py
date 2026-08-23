"""Bulk, idempotent candle persistence."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased
from database.models import MarketCandle

def raw_kline_to_dict(symbol: str, interval: str, row: list) -> dict:
    return {"symbol": symbol, "interval": interval, "open_time": datetime.fromtimestamp(row[0] / 1000, timezone.utc), "close_time": datetime.fromtimestamp(row[6] / 1000, timezone.utc), "open": Decimal(row[1]), "high": Decimal(row[2]), "low": Decimal(row[3]), "close": Decimal(row[4]), "volume": Decimal(row[5])}

class CandleRepository:
    def __init__(self, session: Session): self.session = session
    def latest_open_time(self, symbol: str, interval: str) -> datetime | None:
        return self.session.scalar(select(func.max(MarketCandle.open_time)).where(MarketCandle.symbol == symbol, MarketCandle.interval == interval))

    def earliest_open_time(self, symbol: str, interval: str) -> datetime | None:
        return self.session.scalar(select(func.min(MarketCandle.open_time)).where(MarketCandle.symbol == symbol, MarketCandle.interval == interval))

    def resume_open_time(self, symbol: str, interval: str, start: datetime, end: datetime) -> datetime:
        earliest = self.earliest_open_time(symbol, interval)
        if earliest is None or earliest > start:
            return start
        following = aliased(MarketCandle)
        gap_after = self.session.scalar(
            select(MarketCandle.open_time)
            .where(
                MarketCandle.symbol == symbol,
                MarketCandle.interval == interval,
                MarketCandle.open_time >= start,
                MarketCandle.open_time < end - timedelta(minutes=1),
                ~select(following.id).where(
                    following.symbol == symbol,
                    following.interval == interval,
                    following.open_time == MarketCandle.open_time + timedelta(minutes=1),
                ).exists(),
            )
            .order_by(MarketCandle.open_time)
            .limit(1)
        )
        if gap_after is not None:
            return gap_after + timedelta(minutes=1)
        latest = self.latest_open_time(symbol, interval)
        return min((latest + timedelta(minutes=1)) if latest else start, end)

    def upsert_batch(self, symbol: str, interval: str, rows: list[list]) -> int:
        if not rows: return 0
        values = [raw_kline_to_dict(symbol, interval, row) for row in rows]
        statement = insert(MarketCandle).values(values).on_conflict_do_nothing(index_elements=["symbol", "interval", "open_time"])
        result = self.session.execute(statement)
        return result.rowcount or 0
