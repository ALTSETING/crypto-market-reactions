"""Import historical one-minute Binance candles."""
import argparse
from datetime import datetime, timezone
from app.config import SUPPORTED_ASSETS
from market.historical_candles import import_candles

def _date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=_date); parser.add_argument("--end", required=True, type=_date)
    parser.add_argument("--symbols", nargs="+", default=[item["symbol"] for item in SUPPORTED_ASSETS.values()])
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.end <= args.start: parser.error("--end must be later than --start")
    allowed = {item["symbol"] for item in SUPPORTED_ASSETS.values()}
    unknown = set(args.symbols) - allowed
    if unknown: parser.error(f"unsupported symbols: {', '.join(sorted(unknown))}")
    for symbol in args.symbols: import_candles(symbol, args.start, args.end, resume=args.resume)

if __name__ == "__main__": main()
