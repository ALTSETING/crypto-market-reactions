"""Run one or all production spiders."""
import argparse
from app.config import SUPPORTED_ASSETS
from crawler.runner import SPIDERS, run_spiders

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["all", *SPIDERS], default="all")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="+", default=[item["symbol"] for item in SUPPORTED_ASSETS.values()])
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.start and args.end and args.end <= args.start: parser.error("--end must be later than --start")
    run_spiders(args.source, args.start, args.end, args.symbols, args.resume)

if __name__ == "__main__": main()
