"""Celesteria logging configuration.

Sets up structured logging with console output and a safety filter
that prevents accidental logging of sensitive values like tokens.
"""

from __future__ import annotations

import logging
import sys


class _SecretFilter(logging.Filter):
    """Prevents accidental logging of sensitive values.

    If a log message is suspiciously long and contains keywords
    associated with secrets, the message is redacted.
    """

    _KEYWORDS = ("token", "secret", "password", "authorization", "api_key")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        # Only flag long messages that look like they contain a raw secret
        if len(message) > 60:
            for keyword in self._KEYWORDS:
                if keyword in message:
                    record.msg = "[REDACTED — potential secret in log message]"
                    record.args = ()
                    break
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the root Celesteria logger.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        The configured 'celesteria' logger instance.
    """
    logger = logging.getLogger("celesteria")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))

        formatter = logging.Formatter(
            fmt="%(asctime)s │ %(levelname)-8s │ %(name)-24s │ %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(_SecretFilter())

        logger.addHandler(handler)

    # Reduce noise from discord.py internals
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    return logger

