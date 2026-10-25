"""Celesteria bot core.

Subclasses ``commands.Bot`` to provide Celesteria-specific behaviour:
presence rotation, cog loading, error routing, and configuration.
"""

from __future__ import annotations

import logging
import sys
import time
from itertools import cycle
from typing import Any

import discord
from discord.ext import commands, tasks

from bot.config import Config
from db.database import Database
from db.repository import ModerationRepository
from db.server_repository import ServerRepository
from services.moderation import ModerationService
from services.server import ServerService
from ui.formatters import format_number
from utils.errors import build_error_embed, send_error_response
from utils.logger import setup_logging

log = logging.getLogger("celesteria.bot")

# Cog extensions to load on startup (module paths)
INITIAL_EXTENSIONS: list[str] = [
    "cogs.core",
    "cogs.moderation",
    "cogs.server",
]


class Celesteria(commands.Bot):
    """The Celesteria Discord bot.

    Attributes:
        config: Immutable bot configuration from environment.
        start_time: Monotonic timestamp of when the bot started.
    """

    config: Config
    start_time: float
    db: Database
    moderation_repo: ModerationRepository
    moderation_service: ModerationService
    server_repo: ServerRepository
    server_service: ServerService

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Required for prefix commands
        intents.members = True          # Required for userinfo, welcome, counts

        super().__init__(
            command_prefix=config.prefix,
            intents=intents,
            help_command=None,  # We provide our own /help
            case_insensitive=True,
        )

        self.config = config
        self.start_time = time.monotonic()

        # Database and service architecture
        self.db = Database(self.config.database_path)
        self.moderation_repo = ModerationRepository(self.db)
        self.moderation_service = ModerationService(self, self.moderation_repo)
        self.server_repo = ServerRepository(self.db)
        self.server_service = ServerService(self, self.server_repo)

        # Presence rotation pool — {member_count} is replaced dynamically
        self._presence_pool = cycle([
            "watching {member_count} members",
            "watching over the kingdom",
            "listening to /help",
            "watching the realm",
        ])

    # ── Setup ───────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Called once before the bot connects.

        Loads cogs, syncs slash commands, and starts background tasks.
        """
        # Set up logging
        setup_logging(self.config.log_level)

        # Initialize database
        await self.db.initialize()

        # Load cog extensions
        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:
                log.exception("Failed to load extension: %s", ext)
                sys.exit(1)

        # Sync slash commands
        if self.config.test_guild_id:
            guild = discord.Object(id=self.config.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(
                "Synced %d commands to test guild %d",
                len(synced),
                self.config.test_guild_id,
            )
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))

        # Set up tree error handler for slash command errors
        self.tree.on_error = self._on_tree_error

        # Start presence rotation and server background tasks
        self._rotate_presence.start()
        self.server_service.start()

    # ── Events ──────────────────────────────────────────────────

    async def on_ready(self) -> None:
        """Called when the bot has successfully connected."""
        log.info(
            "Celesteria is online — %s (ID: %s) in %d guild(s)",
            self.user,
            self.user.id if self.user else "?",
            len(self.guilds),
        )
        # Synchronize member counters across guilds after reconnect
        try:
            await self.server_service.sync_all_counters(force=True)
        except Exception:
            log.exception("Error during initial member counter synchronization")

    # ── Error Handling ──────────────────────────────────────────

    async def on_command_error(
        self,
        ctx: commands.Context[Celesteria],
        error: commands.CommandError,
    ) -> None:
        """Global error handler for prefix commands."""
        # Skip if the command has its own local error handler
        if hasattr(ctx.command, "on_error"):
            return

        # Ignore unknown commands silently
        if isinstance(error, commands.CommandNotFound):
            return

        embed = build_error_embed(error, ctx)
        await send_error_response(ctx, embed)

    async def _on_tree_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Global error handler for slash (app) commands."""
        embed = build_error_embed(error)
        await send_error_response(interaction, embed)

    # ── Presence Rotation ───────────────────────────────────────

    @tasks.loop(minutes=5)
    async def _rotate_presence(self) -> None:
        """Rotate the bot's presence/status message."""
        template = next(self._presence_pool)

        # Calculate total member count across all guilds
        member_count = sum(g.member_count or 0 for g in self.guilds)
        text = template.format(member_count=format_number(member_count))

        # Determine activity type from template
        if template.startswith("watching"):
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=text.removeprefix("watching "),
            )
        elif template.startswith("listening"):
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=text.removeprefix("listening to "),
            )
        else:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=text,
            )

        await self.change_presence(activity=activity)

    @_rotate_presence.before_loop
    async def _before_presence(self) -> None:
        """Wait until the bot is ready before rotating presence."""
        await self.wait_until_ready()

    # ── Utility ─────────────────────────────────────────────────

    @property
    def uptime_seconds(self) -> float:
        """Seconds since the bot process started."""
        return time.monotonic() - self.start_time

    async def close(self) -> None:
        """Gracefully shut down bot, background tasks, and database connection."""
        self.server_service.close()
        try:
            await self.db.close()
        except Exception:
            log.exception("Error closing database connection")
        await super().close()

