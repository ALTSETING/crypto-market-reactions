"""Central Loguru configuration."""

import sys

from loguru import logger

from app.config import settings


def configure_logging() -> None:
    """Configure consistent console logging for commands and services."""

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
