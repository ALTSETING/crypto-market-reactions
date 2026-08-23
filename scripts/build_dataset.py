"""Export the current reaction dataset."""
import argparse
from loguru import logger
from database.db import session_scope
from ml.dataset_builder import build_dataframe, export_dataset

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default="datasets/crypto_news.parquet")
    args = parser.parse_args()
    with session_scope() as session: frame = build_dataframe(session)
    path = export_dataset(frame, args.output)
    logger.info("Exported {} rows to {}", len(frame), path)

if __name__ == "__main__": main()
