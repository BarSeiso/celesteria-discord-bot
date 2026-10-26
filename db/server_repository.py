"""Server configuration data access repository.

Handles persistence, caching, and querying of server-level features:
welcome announcements, dynamic member counter, server logs, and leveling toggles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database

DEFAULT_COUNTER_TEMPLATE = "🏰 Members: {count}"
DEFAULT_WELCOME_MESSAGE = (
    "Welcome to the realm, {mention}! We now stand at {member_count} strong."
)


@dataclass(frozen=True)
class ServerConfig:
    """Represents configuration settings for a single guild."""

    guild_id: int
    mod_log_channel_id: int | None = None
    welcome_channel_id: int | None = None
    welcome_message: str | None = None
    counter_channel_id: int | None = None
    counter_template: str = DEFAULT_COUNTER_TEMPLATE
    server_log_channel_id: int | None = None
    leveling_enabled: bool = True
    levelup_channel_id: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> ServerConfig:
        """Construct a ServerConfig from an aiosqlite Row."""
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            guild_id=int(row["guild_id"]),
            mod_log_channel_id=(
                int(row["mod_log_channel_id"])
                if "mod_log_channel_id" in keys and row["mod_log_channel_id"] is not None
                else None
            ),
            welcome_channel_id=(
                int(row["welcome_channel_id"])
                if "welcome_channel_id" in keys and row["welcome_channel_id"] is not None
                else None
            ),
            welcome_message=(
                str(row["welcome_message"])
                if "welcome_message" in keys and row["welcome_message"] is not None
                else None
            ),
            counter_channel_id=(
                int(row["counter_channel_id"])
                if "counter_channel_id" in keys and row["counter_channel_id"] is not None
                else None
            ),
            counter_template=(
                str(row["counter_template"])
                if "counter_template" in keys and row["counter_template"]
                else DEFAULT_COUNTER_TEMPLATE
            ),
            server_log_channel_id=(
                int(row["server_log_channel_id"])
                if "server_log_channel_id" in keys and row["server_log_channel_id"] is not None
                else None
            ),
            leveling_enabled=(
                bool(row["leveling_enabled"])
                if "leveling_enabled" in keys and row["leveling_enabled"] is not None
                else True
            ),
            levelup_channel_id=(
                int(row["levelup_channel_id"])
                if "levelup_channel_id" in keys and row["levelup_channel_id"] is not None
                else None
            ),
        )


class ServerRepository:
    """Repository for guild server configuration management with in-memory caching."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[int, ServerConfig] = {}

    def invalidate_cache(self, guild_id: int | None = None) -> None:
        """Invalidate in-memory cache for a guild or all guilds."""
        if guild_id is not None:
            self._cache.pop(guild_id, None)
        else:
            self._cache.clear()

    async def get_server_config(self, guild_id: int) -> ServerConfig | None:
        """Retrieve full server configuration for a guild (cached)."""
        if guild_id in self._cache:
            return self._cache[guild_id]

        sql = "SELECT * FROM guild_config WHERE guild_id = ?"
        row = await self.db.fetchone(sql, (guild_id,))
        if row:
            config = ServerConfig.from_row(row)
            self._cache[guild_id] = config
            return config
        return None

    async def get_or_create_config(self, guild_id: int) -> ServerConfig:
        """Retrieve server config or initialize a default entry if not found."""
        config = await self.get_server_config(guild_id)
        if config is not None:
            return config

        sql = """
            INSERT INTO guild_config (guild_id, updated_at)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO NOTHING
        """
        await self.db.execute(sql, (guild_id,))
        self.invalidate_cache(guild_id)
        created = await self.get_server_config(guild_id)
        if created is None:
            return ServerConfig(guild_id=guild_id)
        return created

    async def set_welcome_config(
        self,
        guild_id: int,
        channel_id: int | None,
        message: str | None = None,
    ) -> None:
        """Configure or disable the welcome announcement channel and custom greeting."""
        self.invalidate_cache(guild_id)
        if channel_id is None:
            sql = """
                INSERT INTO guild_config (guild_id, welcome_channel_id, updated_at)
                VALUES (?, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    welcome_channel_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
            """
            await self.db.execute(sql, (guild_id,))
            return

        if message is not None:
            sql = """
                INSERT INTO guild_config (guild_id, welcome_channel_id, welcome_message, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    welcome_channel_id = excluded.welcome_channel_id,
                    welcome_message = excluded.welcome_message,
                    updated_at = CURRENT_TIMESTAMP
            """
            await self.db.execute(sql, (guild_id, channel_id, message))
        else:
            sql = """
                INSERT INTO guild_config (guild_id, welcome_channel_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    welcome_channel_id = excluded.welcome_channel_id,
                    updated_at = CURRENT_TIMESTAMP
            """
            await self.db.execute(sql, (guild_id, channel_id))

    async def set_counter_config(
        self,
        guild_id: int,
        channel_id: int | None,
        template: str | None = None,
    ) -> None:
        """Configure or disable the member counter channel and display template."""
        self.invalidate_cache(guild_id)
        if channel_id is None:
            sql = """
                INSERT INTO guild_config (guild_id, counter_channel_id, updated_at)
                VALUES (?, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    counter_channel_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
            """
            await self.db.execute(sql, (guild_id,))
            return

        resolved_template = template if template else DEFAULT_COUNTER_TEMPLATE
        sql = """
            INSERT INTO guild_config (guild_id, counter_channel_id, counter_template, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                counter_channel_id = excluded.counter_channel_id,
                counter_template = excluded.counter_template,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, channel_id, resolved_template))

    async def set_server_log_channel_id(
        self,
        guild_id: int,
        channel_id: int | None,
    ) -> None:
        """Configure or disable the server activity log channel."""
        self.invalidate_cache(guild_id)
        sql = """
            INSERT INTO guild_config (guild_id, server_log_channel_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                server_log_channel_id = excluded.server_log_channel_id,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, channel_id))

    async def set_leveling_enabled(self, guild_id: int, enabled: bool) -> None:
        """Toggle leveling progression for a guild."""
        self.invalidate_cache(guild_id)
        val = 1 if enabled else 0
        sql = """
            INSERT INTO guild_config (guild_id, leveling_enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                leveling_enabled = excluded.leveling_enabled,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, val))

    async def set_levelup_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        """Configure or clear the level-up celebration announcement channel."""
        self.invalidate_cache(guild_id)
        sql = """
            INSERT INTO guild_config (guild_id, levelup_channel_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                levelup_channel_id = excluded.levelup_channel_id,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, channel_id))

    async def clear_channel_binding(self, guild_id: int, channel_id: int) -> list[str]:
        """Automatically unbind any configuration referencing a deleted channel.

        Returns a list of unbind actions performed (e.g. ['welcome', 'counter']).
        """
        config = await self.get_server_config(guild_id)
        if not config:
            return []

        cleared: list[str] = []
        if config.welcome_channel_id == channel_id:
            await self.set_welcome_config(guild_id, None)
            cleared.append("welcome")
        if config.counter_channel_id == channel_id:
            await self.set_counter_config(guild_id, None)
            cleared.append("counter")
        if config.server_log_channel_id == channel_id:
            await self.set_server_log_channel_id(guild_id, None)
            cleared.append("server_log")
        if config.mod_log_channel_id == channel_id:
            sql = """
                UPDATE guild_config
                SET mod_log_channel_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
            """
            await self.db.execute(sql, (guild_id,))
            self.invalidate_cache(guild_id)
            cleared.append("mod_log")
        if config.levelup_channel_id == channel_id:
            await self.set_levelup_channel_id(guild_id, None)
            cleared.append("levelup")

        return cleared

    async def get_all_counter_configs(self) -> list[ServerConfig]:
        """Fetch all server configs where a counter channel is bound."""
        sql = "SELECT * FROM guild_config WHERE counter_channel_id IS NOT NULL"
        rows = await self.db.fetchall(sql)
        return [ServerConfig.from_row(r) for r in rows]
