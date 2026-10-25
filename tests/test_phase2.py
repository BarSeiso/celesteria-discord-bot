"""Comprehensive unit and integration test suite for Celesteria Phase 2.

Covers:
1. Duration parsing and formatting constraints
2. Database initialization and repository operations
3. Role hierarchy and permission check matrix
4. Moderation domain service execution and error handling
5. Bot cog loading and hybrid command registration parity
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.celesteria import Celesteria
from bot.config import Config
from db.database import Database
from db.repository import ModerationCase, ModerationRepository
from services.moderation import ModerationService
from ui.views import HelpCategorySelect
from utils.duration import (
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    format_duration,
    parse_duration,
)
from utils.permissions import bot_can_moderate, can_moderate, check_bot_permissions


class TestDurationUtils(unittest.TestCase):
    """Test duration parsing, boundary enforcement, and formatting."""

    def test_valid_durations(self) -> None:
        test_cases = [
            ("30s", 30),
            ("10m", 600),
            ("2h", 7200),
            ("1d", 86400),
            ("7d", 604800),
            ("2w", 1209600),
            ("1h 30m", 5400),
            ("2h15m", 8100),
        ]
        for text, expected_seconds in test_cases:
            with self.subTest(duration=text):
                secs, delta = parse_duration(text)
                self.assertEqual(secs, expected_seconds)
                self.assertEqual(delta, timedelta(seconds=expected_seconds))

    def test_minimum_boundary(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_duration("4s")
        self.assertIn("at least 5 seconds", str(ctx.exception))

    def test_maximum_boundary(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_duration("29d")
        self.assertIn("cannot exceed 28 days", str(ctx.exception))

    def test_invalid_syntax(self) -> None:
        invalid_inputs = ["abc", "10x", "-5m", "10m 5invalid", ""]
        for text in invalid_inputs:
            with self.subTest(duration=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(60), "1 minute")
        self.assertEqual(format_duration(3600), "1 hour")
        self.assertEqual(format_duration(7200), "2 hours")
        self.assertEqual(format_duration(86400), "1 day")
        self.assertEqual(format_duration(90000), "1 day 1 hour")
        self.assertEqual(format_duration(0), "0 seconds")


class TestDatabaseAndRepository(unittest.IsolatedAsyncioTestCase):
    """Test SQLite lifecycle, migrations, and repository queries."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_celesteria.db")
        self.db = Database(self.db_path)
        await self.db.initialize()
        self.repo = ModerationRepository(self.db)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_case_sequential_increment_per_guild(self) -> None:
        guild_a = 1001
        guild_b = 2002

        # Guild A first case
        case_a1 = await self.repo.create_case(
            guild_id=guild_a,
            action="warn",
            target_id=501,
            target_tag="Knight#0001",
            moderator_id=901,
            moderator_tag="King#0001",
            reason="Treasonous speech",
        )
        self.assertEqual(case_a1.case_id, 1)

        # Guild A second case
        case_a2 = await self.repo.create_case(
            guild_id=guild_a,
            action="timeout",
            target_id=501,
            target_tag="Knight#0001",
            moderator_id=901,
            moderator_tag="King#0001",
            reason="Unruly conduct",
            duration_seconds=600,
        )
        self.assertEqual(case_a2.case_id, 2)

        # Guild B first case (must be isolated and start at 1)
        case_b1 = await self.repo.create_case(
            guild_id=guild_b,
            action="ban",
            target_id=701,
            target_tag="Rogue#0001",
            moderator_id=902,
            moderator_tag="Queen#0001",
            reason="Espionage",
        )
        self.assertEqual(case_b1.case_id, 1)

    async def test_case_queries(self) -> None:
        guild_id = 3003
        target_id = 4004

        await self.repo.create_case(
            guild_id=guild_id,
            action="warn",
            target_id=target_id,
            target_tag="Peasant#0001",
            moderator_id=1,
            moderator_tag="Guard#0001",
            reason="Curfew violation",
        )
        await self.repo.create_case(
            guild_id=guild_id,
            action="kick",
            target_id=target_id,
            target_tag="Peasant#0001",
            moderator_id=1,
            moderator_tag="Guard#0001",
            reason="Second offense",
        )

        # Query by case ID
        case1 = await self.repo.get_case(guild_id, 1)
        self.assertIsNotNone(case1)
        self.assertEqual(case1.action, "warn")

        # Nonexistent case
        self.assertIsNone(await self.repo.get_case(guild_id, 99))

        # Query by target
        cases = await self.repo.get_cases_for_target(guild_id, target_id)
        self.assertEqual(len(cases), 2)
        count = await self.repo.count_cases_for_target(guild_id, target_id)
        self.assertEqual(count, 2)

        # Recent cases in guild
        recent = await self.repo.get_recent_cases(guild_id)
        self.assertEqual(len(recent), 2)
        total = await self.repo.count_total_cases(guild_id)
        self.assertEqual(total, 2)

    async def test_mod_log_channel_config(self) -> None:
        guild_id = 4004

        # Initial: not configured
        self.assertIsNone(await self.repo.get_mod_log_channel_id(guild_id))

        # Bind channel
        await self.repo.set_mod_log_channel_id(guild_id, 888888)
        self.assertEqual(await self.repo.get_mod_log_channel_id(guild_id), 888888)

        # Update channel
        await self.repo.set_mod_log_channel_id(guild_id, 999999)
        self.assertEqual(await self.repo.get_mod_log_channel_id(guild_id), 999999)

        # Unbind channel
        await self.repo.set_mod_log_channel_id(guild_id, None)
        self.assertIsNone(await self.repo.get_mod_log_channel_id(guild_id))


class TestPermissionsAndHierarchy(unittest.TestCase):
    """Test role hierarchy, ownership protection, and bot permission validation."""

    def setUp(self) -> None:
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.owner_id = 100
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = 999

    def _create_member(self, member_id: int, top_role_pos: int) -> MagicMock:
        member = MagicMock(spec=discord.Member)
        member.id = member_id
        member.guild = self.guild
        role = MagicMock(spec=discord.Role)
        role.position = top_role_pos
        role.__ge__ = lambda s, o: s.position >= o.position
        role.__lt__ = lambda s, o: s.position < o.position
        member.top_role = role
        return member

    def test_can_moderate_owner_protection(self) -> None:
        mod = self._create_member(200, top_role_pos=50)
        owner = self._create_member(100, top_role_pos=10)  # Owner even if low role
        allowed, reason = can_moderate(mod, owner)
        self.assertFalse(allowed)
        self.assertIn("cannot moderate the server owner", reason)

    def test_can_moderate_self_protection(self) -> None:
        mod = self._create_member(200, top_role_pos=50)
        allowed, reason = can_moderate(mod, mod)
        self.assertFalse(allowed)
        self.assertIn("cannot moderate yourself", reason)

    def test_can_moderate_bot_protection(self) -> None:
        mod = self._create_member(200, top_role_pos=50)
        bot_member = self._create_member(999, top_role_pos=10)
        allowed, reason = can_moderate(mod, bot_member)
        self.assertFalse(allowed)
        self.assertIn("cannot moderate the bot", reason)

    def test_can_moderate_equal_or_higher_role(self) -> None:
        mod = self._create_member(200, top_role_pos=20)
        target_equal = self._create_member(300, top_role_pos=20)
        target_higher = self._create_member(301, top_role_pos=25)
        target_lower = self._create_member(302, top_role_pos=15)

        # Equal
        allowed, reason = can_moderate(mod, target_equal)
        self.assertFalse(allowed)
        self.assertIn("equal or higher role", reason)

        # Higher
        allowed, reason = can_moderate(mod, target_higher)
        self.assertFalse(allowed)
        self.assertIn("equal or higher role", reason)

        # Lower
        allowed, reason = can_moderate(mod, target_lower)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_owner_can_moderate_anyone(self) -> None:
        owner_mod = self._create_member(100, top_role_pos=10)
        target_higher = self._create_member(300, top_role_pos=50)
        allowed, reason = can_moderate(owner_mod, target_higher)
        self.assertTrue(allowed)

    def test_bot_can_moderate(self) -> None:
        bot_member = self._create_member(999, top_role_pos=30)
        target_higher = self._create_member(400, top_role_pos=40)
        target_lower = self._create_member(401, top_role_pos=20)
        owner = self._create_member(100, top_role_pos=5)

        # Target is owner
        allowed, reason = bot_can_moderate(bot_member, owner)
        self.assertFalse(allowed)

        # Target higher role than bot
        allowed, reason = bot_can_moderate(bot_member, target_higher)
        self.assertFalse(allowed)

        # Target lower role than bot
        allowed, reason = bot_can_moderate(bot_member, target_lower)
        self.assertTrue(allowed)

    def test_check_bot_permissions(self) -> None:
        bot_member = MagicMock(spec=discord.Member)
        perms = MagicMock()
        perms.ban_members = True
        perms.kick_members = False
        bot_member.guild_permissions = perms

        allowed, missing = check_bot_permissions(bot_member, ban_members=True)
        self.assertTrue(allowed)
        self.assertEqual(missing, [])

        allowed, missing = check_bot_permissions(bot_member, ban_members=True, kick_members=True)
        self.assertFalse(allowed)
        self.assertEqual(missing, ["Kick Members"])


class TestModerationService(unittest.IsolatedAsyncioTestCase):
    """Test ModerationService business logic and orchestration."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.test_dir, "service_test.db"))
        await self.db.initialize()
        self.repo = ModerationRepository(self.db)
        self.bot = MagicMock()
        self.service = ModerationService(self.bot, self.repo)

        # Setup mock guild
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 5555
        self.guild.name = "Kingdom of Celesteria"
        self.guild.icon = None
        self.guild.owner_id = 1

        # Setup mock bot member
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = 99
        self.guild.me.guild = self.guild
        self.guild.me.guild_permissions.kick_members = True
        self.guild.me.guild_permissions.ban_members = True
        self.guild.me.guild_permissions.moderate_members = True
        self.guild.me.guild_permissions.manage_messages = True
        bot_role = MagicMock(position=50)
        bot_role.__ge__ = lambda s, o: s.position >= o.position
        bot_role.__lt__ = lambda s, o: s.position < o.position
        self.guild.me.top_role = bot_role

        # Setup mock moderator
        self.moderator = MagicMock(spec=discord.Member)
        self.moderator.id = 10
        self.moderator.guild = self.guild
        self.moderator.__str__ = lambda s: "GrandDuke#0001"
        mod_role = MagicMock(position=40)
        mod_role.__ge__ = lambda s, o: s.position >= o.position
        mod_role.__lt__ = lambda s, o: s.position < o.position
        self.moderator.top_role = mod_role

        # Setup mock target
        self.target = MagicMock(spec=discord.Member)
        self.target.id = 20
        self.target.guild = self.guild
        self.target.__str__ = lambda s: "Squire#0001"
        self.target.send = AsyncMock()
        self.target.kick = AsyncMock()
        self.target.ban = AsyncMock()
        self.target.timeout = AsyncMock()
        target_role = MagicMock(position=10)
        target_role.__ge__ = lambda s, o: s.position >= o.position
        target_role.__lt__ = lambda s, o: s.position < o.position
        self.target.top_role = target_role

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_execute_warn(self) -> None:
        case, dm_sent = await self.service.execute_warn(
            self.guild, self.moderator, self.target, "Disrespecting nobility"
        )
        self.assertEqual(case.case_id, 1)
        self.assertEqual(case.action, "warn")
        self.assertTrue(dm_sent)
        self.target.send.assert_awaited_once()

    async def test_execute_kick(self) -> None:
        case, dm_sent = await self.service.execute_kick(
            self.guild, self.moderator, self.target, "Mutiny"
        )
        self.assertEqual(case.case_id, 1)
        self.assertEqual(case.action, "kick")
        self.target.kick.assert_awaited_once()

    async def test_execute_ban(self) -> None:
        self.guild.ban = AsyncMock()
        case, dm_sent = await self.service.execute_ban(
            self.guild, self.moderator, self.target, "High Treason", delete_days=1
        )
        self.assertEqual(case.case_id, 1)
        self.assertEqual(case.action, "ban")
        self.guild.ban.assert_awaited_once()

    async def test_execute_timeout(self) -> None:
        case, dm_sent = await self.service.execute_timeout(
            self.guild, self.moderator, self.target, 600, "Spamming tavern"
        )
        self.assertEqual(case.case_id, 1)
        self.assertEqual(case.action, "timeout")
        self.assertEqual(case.duration_seconds, 600)
        self.target.timeout.assert_awaited_once()

    async def test_execute_clear(self) -> None:
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = self.guild
        channel.name = "tavern-hall"
        channel.id = 888
        fake_deleted = [MagicMock(), MagicMock(), MagicMock()]
        channel.purge = AsyncMock(return_value=fake_deleted)

        count, case = await self.service.execute_clear(
            channel, self.moderator, 3, "Tavern brawl cleanup"
        )
        self.assertEqual(count, 3)
        self.assertEqual(case.action, "clear")
        channel.purge.assert_awaited_once()

    async def test_hierarchy_rejection(self) -> None:
        # Elevate target role above moderator
        superior_role = MagicMock(position=45)
        superior_role.__ge__ = lambda s, o: s.position >= o.position
        superior_role.__lt__ = lambda s, o: s.position < o.position
        self.target.top_role = superior_role

        with self.assertRaises(PermissionError):
            await self.service.execute_kick(self.guild, self.moderator, self.target, "Invalid decree")

        # Verify kick was never called
        self.target.kick.assert_not_called()


class TestBotCogsIntegration(unittest.IsolatedAsyncioTestCase):
    """Test full Bot initialization, cog extensions, command loading, and help categories."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        db_path = os.path.join(self.test_dir, "bot_test.db")
        self.config = Config(
            token="dummy_token_test",
            prefix="!c",
            env="development",
            version="1.0.0-test",
            log_level="ERROR",
            database_path=db_path,
            test_guild_id=None,
        )
        self.bot = Celesteria(self.config)

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_cogs_and_commands_registered(self) -> None:
        # Load extensions directly
        await self.bot.db.initialize()
        await self.bot.load_extension("cogs.core")
        await self.bot.load_extension("cogs.moderation")

        # Verify cogs loaded
        self.assertIn("Core", self.bot.cogs)
        self.assertIn("Moderation", self.bot.cogs)

        # Verify Phase 1 commands
        core_commands = [c.name for c in self.bot.get_cog("Core").get_commands()]
        self.assertIn("ping", core_commands)
        self.assertIn("help", core_commands)
        self.assertIn("userinfo", core_commands)
        self.assertIn("sync", core_commands)

        # Verify Phase 2 commands
        mod_commands = [c.name for c in self.bot.get_cog("Moderation").get_commands()]
        expected_mod_commands = ["warn", "kick", "ban", "timeout", "clear", "cases", "setmodlog"]
        for cmd in expected_mod_commands:
            self.assertIn(cmd, mod_commands, f"Command '{cmd}' not found in ModerationCog")

        # Verify HelpView category discovery
        help_select = HelpCategorySelect(self.bot)
        category_values = [opt.value for opt in help_select.options]
        self.assertIn("Core", category_values)
        self.assertIn("Moderation", category_values)


if __name__ == "__main__":
    unittest.main()

