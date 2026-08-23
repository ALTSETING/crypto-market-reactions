"""Calculate reactions for news/assets without an existing result."""
import argparse
from datetime import datetime, timezone
from loguru import logger
from database.db import session_scope
from database.repositories.reaction_repository import ReactionRepository

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--start"); parser.add_argument("--end"); parser.add_argument("--source")
    parser.add_argument("--symbols", nargs="+"); parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(); created = 0
    parse_date = lambda value: datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if value else None
    with session_scope() as session:
        repository = ReactionRepository(session)
        while True:
            pending = repository.pending(args.limit, parse_date(args.start), parse_date(args.end), args.source, args.symbols)
            if not pending: break
            batch_created = 0
            for news, symbol in pending:
                if repository.calculate_and_add(news, symbol): created += 1; batch_created += 1
            session.flush()
            if batch_created == 0: break
    logger.info("Calculated {} market reactions", created)

if __name__ == "__main__": main()
