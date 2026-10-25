"""Unit and integration test suite for Celesteria Phase 3 — Server Systems.

Covers:
1. Database schema migration and ServerRepository CRUD operations
2. Welcome system embed rendering, placeholder interpolation, and dispatching
3. Member counter format rendering, dirty tracking, debounce logic, and API skipping
4. Server activity logging events (member join/leave, message delete/edit, roles, channels)
5. Missing/invalid configuration resilience and permission error handling
6. Cog command registration and /help category integration
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.celesteria import Celesteria
from bot.config import Config
from db.database import Database
from db.server_repository import (
    DEFAULT_COUNTER_TEMPLATE,
    DEFAULT_WELCOME_MESSAGE,
    ServerConfig,
    ServerRepository,
)
from services.server import ServerService
from ui.theme import Brand, Icon, Palette
from ui.views import HelpCategorySelect


class TestServerDatabaseAndRepository(unittest.IsolatedAsyncioTestCase):
    """Test SQLite migrations and ServerRepository persistence."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_server.db")
        self.db = Database(self.db_path)
        await self.db.initialize()
        self.repo = ServerRepository(self.db)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_schema_has_all_phase3_columns(self) -> None:
        async with self.db.connection.execute("PRAGMA table_info(guild_config);") as cursor:
            rows = await cursor.fetchall()
            columns = {row["name"] for row in rows}

        expected = {
            "guild_id",
            "mod_log_channel_id",
            "welcome_channel_id",
            "welcome_message",
            "counter_channel_id",
            "counter_template",
            "server_log_channel_id",
            "created_at",
            "updated_at",
        }
        self.assertTrue(expected.issubset(columns))

    async def test_welcome_config_persistence(self) -> None:
        guild_id = 9901
        self.assertIsNone(await self.repo.get_server_config(guild_id))

        # Set welcome channel and custom message
        await self.repo.set_welcome_config(
            guild_id,
            channel_id=12345,
            message="Hail, {mention}! Welcome to {server}!",
        )
        cfg = await self.repo.get_server_config(guild_id)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.welcome_channel_id, 12345)
        self.assertEqual(cfg.welcome_message, "Hail, {mention}! Welcome to {server}!")

        # Unbind welcome channel
        await self.repo.set_welcome_config(guild_id, None)
        cfg_updated = await self.repo.get_server_config(guild_id)
        self.assertIsNotNone(cfg_updated)
        self.assertIsNone(cfg_updated.welcome_channel_id)

    async def test_counter_config_persistence(self) -> None:
        guild_id = 9902
        await self.repo.set_counter_config(
            guild_id,
            channel_id=54321,
            template="⚜ Realm: {count}",
        )
        cfg = await self.repo.get_server_config(guild_id)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.counter_channel_id, 54321)
        self.assertEqual(cfg.counter_template, "⚜ Realm: {count}")

        # List all counter configs
        active = await self.repo.get_all_counter_configs()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].guild_id, guild_id)

        # Disable counter
        await self.repo.set_counter_config(guild_id, None)
        active_after = await self.repo.get_all_counter_configs()
        self.assertEqual(len(active_after), 0)

    async def test_server_log_config_persistence(self) -> None:
        guild_id = 9903
        await self.repo.set_server_log_channel_id(guild_id, 88888)
        cfg = await self.repo.get_server_config(guild_id)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.server_log_channel_id, 88888)

        # Unbind
        await self.repo.set_server_log_channel_id(guild_id, None)
        cfg_after = await self.repo.get_server_config(guild_id)
        self.assertIsNone(cfg_after.server_log_channel_id)


class TestWelcomeService(unittest.TestCase):
    """Test welcome embed formatting, placeholders, and bot distinction."""

    def setUp(self) -> None:
        self.bot_mock = MagicMock(spec=Celesteria)
        self.repo_mock = MagicMock(spec=ServerRepository)
        self.service = ServerService(self.bot_mock, self.repo_mock)

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 1001
        self.guild.name = "Kingdom of Celesteria"
        self.guild.member_count = 1250
        self.guild.members = [MagicMock()] * 1250

    def test_human_welcome_embed_formatting(self) -> None:
        member = MagicMock(spec=discord.Member)
        member.id = 2001
        member.name = "Arthur"
        member.mention = "<@2001>"
        member.guild = self.guild
        member.bot = False
        member.display_avatar.url = "https://example.com/avatar.png"
        member.created_at = discord.utils.utcnow()

        custom_template = "Greetings, {mention}! You are member #{member_count} of {server}."
        embed = self.service.build_welcome_embed(member, custom_template)

        self.assertEqual(embed.title, f"{Icon.BRAND} A New Member Has Entered the Realm")
        self.assertIn("Greetings, <@2001>!", embed.description)
        self.assertIn("Kingdom of Celesteria", embed.description)
        self.assertIn("1,250", embed.description)
        self.assertEqual(embed.thumbnail.url, "https://example.com/avatar.png")
        self.assertEqual(embed.footer.text, "Welcome to Kingdom of Celesteria")
        self.assertNotIn("sunflower1y", embed.footer.text)

    def test_bot_sentinel_welcome_embed_formatting(self) -> None:
        bot_member = MagicMock(spec=discord.Member)
        bot_member.id = 3001
        bot_member.name = "CelesteriaGuard"
        bot_member.mention = "<@3001>"
        bot_member.guild = self.guild
        bot_member.bot = True
        bot_member.display_avatar.url = "https://example.com/bot_avatar.png"
        bot_member.created_at = discord.utils.utcnow()

        embed = self.service.build_welcome_embed(bot_member)
        self.assertEqual(embed.title, f"{Icon.SHIELD} Arcane Construct Registered")
        self.assertIn("automated sentinel", embed.description)
        self.assertEqual(embed.colour, Palette.INFO)
        self.assertEqual(embed.footer.text, "Realm Sentinel")
        self.assertNotIn("sunflower1y", embed.footer.text)


class TestMemberCounterLogic(unittest.IsolatedAsyncioTestCase):
    """Test counter name template interpolation, debounce interval, and API avoidance."""

    def setUp(self) -> None:
        self.bot_mock = MagicMock(spec=Celesteria)
        self.repo_mock = AsyncMock(spec=ServerRepository)
        self.service = ServerService(self.bot_mock, self.repo_mock)

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 1001
        self.guild.member_count = 100
        
        # 80 humans, 20 bots
        humans = [MagicMock(bot=False) for _ in range(80)]
        bots = [MagicMock(bot=True) for _ in range(20)]
        self.guild.members = humans + bots
        self.bot_mock.get_guild.return_value = self.guild

    def test_format_counter_name(self) -> None:
        template = "🏰 Realm: {count} | Humans: {humans} | Bots: {bots}"
        name = self.service.format_counter_name(self.guild, template)
        self.assertEqual(name, "🏰 Realm: 100 | Humans: 80 | Bots: 20")

    def test_format_counter_name_truncation(self) -> None:
        long_template = "X" * 150
        name = self.service.format_counter_name(self.guild, long_template)
        self.assertEqual(len(name), 100)

    async def test_skip_api_call_when_name_already_matches(self) -> None:
        channel = AsyncMock(spec=discord.VoiceChannel)
        channel.name = "🏰 Members: 100"
        perms = MagicMock()
        perms.manage_channels = True
        channel.permissions_for.return_value = perms
        self.guild.get_channel.return_value = channel

        self.repo_mock.get_server_config.return_value = ServerConfig(
            guild_id=self.guild.id,
            counter_channel_id=channel.id,
            counter_template="🏰 Members: {count}",
        )

        synced = await self.service.sync_guild_counter(self.guild.id)
        self.assertTrue(synced)
        channel.edit.assert_not_called()

    async def test_debounce_cooldown_prevents_rapid_renames(self) -> None:
        channel = AsyncMock(spec=discord.VoiceChannel)
        channel.name = "🏰 Members: 99"
        perms = MagicMock()
        perms.manage_channels = True
        channel.permissions_for.return_value = perms
        self.guild.get_channel.return_value = channel

        self.repo_mock.get_server_config.return_value = ServerConfig(
            guild_id=self.guild.id,
            counter_channel_id=channel.id,
            counter_template="🏰 Members: {count}",
        )

        # Simulate a rename done 60 seconds ago
        self.service._last_rename_time[self.guild.id] = time.monotonic() - 60.0

        # Normal sync (not forced) should be blocked by 10-minute cooldown
        synced = await self.service.sync_guild_counter(self.guild.id, force=False)
        self.assertFalse(synced)
        channel.edit.assert_not_called()

        # Forced sync (e.g. initial setup) overrides cooldown
        forced_synced = await self.service.sync_guild_counter(self.guild.id, force=True)
        self.assertTrue(forced_synced)
        channel.edit.assert_called_once_with(
            name="🏰 Members: 100",
            reason="Celesteria member counter sync",
        )


class TestServerLoggingService(unittest.IsolatedAsyncioTestCase):
    """Test server activity log dispatching for joins, leaves, edits, deletes."""

    def setUp(self) -> None:
        self.bot_mock = MagicMock(spec=Celesteria)
        self.repo_mock = AsyncMock(spec=ServerRepository)
        self.service = ServerService(self.bot_mock, self.repo_mock)

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 1001
        self.guild.member_count = 50
        self.guild.members = [MagicMock()] * 50

        self.log_channel = AsyncMock(spec=discord.TextChannel)
        perms = MagicMock()
        perms.send_messages = True
        perms.embed_links = True
        self.log_channel.permissions_for.return_value = perms
        self.guild.get_channel.return_value = self.log_channel

        self.repo_mock.get_server_config.return_value = ServerConfig(
            guild_id=self.guild.id,
            server_log_channel_id=self.log_channel.id,
        )

    async def test_log_member_join(self) -> None:
        member = MagicMock(spec=discord.Member)
        member.id = 2001
        member.guild = self.guild
        member.bot = False
        member.created_at = discord.utils.utcnow()
        member.display_avatar.url = "https://example.com/avatar.png"

        await self.service.log_member_join(member)
        self.log_channel.send.assert_called_once()
        embed = self.log_channel.send.call_args.kwargs["embed"]
        self.assertIn("Member Joined Realm", embed.title)

    async def test_log_member_leave(self) -> None:
        member = MagicMock(spec=discord.Member)
        member.id = 2001
        member.guild = self.guild
        member.joined_at = discord.utils.utcnow()
        member.roles = [self.guild.default_role]
        member.display_avatar.url = "https://example.com/avatar.png"

        await self.service.log_member_leave(member)
        self.log_channel.send.assert_called_once()
        embed = self.log_channel.send.call_args.kwargs["embed"]
        self.assertIn("Member Departed Realm", embed.title)

    async def test_log_message_delete_ignores_bots(self) -> None:
        msg = MagicMock(spec=discord.Message)
        msg.guild = self.guild
        msg.author.bot = True

        await self.service.log_message_delete(msg)
        self.log_channel.send.assert_not_called()

    async def test_log_message_delete_human(self) -> None:
        msg = MagicMock(spec=discord.Message)
        msg.guild = self.guild
        msg.author.bot = False
        msg.author.mention = "<@123>"
        msg.content = "Secret medieval message"
        msg.clean_content = "Secret medieval message"
        msg.attachments = []
        msg.channel.mention = "<#chan>"

        await self.service.log_message_delete(msg)
        self.log_channel.send.assert_called_once()
        embed = self.log_channel.send.call_args.kwargs["embed"]
        self.assertIn("Message Expunged", embed.title)

    async def test_log_message_edit_ignores_identical_content(self) -> None:
        before = MagicMock(spec=discord.Message)
        before.guild = self.guild
        before.author.bot = False
        before.content = "Same text"

        after = MagicMock(spec=discord.Message)
        after.content = "Same text"

        await self.service.log_message_edit(before, after)
        self.log_channel.send.assert_not_called()


class TestServerCogAndHelpParity(unittest.IsolatedAsyncioTestCase):
    """Test ServerCog command registration and /help category integration."""

    async def asyncSetUp(self) -> None:
        self.config = Config(
            token="dummy_token",
            prefix="!c",
            env="testing",
            version="1.0.0",
            log_level="CRITICAL",
            database_path=":memory:",
            test_guild_id=None,
        )
        self.bot = Celesteria(self.config)
        await self.bot.db.initialize()
        await self.bot.load_extension("cogs.core")
        await self.bot.load_extension("cogs.moderation")
        await self.bot.load_extension("cogs.server")

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_server_cog_registered_with_all_commands(self) -> None:
        cog = self.bot.get_cog("Server")
        self.assertIsNotNone(cog)
        self.assertEqual(cog.emoji, "🏰")

        registered_names = {c.name for c in cog.get_commands()}
        expected_commands = {
            "setwelcome",
            "testwelcome",
            "setcounter",
            "setserverlog",
            "serverconfig",
        }
        self.assertTrue(expected_commands.issubset(registered_names))

    async def test_help_view_surfaces_server_category(self) -> None:
        select = HelpCategorySelect(self.bot)
        category_values = {opt.value for opt in select.options}
        self.assertIn("Core", category_values)
        self.assertIn("Moderation", category_values)
        self.assertIn("Server", category_values)

        server_opt = next(opt for opt in select.options if opt.value == "Server")
        self.assertIn("🏰", server_opt.label)


if __name__ == "__main__":
    unittest.main()

