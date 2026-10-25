"""Celesteria — Entry Point

Validates configuration and starts the bot.
Run with: py main.py
"""

from __future__ import annotations

import sys

from bot.celesteria import Celesteria
from bot.config import Config


def main() -> None:
    """Load configuration, validate it, and start Celesteria."""
    config = Config.from_env()

    try:
        config.validate()
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    bot = Celesteria(config)
    bot.run(config.token, log_handler=None)  # We configure logging ourselves


if __name__ == "__main__":
    main()

