"""File + console logging shared by the CLI, the API and the pipeline."""
from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "network_utilization"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"


def setup_logger(log_file: Path, level: int = logging.INFO) -> logging.Logger:
    """Return the project logger, writing to `log_file`. Safe to call repeatedly."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    target = str(log_file.resolve())

    has_file_handler = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == target
        for h in logger.handlers
    )
    if not has_file_handler:
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
