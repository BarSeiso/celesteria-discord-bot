"""Celesteria configuration management.

Loads configuration from environment variables via python-dotenv.
All secrets remain in .env (git-ignored) and are never logged or exposed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Immutable bot configuration loaded from environment."""

    token: str
    prefix: str
    env: str
    version: str
    log_level: str
    database_path: str
    test_guild_id: int | None

    @classmethod
    def from_env(cls) -> Config:
        """Create a Config instance from environment variables."""
        raw_guild_id = os.getenv("TEST_GUILD_ID", "")
        test_guild_id = int(raw_guild_id) if raw_guild_id.strip() else None

        return cls(
            token=os.getenv("DISCORD_TOKEN", ""),
            prefix=os.getenv("BOT_PREFIX", "!c"),
            env=os.getenv("BOT_ENV", "development"),
            version=os.getenv("BOT_VERSION", "1.0.0"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            database_path=os.getenv("DATABASE_PATH", "data/celesteria.db"),
            test_guild_id=test_guild_id,
        )

    def validate(self) -> None:
        """Validate that required configuration is present.

        Raises:
            ValueError: If DISCORD_TOKEN is missing.
        """
        if not self.token:
            raise ValueError(
                "DISCORD_TOKEN is not set. "
                "Please copy .env.example to .env and add your bot token."
            )

    @property
    def is_development(self) -> bool:
        """Whether the bot is running in development mode."""
        return self.env == "development"

