"""Historical candle import orchestration."""
from datetime import datetime, timedelta
from loguru import logger
from database.db import session_scope
from database.repositories.candle_repository import CandleRepository
from market.binance_client import BinanceClient

def import_candles(symbol: str, start: datetime, end: datetime, interval: str = "1m", client: BinanceClient | None = None, resume: bool = True) -> int:
    if resume:
        with session_scope() as session:
            repository = CandleRepository(session)
            start = repository.resume_open_time(symbol, interval, start, end)
    if start >= end:
        logger.info("No missing {} candles for {} in requested range", interval, symbol)
        return 0
    total = 0; client = client or BinanceClient()
    for batch in client.iter_klines(symbol, interval, start, end):
        with session_scope() as session:
            saved = CandleRepository(session).upsert_batch(symbol, interval, batch)
        total += saved
        logger.info("Imported {} new {} candles for {}; total={}", saved, interval, symbol, total)
    return total
