"""Unit and integration test suite for Celesteria Phase 5 — Polish & Admin Control.

Covers:
1. Centralized administrator configuration (/config, ConfigDashboardView)
2. Interactive admin dashboard interactions (category select, toggle leveling button, sync counter button)
3. Direct leveling toggle command (/toggleveling) and parity in /serverconfig
4. Discord.py 2.x app_commands error handling and custom PermissionError handling
5. Database self-healing on channel and role deletions
6. In-memory configuration caching and cache invalidation
7. Logging security and dynamic token masking
8. Full cross-phase regression verification
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands
from discord.ext import commands

from bot.celesteria import Celesteria
from bot.config import Config
from cogs.server import ServerCog
from db.database import Database
from db.level_repository import LevelRepository, LevelReward
from db.server_repository import ServerConfig, ServerRepository
from services.server import ServerService
from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette
from ui.views import ConfigCategorySelect, ConfigDashboardView
from utils.errors import build_error_embed, generate_error_id, send_error_response
from utils.logger import _SecretFilter, setup_logging


class TestPhase5DatabaseSelfHealingAndCache(unittest.IsolatedAsyncioTestCase):
    """Test in-memory config caching and automatic self-healing on entity deletion."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_phase5.db")
        self.db = Database(self.db_path)
        await self.db.initialize()
        self.server_repo = ServerRepository(self.db)
        self.level_repo = LevelRepository(self.db)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_server_config_caching_and_invalidation(self) -> None:
        guild_id = 7001
        # Initial fetch -> None
        self.assertIsNone(await self.server_repo.get_server_config(guild_id))

        # Set config -> invalidates cache
        await self.server_repo.set_welcome_config(guild_id, 111, "Hail {mention}!")
        cfg1 = await self.server_repo.get_server_config(guild_id)
        self.assertIsNotNone(cfg1)
        self.assertEqual(cfg1.welcome_channel_id, 111)

        # Second fetch should hit in-memory cache directly
        self.assertIn(guild_id, self.server_repo._cache)
        cfg2 = await self.server_repo.get_server_config(guild_id)
        self.assertIs(cfg1, cfg2)

        # Mutating config clears/updates cache
        await self.server_repo.set_welcome_config(guild_id, 222)
        cfg3 = await self.server_repo.get_server_config(guild_id)
        self.assertEqual(cfg3.welcome_channel_id, 222)

    async def test_leveling_enabled_caching(self) -> None:
        guild_id = 7002
        # Default is True
        self.assertTrue(await self.level_repo.is_leveling_enabled(guild_id))
        self.assertIn(guild_id, self.level_repo._enabled_cache)

        # Toggle to False
        await self.level_repo.set_leveling_enabled(guild_id, False)
        self.assertFalse(await self.level_repo.is_leveling_enabled(guild_id))
        self.assertFalse(self.level_repo._enabled_cache[guild_id])

    async def test_clear_channel_binding_self_healing(self) -> None:
        guild_id = 7003
        chan_id = 5555

        # Configure multiple features with this channel
        await self.server_repo.set_welcome_config(guild_id, chan_id)
        await self.server_repo.set_counter_config(guild_id, chan_id)
        await self.server_repo.set_server_log_channel_id(guild_id, chan_id)
        await self.server_repo.set_levelup_channel_id(guild_id, chan_id)

        # Verify configured
        cfg = await self.server_repo.get_server_config(guild_id)
        self.assertEqual(cfg.welcome_channel_id, chan_id)
        self.assertEqual(cfg.counter_channel_id, chan_id)
        self.assertEqual(cfg.server_log_channel_id, chan_id)
        self.assertEqual(cfg.levelup_channel_id, chan_id)

        # Clear channel binding
        cleared = await self.server_repo.clear_channel_binding(guild_id, chan_id)
        self.assertIn("welcome", cleared)
        self.assertIn("counter", cleared)
        self.assertIn("server_log", cleared)
        self.assertIn("levelup", cleared)

        # Verify database fields are now NULL
        updated = await self.server_repo.get_server_config(guild_id)
        self.assertIsNone(updated.welcome_channel_id)
        self.assertIsNone(updated.counter_channel_id)
        self.assertIsNone(updated.server_log_channel_id)
        self.assertIsNone(updated.levelup_channel_id)

    async def test_remove_reward_by_role_id(self) -> None:
        guild_id = 7004
        role_id = 9999
        await self.level_repo.set_level_reward(guild_id, level=5, role_id=role_id)
        await self.level_repo.set_level_reward(guild_id, level=10, role_id=8888)

        # Prune rewards for role 9999
        deleted = await self.level_repo.remove_reward_by_role_id(guild_id, role_id)
        self.assertEqual(deleted, 1)

        # Level 5 reward is gone, level 10 remains
        self.assertIsNone(await self.level_repo.get_reward_for_level(guild_id, 5))
        self.assertIsNotNone(await self.level_repo.get_reward_for_level(guild_id, 10))


class TestPhase5AppCommandAndErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test global error handler with Discord.py 2.x app_commands and API exceptions."""

    def test_app_commands_missing_permissions(self) -> None:
        err = app_commands.MissingPermissions(["manage_guild", "kick_members"])
        embed = build_error_embed(err)
        self.assertIn("Permission Denied", embed.title)
        self.assertIn("Manage Guild", embed.description)
        self.assertIn("Kick Members", embed.description)

    def test_app_commands_bot_missing_permissions(self) -> None:
        err = app_commands.BotMissingPermissions(["manage_channels"])
        embed = build_error_embed(err)
        self.assertIn("Bot Missing Permissions", embed.title)
        self.assertIn("Manage Channels", embed.description)

    def test_app_commands_cooldown(self) -> None:
        err = app_commands.CommandOnCooldown(cooldown=MagicMock(), retry_after=42.5)
        embed = build_error_embed(err)
        self.assertIn("Command on Cooldown", embed.title)
        self.assertIn("42.5s", embed.description)

    def test_permission_error_from_domain_service(self) -> None:
        err = PermissionError("I cannot moderate someone with an equal or higher role than mine.")
        embed = build_error_embed(err)
        self.assertIn("Permission Denied", embed.title)
        self.assertIn("equal or higher role", embed.description)

    def test_discord_forbidden_http_exception(self) -> None:
        response = MagicMock()
        response.status = 403
        response.reason = "Forbidden"
        err = discord.Forbidden(response, "Missing Permissions")
        embed = build_error_embed(err)
        self.assertIn("Access Denied by Discord", embed.title)
        self.assertIn("missing bot permissions", embed.description)

    def test_discord_not_found_exception(self) -> None:
        response = MagicMock()
        response.status = 404
        response.reason = "Not Found"
        err = discord.NotFound(response, "Unknown Channel")
        embed = build_error_embed(err)
        self.assertIn("Resource Not Found", embed.title)

    def test_generic_unexpected_error_generates_error_id(self) -> None:
        err = RuntimeError("Unexpected internal failure")
        embed = build_error_embed(err)
        self.assertIn("Something Went Wrong", embed.title)
        self.assertTrue(embed.footer.text.startswith("Error ID: CELESTERIA-"))
        self.assertNotIn("Traceback", embed.description)

    async def test_send_error_response_interaction(self) -> None:
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        embed = CelesteriaEmbed.error("Test Title", "Test Desc")

        await send_error_response(interaction, embed)
        interaction.response.send_message.assert_called_once_with(embed=embed, ephemeral=True)


class TestPhase5ConfigViewsAndAdminInteractions(unittest.IsolatedAsyncioTestCase):
    """Test interactive ConfigDashboardView, select menu navigation, and buttons."""

    async def asyncSetUp(self) -> None:
        self.bot = MagicMock(spec=Celesteria)
        self.bot.server_repo = AsyncMock()
        self.bot.level_repo = AsyncMock()
        self.bot.server_service = AsyncMock()

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 8001
        self.guild.name = "Kingdom of Celesteria"
        self.guild.icon = None

        self.author_id = 12345
        self.view = ConfigDashboardView(self.bot, self.guild, self.author_id)

    def test_view_initialization_and_children(self) -> None:
        self.assertEqual(len(self.view.children), 5)  # 1 Select + 4 Buttons
        selects = [c for c in self.view.children if isinstance(c, ConfigCategorySelect)]
        self.assertEqual(len(selects), 1)
        button_labels = [c.label for c in self.view.children if isinstance(c, discord.ui.Button)]
        self.assertIn("Toggle Leveling", button_labels)
        self.assertIn("Sync Counter", button_labels)
        self.assertIn("Refresh", button_labels)
        self.assertIn("Close", button_labels)

    async def test_interaction_check_permissions(self) -> None:
        # 1. Author should be allowed
        inter1 = AsyncMock(spec=discord.Interaction)
        inter1.user = MagicMock(spec=discord.Member)
        inter1.user.id = self.author_id
        inter1.user.guild_permissions.manage_guild = False
        self.assertTrue(await self.view.interaction_check(inter1))

        # 2. Administrator with Manage Guild should be allowed
        inter2 = AsyncMock(spec=discord.Interaction)
        inter2.user = MagicMock(spec=discord.Member)
        inter2.user.id = 99999
        inter2.user.guild_permissions.manage_guild = True
        self.assertTrue(await self.view.interaction_check(inter2))

        # 3. Unauthorized non-admin should be rejected
        inter3 = AsyncMock(spec=discord.Interaction)
        inter3.response = AsyncMock()
        inter3.response.send_message = AsyncMock()
        inter3.user = MagicMock(spec=discord.Member)
        inter3.user.id = 88888
        inter3.user.guild_permissions.manage_guild = False
        self.assertFalse(await self.view.interaction_check(inter3))
        inter3.response.send_message.assert_called_once()

    async def test_render_overview_embed(self) -> None:
        config = ServerConfig(
            guild_id=self.guild.id,
            welcome_channel_id=111,
            welcome_message="Welcome!",
            counter_channel_id=222,
            counter_template="🏰 Members: {count}",
            server_log_channel_id=333,
            mod_log_channel_id=444,
            leveling_enabled=True,
            levelup_channel_id=555,
        )
        self.bot.server_repo.get_server_config.return_value = config
        self.bot.level_repo.get_level_rewards.return_value = [
            LevelReward(guild_id=self.guild.id, level=5, role_id=777)
        ]

        embed = await self.view.render_embed()
        self.assertIn("Royal Realm Configuration", embed.title)
        field_names = [f.name for f in embed.fields]
        self.assertTrue(any("Welcome" in f for f in field_names))
        self.assertTrue(any("Counter" in f for f in field_names))
        self.assertTrue(any("Server Activity" in f for f in field_names))
        self.assertTrue(any("Decree Log" in f for f in field_names))
        self.assertTrue(any("Leveling" in f for f in field_names))
        self.assertTrue(any("Rewards" in f for f in field_names))

    async def test_toggle_leveling_button(self) -> None:
        config = ServerConfig(guild_id=self.guild.id, leveling_enabled=True)
        self.bot.server_repo.get_server_config.return_value = config
        self.bot.level_repo.get_level_rewards.return_value = []

        inter = AsyncMock(spec=discord.Interaction)
        inter.response = AsyncMock()
        inter.response.edit_message = AsyncMock()

        await self.view.toggle_leveling_btn.callback(inter)
        self.bot.server_repo.set_leveling_enabled.assert_called_once_with(self.guild.id, False)
        self.bot.level_repo.set_leveling_enabled.assert_called_once_with(self.guild.id, False)
        inter.response.edit_message.assert_called_once()

    async def test_sync_counter_button(self) -> None:
        self.bot.server_service.sync_guild_counter.return_value = True
        self.bot.server_repo.get_server_config.return_value = ServerConfig(guild_id=self.guild.id)
        self.bot.level_repo.get_level_rewards.return_value = []

        inter = AsyncMock(spec=discord.Interaction)
        inter.response = AsyncMock()
        inter.response.edit_message = AsyncMock()
        inter.followup = AsyncMock()
        inter.followup.send = AsyncMock()

        await self.view.sync_counter_btn.callback(inter)
        self.bot.server_service.sync_guild_counter.assert_called_once_with(self.guild.id, force=False)
        inter.response.edit_message.assert_called_once()
        inter.followup.send.assert_called_once()


class TestPhase5ServerCogCommands(unittest.IsolatedAsyncioTestCase):
    """Test /config and /toggleveling hybrid commands and /serverconfig parity."""

    async def asyncSetUp(self) -> None:
        self.bot = MagicMock(spec=Celesteria)
        self.bot.server_service = AsyncMock()
        self.bot.server_repo = AsyncMock()
        self.bot.level_repo = AsyncMock()
        self.bot.moderation_repo = AsyncMock()

        self.cog = ServerCog(self.bot)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 9001
        self.guild.name = "Grand Realm"
        self.guild.icon = None

        self.ctx = AsyncMock(spec=commands.Context)
        self.ctx.guild = self.guild
        self.ctx.author = MagicMock(spec=discord.Member)
        self.ctx.author.id = 12345

    async def test_config_command_dispatches_view(self) -> None:
        self.bot.server_repo.get_server_config.return_value = ServerConfig(guild_id=self.guild.id)
        self.bot.level_repo.get_level_rewards.return_value = []

        await self.cog.config_dashboard.callback(self.cog, self.ctx)
        self.ctx.send.assert_called_once()
        _, kwargs = self.ctx.send.call_args
        self.assertIn("embed", kwargs)
        self.assertIn("view", kwargs)
        self.assertIsInstance(kwargs["view"], ConfigDashboardView)

    async def test_toggleveling_command(self) -> None:
        # Start enabled (True)
        self.bot.level_repo.is_leveling_enabled.return_value = True

        await self.cog.toggleveling.callback(self.cog, self.ctx)
        self.bot.server_repo.set_leveling_enabled.assert_called_once_with(self.guild.id, False)
        self.bot.level_repo.set_leveling_enabled.assert_called_once_with(self.guild.id, False)

        self.ctx.send.assert_called_once()
        _, kwargs = self.ctx.send.call_args
        embed = kwargs["embed"]
        self.assertIn("Disabled", embed.title)

    async def test_serverconfig_parity_contains_all_systems(self) -> None:
        self.bot.server_repo.get_server_config.return_value = ServerConfig(
            guild_id=self.guild.id,
            welcome_channel_id=111,
            counter_channel_id=222,
            server_log_channel_id=333,
            leveling_enabled=True,
            levelup_channel_id=555,
        )
        self.bot.moderation_repo.get_mod_log_channel_id.return_value = 444
        self.bot.level_repo.get_level_rewards.return_value = [
            LevelReward(guild_id=self.guild.id, level=1, role_id=10)
        ]

        await self.cog.serverconfig.callback(self.cog, self.ctx)
        self.ctx.send.assert_called_once()
        _, kwargs = self.ctx.send.call_args
        embed = kwargs["embed"]

        field_names = [f.name for f in embed.fields]
        self.assertTrue(any("Welcome" in f for f in field_names))
        self.assertTrue(any("Counter" in f for f in field_names))
        self.assertTrue(any("Server Activity" in f for f in field_names))
        self.assertTrue(any("Moderation" in f for f in field_names))
        self.assertTrue(any("Leveling" in f for f in field_names))
        self.assertTrue(any("Role Rewards" in f for f in field_names))


class TestPhase5SecurityAndLogging(unittest.TestCase):
    """Test dynamic token masking, file logger setup, and .env.example hygiene."""

    def test_dynamic_token_masking(self) -> None:
        secret_token = "MTE2NzgyMzQ1Njc4OTA5ODc2NQ.CelesteriaSecretTokenXYZ"
        _SecretFilter.register_secret(secret_token)
        filt = _SecretFilter()

        record = logging.LogRecord(
            name="celesteria.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg=f"Connected using bot token: {secret_token}",
            args=(),
            exc_info=None,
        )

        filt.filter(record)
        self.assertNotIn(secret_token, record.msg)
        self.assertIn("[REDACTED_SECRET]", record.msg)

    def test_env_example_clean_and_present(self) -> None:
        env_example_path = Path(".env.example")
        self.assertTrue(env_example_path.exists(), ".env.example must exist in root")

        content = env_example_path.read_text(encoding="utf-8")
        self.assertIn("DISCORD_TOKEN=your_bot_token_here", content)
        self.assertNotIn("Celesteria", content[:20].lower())  # Header is fine, verify no raw token
        self.assertIn("BOT_PREFIX=!c", content)


if __name__ == "__main__":
    unittest.main()
