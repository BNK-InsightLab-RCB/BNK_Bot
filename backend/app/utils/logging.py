"""Logging setup."""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a logger with a simple local-development formatter."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)
