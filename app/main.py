"""Minimal application entry point."""

from app.config import SUPPORTED_ASSETS, settings
from app.logging_config import configure_logging
from database.db import check_database_connection


def main(check_database: bool = False) -> int:
    """Validate configuration and optionally check PostgreSQL connectivity."""

    configure_logging()
    print(f"Configured assets: {', '.join(SUPPORTED_ASSETS)}")
    print(f"Binance endpoint: {settings.binance_base_url}")
    if check_database:
        check_database_connection()
        print("PostgreSQL connection: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
