"""Logging setup.

The alert scheduler runs in the background with no user watching, so when it
fires something that needs to be visible — especially once this lives on a
Raspberry Pi and the only evidence is the log.
"""

from __future__ import annotations

import logging

LOGGER_NAME = "jarlog"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Give jar-log's own logger a destination, whoever is hosting us.

    Uvicorn configures its own loggers and leaves the root logger bare, so
    without this the scheduler's output goes nowhere.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT))
        logger.addHandler(handler)
        # We have our own handler; don't also print via root if one appears.
        logger.propagate = False

    return logger
