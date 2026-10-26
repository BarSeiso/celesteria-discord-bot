"""Celesteria logging configuration.

Sets up structured logging with console output, rotating file output,
and a safety filter that prevents accidental logging of sensitive values like tokens.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


class _SecretFilter(logging.Filter):
    """Prevents accidental logging of sensitive values.

    Masks exact registered secrets (e.g. Discord tokens) and redacts
    suspiciously long messages containing sensitive keywords.
    """

    _KEYWORDS = ("token", "secret", "password", "authorization", "api_key")
    _SECRETS: set[str] = set()

    @classmethod
    def register_secret(cls, secret: str | None) -> None:
        """Register a secret value to be masked across all logs."""
        if secret and len(secret.strip()) >= 8:
            cls._SECRETS.add(secret.strip())

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        # 1. Exact secret redaction
        for secret in self._SECRETS:
            if secret in message:
                record.msg = message.replace(secret, "[REDACTED_SECRET]")
                record.args = ()
                message = str(record.msg)

        # 2. General keyword heuristic for long string dumps
        if len(message) > 60:
            lower = message.lower()
            for keyword in self._KEYWORDS:
                if keyword in lower:
                    record.msg = "[REDACTED — potential secret in log message]"
                    record.args = ()
                    break

        return True


def setup_logging(level: str = "INFO", token: str | None = None) -> logging.Logger:
    """Configure and return the root Celesteria logger.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        token: Optional secret token to register for masking.

    Returns:
        The configured 'celesteria' logger instance.
    """
    if token:
        _SecretFilter.register_secret(token)

    logger = logging.getLogger("celesteria")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s │ %(levelname)-8s │ %(name)-24s │ %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        secret_filter = _SecretFilter()

        # Console Stream Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        console_handler.setFormatter(formatter)
        console_handler.addFilter(secret_filter)
        logger.addHandler(console_handler)

        # File Handler (rotating, max 5MB with 3 backups)
        try:
            log_dir = Path("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "celesteria.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            file_handler.setFormatter(formatter)
            file_handler.addFilter(secret_filter)
            logger.addHandler(file_handler)
        except OSError:
            # Fall back safely if file system permissions prevent file logging
            pass

    # Reduce noise from discord.py internals
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    return logger
