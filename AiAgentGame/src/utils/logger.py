"""
Logging configuration for AI Agent Game Creator.
"""

import logging
import sys
from pathlib import Path


def setup_logger(name: str = "game_creator", level: int = logging.INFO) -> logging.Logger:
    """
    Setup and return a configured logger.

    Args:
        name: Logger name
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Format: [TIME] LEVEL - message
    formatter = logging.Formatter(
        fmt='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.propagate = False

    return logger


def get_logger(name: str = "game_creator") -> logging.Logger:
    """
    Get an existing logger or create a new one.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Default logger instance
logger = setup_logger()
