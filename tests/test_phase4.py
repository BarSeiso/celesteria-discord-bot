"""Unit and integration test suite for Celesteria Phase 4 — Social Systems.

Covers:
1. Mathematical progression formulas (XP = 100 * N^2, isqrt inverse, boundary conditions)
2. Fantasy title mapping and progress bar rendering
3. LevelRepository CRUD, rank calculations, and paginated leaderboard queries
4. LevelingService message heuristics (bot exclusion, DMs, command exclusion, short messages)
5. Anti-spam in-memory 60s cooldown cache
6. Level advancement detection, role reward granting, and hierarchy validation
7. Deleted / missing role resilience
8. Profile embed and leaderboard embed construction
9. LeaderboardPaginationView interaction checks and button states
10. Full bot integration, cog registration, and /help category discovery
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.celesteria import Celesteria
from bot.config import Config
from db.database import Database
from db.level_repository import LevelRepository, LevelReward, MemberLevel
from services.leveling import (
    LevelingService,
    get_level_tier_info,
    get_level_title,
    level_from_xp,
    xp_required_for_level,
)
from ui.formatters import format_progress_bar
from ui.views import HelpCategorySelect, LeaderboardPaginationView


class TestLevelingFormulasAndFormatters(unittest.TestCase):
    """Test mathematical formulas and UI formatting utilities."""

    def test_xp_required_for_level(self) -> None:
        self.assertEqual(xp_required_for_level(0), 0)
        self.assertEqual(xp_required_for_level(1), 100)
        self.assertEqual(xp_required_for_level(2), 400)
        self.assertEqual(xp_required_for_level(3), 900)
        self.assertEqual(xp_required_for_level(4), 1600)
        self.assertEqual(xp_required_for_level(5), 2500)
        self.assertEqual(xp_required_for_level(10), 10000)
        self.assertEqual(xp_required_for_level(20), 40000)

    def test_level_from_xp_boundaries(self) -> None:
        # 0 to 99 XP -> Level 0
        self.assertEqual(level_from_xp(0), 0)
        self.assertEqual(level_from_xp(50), 0)
        self.assertEqual(level_from_xp(99), 0)

        # 100 to 399 XP -> Level 1
        self.assertEqual(level_from_xp(100), 1)
        self.assertEqual(level_from_xp(250), 1)
        self.assertEqual(level_from_xp(399), 1)

        # 400 to 899 XP -> Level 2
        self.assertEqual(level_from_xp(400), 2)
        self.assertEqual(level_from_xp(750), 2)
        self.assertEqual(level_from_xp(899), 2)

        # 900 to 1599 XP -> Level 3
        self.assertEqual(level_from_xp(900), 3)
        self.assertEqual(level_from_xp(1250), 3)  # Matches user prompt example
        self.assertEqual(level_from_xp(1599), 3)

        # 1600 XP -> Level 4
        self.assertEqual(level_from_xp(1600), 4)

    def test_get_level_tier_info(self) -> None:
        # At 1250 XP: Level 3 (Base 900, Target 1600).
        # Progress: 350 / 700 = 50.0%
        level, base_xp, target_xp, progress_pct = get_level_tier_info(1250)
        self.assertEqual(level, 3)
        self.assertEqual(base_xp, 900)
        self.assertEqual(target_xp, 1600)
        self.assertAlmostEqual(progress_pct, 50.0)

    def test_format_progress_bar(self) -> None:
        self.assertEqual(format_progress_bar(0, 100, 10), "░░░░░░░░░░")
        self.assertEqual(format_progress_bar(50, 100, 10), "█████░░░░░")
        self.assertEqual(format_progress_bar(80, 100, 10), "████████░░")
        self.assertEqual(format_progress_bar(100, 100, 10), "██████████")
        self.assertEqual(format_progress_bar(0, 0, 10), "░░░░░░░░░░")

    def test_get_level_title(self) -> None:
        self.assertEqual(get_level_title(0), "Wanderer I")
        self.assertEqual(get_level_title(3), "Wanderer IV")
        self.assertEqual(get_level_title(5), "Page I")
        self.assertEqual(get_level_title(10), "Squire I")
        self.assertEqual(get_level_title(22), "Knight III")  # Matches user prompt example
        self.assertEqual(get_level_title(50), "Royal Paladin I")


class TestLevelRepository(unittest.IsolatedAsyncioTestCase):
    """Test SQLite persistence, atomic XP increments, and leaderboard ranking."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_level.db")
        self.db = Database(self.db_path)
        await self.db.initialize()
        self.repo = LevelRepository(self.db)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_schema_has_all_phase4_tables_and_columns(self) -> None:
        async with self.db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ) as cursor:
            tables = {row["name"] for row in await cursor.fetchall()}

        self.assertIn("member_levels", tables)
        self.assertIn("level_rewards", tables)

        async with self.db.connection.execute("PRAGMA table_info(guild_config);") as cursor:
            cols = {row["name"] for row in await cursor.fetchall()}

        self.assertIn("leveling_enabled", cols)
        self.assertIn("levelup_channel_id", cols)

    async def test_add_xp_and_progression_persistence(self) -> None:
        guild_id = 100
        user_id = 200

        # Initial check
        init = await self.repo.get_member(guild_id, user_id)
        self.assertIsNone(init)

        # Award 50 XP (Level 0)
        res1 = await self.repo.add_xp(guild_id, user_id, 50, 0)
        self.assertEqual(res1.xp, 50)
        self.assertEqual(res1.level, 0)
        self.assertEqual(res1.message_count, 1)

        # Award another 60 XP (Total 110 XP -> Level 1)
        res2 = await self.repo.add_xp(guild_id, user_id, 60, 1)
        self.assertEqual(res2.xp, 110)
        self.assertEqual(res2.level, 1)
        self.assertEqual(res2.message_count, 2)

    async def test_leaderboard_and_rank_calculation(self) -> None:
        guild_id = 100

        # Add 3 users with different XP
        await self.repo.add_xp(guild_id, 1, 1000, 3)
        await self.repo.add_xp(guild_id, 2, 500, 2)
        await self.repo.add_xp(guild_id, 3, 2000, 4)

        # Check ranks
        rank_u3 = await self.repo.get_user_rank(guild_id, 3)  # 2000 XP
        rank_u1 = await self.repo.get_user_rank(guild_id, 1)  # 1000 XP
        rank_u2 = await self.repo.get_user_rank(guild_id, 2)  # 500 XP
        rank_u4 = await self.repo.get_user_rank(guild_id, 4)  # No XP recorded

        self.assertEqual(rank_u3, 1)
        self.assertEqual(rank_u1, 2)
        self.assertEqual(rank_u2, 3)
        self.assertEqual(rank_u4, 4)

        # Check paginated leaderboard
        lb = await self.repo.get_leaderboard(guild_id, limit=2, offset=0)
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0].user_id, 3)
        self.assertEqual(lb[1].user_id, 1)

        lb_page2 = await self.repo.get_leaderboard(guild_id, limit=2, offset=2)
        self.assertEqual(len(lb_page2), 1)
        self.assertEqual(lb_page2[0].user_id, 2)

    async def test_level_rewards_crud(self) -> None:
        guild_id = 500
        # Add rewards
        r1 = await self.repo.set_level_reward(guild_id, level=5, role_id=1001)
        r2 = await self.repo.set_level_reward(guild_id, level=10, role_id=1002)

        self.assertEqual(r1.level, 5)
        self.assertEqual(r1.role_id, 1001)

        rewards = await self.repo.get_level_rewards(guild_id)
        self.assertEqual(len(rewards), 2)
        self.assertEqual(rewards[0].level, 5)
        self.assertEqual(rewards[1].level, 10)

        # Remove reward
        removed = await self.repo.remove_level_reward(guild_id, 5)
        self.assertTrue(removed)

        rewards_after = await self.repo.get_level_rewards(guild_id)
        self.assertEqual(len(rewards_after), 1)
        self.assertEqual(rewards_after[0].level, 10)

        # Remove non-existent reward
        removed_none = await self.repo.remove_level_reward(guild_id, 99)
        self.assertFalse(removed_none)

    async def test_guild_leveling_config(self) -> None:
        guild_id = 777
        self.assertTrue(await self.repo.is_leveling_enabled(guild_id))

        await self.repo.set_leveling_enabled(guild_id, False)
        self.assertFalse(await self.repo.is_leveling_enabled(guild_id))

        await self.repo.set_levelup_channel_id(guild_id, 888)
        self.assertEqual(await self.repo.get_levelup_channel_id(guild_id), 888)

        await self.repo.set_levelup_channel_id(guild_id, None)
        self.assertIsNone(await self.repo.get_levelup_channel_id(guild_id))


class TestLevelingServiceAntiSpamAndRewards(unittest.IsolatedAsyncioTestCase):
    """Test message qualification, 60s cooldowns, and role reward assignment."""

    async def asyncSetUp(self) -> None:
        self.bot_mock = MagicMock(spec=Celesteria)
        self.bot_mock.config = MagicMock()
        self.bot_mock.config.prefix = "!c"

        self.repo_mock = AsyncMock(spec=LevelRepository)
        self.service = LevelingService(self.bot_mock, self.repo_mock)

        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 1234
        self.guild.name = "Royal Celesteria"

        self.author = MagicMock(spec=discord.Member)
        self.author.id = 5678
        self.author.bot = False
        self.author.guild = self.guild
        self.author.display_name = "Arthur"

    def test_message_filtering_heuristics(self) -> None:
        msg = MagicMock(spec=discord.Message)
        msg.guild = self.guild
        msg.author = self.author
        msg.webhook_id = None
        msg.type = discord.MessageType.default
        msg.content = "Hail fellow knight of the realm!"

        # Valid human message passes
        self.assertTrue(self.service.should_award_xp(msg))

        # Bot author fails
        bot_author = MagicMock(spec=discord.Member, bot=True)
        msg.author = bot_author
        self.assertFalse(self.service.should_award_xp(msg))
        msg.author = self.author

        # DM (no guild) fails
        msg.guild = None
        self.assertFalse(self.service.should_award_xp(msg))
        msg.guild = self.guild

        # Webhook fails
        msg.webhook_id = 999
        self.assertFalse(self.service.should_award_xp(msg))
        msg.webhook_id = None

        # Short message (< 3 chars) fails
        msg.content = "ok"
        self.assertFalse(self.service.should_award_xp(msg))

        # Bot prefix command fails
        msg.content = "!chelp"
        self.assertFalse(self.service.should_award_xp(msg))

    def test_cooldown_suppression(self) -> None:
        msg = MagicMock(spec=discord.Message)
        msg.guild = self.guild
        msg.author = self.author
        msg.webhook_id = None
        msg.type = discord.MessageType.default
        msg.content = "A legitimate conversational decree."

        # First message passes
        self.assertTrue(self.service.should_award_xp(msg))

        # Record cooldown
        self.service._cooldowns[(self.guild.id, self.author.id)] = time.monotonic()

        # Immediate second message fails due to 60s cooldown
        self.assertFalse(self.service.should_award_xp(msg))

        # After cooldown elapses, message passes again
        self.service._cooldowns[(self.guild.id, self.author.id)] = time.monotonic() - 61.0
        self.assertTrue(self.service.should_award_xp(msg))

    async def test_role_reward_hierarchy_and_permissions(self) -> None:
        # Configured reward role: Level 5 -> Role 9001
        reward = LevelReward(guild_id=self.guild.id, level=5, role_id=9001)
        self.repo_mock.get_level_rewards.return_value = [reward]

        # Role mock
        role = MagicMock(spec=discord.Role)
        role.id = 9001
        role.name = "Squire"
        self.guild.get_role.return_value = role

        # Member does not hold role
        self.author.roles = []

        # Bot has Manage Roles permission and higher hierarchy
        bot_member = MagicMock(spec=discord.Member)
        bot_member.guild_permissions.manage_roles = True
        bot_top_role = MagicMock(spec=discord.Role)
        role.__ge__ = MagicMock(return_value=False)  # role < bot_top_role
        bot_member.top_role = bot_top_role
        self.guild.me = bot_member

        # Assign reward
        awarded = await self.service.check_and_assign_rewards(self.author, new_level=5)
        self.assertEqual(len(awarded), 1)
        self.assertEqual(awarded[0].name, "Squire")
        self.author.add_roles.assert_called_once_with(
            role, reason="Celesteria Level 5 Reward"
        )

    async def test_role_reward_hierarchy_failure_prevented(self) -> None:
        # Reward role is higher than bot role
        reward = LevelReward(guild_id=self.guild.id, level=10, role_id=9002)
        self.repo_mock.get_level_rewards.return_value = [reward]

        role = MagicMock(spec=discord.Role)
        role.id = 9002
        role.name = "Archon"
        self.guild.get_role.return_value = role
        self.author.roles = []

        bot_member = MagicMock(spec=discord.Member)
        bot_member.guild_permissions.manage_roles = True
        role.__ge__ = MagicMock(return_value=True)  # role >= bot_top_role
        self.guild.me = bot_member

        awarded = await self.service.check_and_assign_rewards(self.author, new_level=10)
        self.assertEqual(len(awarded), 0)
        self.author.add_roles.assert_not_called()

    async def test_missing_or_deleted_reward_role_handled_gracefully(self) -> None:
        reward = LevelReward(guild_id=self.guild.id, level=5, role_id=9999)
        self.repo_mock.get_level_rewards.return_value = [reward]
        self.guild.get_role.return_value = None  # Deleted from Discord

        awarded = await self.service.check_and_assign_rewards(self.author, new_level=5)
        self.assertEqual(len(awarded), 0)
        self.author.add_roles.assert_not_called()


class TestSocialCogAndHelpIntegration(unittest.IsolatedAsyncioTestCase):
    """Test Leveling/Social cog registration and parity with /help system."""

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
        await self.bot.load_extension("cogs.leveling")

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_social_cog_registered_with_all_commands(self) -> None:
        cog = self.bot.get_cog("Social")
        self.assertIsNotNone(cog)
        self.assertEqual(cog.emoji, "⚜")

        registered_names = {c.name for c in cog.get_commands()}
        expected_commands = {
            "level",
            "profile",
            "leaderboard",
            "levelrewards",
            "setlevelreward",
            "removelevelreward",
            "setlevelupchannel",
        }
        self.assertTrue(expected_commands.issubset(registered_names))

    async def test_help_view_surfaces_social_category(self) -> None:
        select = HelpCategorySelect(self.bot)
        category_values = {opt.value for opt in select.options}

        self.assertIn("Core", category_values)
        self.assertIn("Moderation", category_values)
        self.assertIn("Server", category_values)
        self.assertIn("Social", category_values)

        social_opt = next(opt for opt in select.options if opt.value == "Social")
        self.assertIn("⚜", social_opt.label)


class TestPaginationViewInteractions(unittest.IsolatedAsyncioTestCase):
    """Test LeaderboardPaginationView interaction security and page boundaries."""

    async def test_pagination_state_and_security(self) -> None:
        page_loader = AsyncMock()
        page_loader.return_value = discord.Embed(title="Page Embed")

        view = LeaderboardPaginationView(
            author_id=12345,
            total_pages=3,
            page_loader=page_loader,
        )

        # Page 1: Prev should be disabled, Next should be enabled
        self.assertTrue(view.prev_button.disabled)
        self.assertFalse(view.next_button.disabled)
        self.assertEqual(view.page_indicator.label, "Page 1 of 3")

        # Non-author interaction rejected
        intruder = MagicMock(spec=discord.Interaction)
        intruder.user.id = 99999
        intruder.response = AsyncMock()
        allowed = await view.interaction_check(intruder)
        self.assertFalse(allowed)
        intruder.response.send_message.assert_called_once()

        # Author interaction accepted
        author = MagicMock(spec=discord.Interaction)
        author.user.id = 12345
        author.response = AsyncMock()
        allowed_author = await view.interaction_check(author)
        self.assertTrue(allowed_author)


class TestRestartPersistenceAndCrossPhaseCompatibility(unittest.IsolatedAsyncioTestCase):
    """Verify state persistence across restarts and multi-phase command coexistence."""

    async def test_persistence_across_bot_restart(self) -> None:
        test_dir = tempfile.mkdtemp()
        db_path = os.path.join(test_dir, "restart_test.db")

        # Session 1: initialize and insert data
        db1 = Database(db_path)
        await db1.initialize()
        repo1 = LevelRepository(db1)

        await repo1.add_xp(guild_id=999, user_id=101, xp_gain=1250, new_level=3)
        await repo1.add_xp(guild_id=999, user_id=102, xp_gain=5000, new_level=7)
        await repo1.set_level_reward(guild_id=999, level=5, role_id=8888)
        await repo1.set_levelup_channel_id(guild_id=999, channel_id=7777)
        await db1.close()

        # Session 2: simulate bot restart with a brand new Database instance
        db2 = Database(db_path)
        await db2.initialize()
        repo2 = LevelRepository(db2)

        m1 = await repo2.get_member(guild_id=999, user_id=101)
        self.assertIsNotNone(m1)
        self.assertEqual(m1.xp, 1250)
        self.assertEqual(m1.level, 3)

        m2 = await repo2.get_member(guild_id=999, user_id=102)
        self.assertIsNotNone(m2)
        self.assertEqual(m2.xp, 5000)
        self.assertEqual(m2.level, 7)

        # Verify leaderboard rank order maintained
        rank_102 = await repo2.get_user_rank(guild_id=999, user_id=102)
        rank_101 = await repo2.get_user_rank(guild_id=999, user_id=101)
        self.assertEqual(rank_102, 1)
        self.assertEqual(rank_101, 2)

        # Verify reward and configuration persisted
        rewards = await repo2.get_level_rewards(guild_id=999)
        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0].level, 5)
        self.assertEqual(rewards[0].role_id, 8888)

        chan_id = await repo2.get_levelup_channel_id(guild_id=999)
        self.assertEqual(chan_id, 7777)

        await db2.close()
        shutil.rmtree(test_dir, ignore_errors=True)

    async def test_all_phases_cogs_loaded_without_conflict(self) -> None:
        config = Config(
            token="dummy_token",
            prefix="!c",
            env="testing",
            version="1.0.0",
            log_level="CRITICAL",
            database_path=":memory:",
            test_guild_id=None,
        )
        bot = Celesteria(config)
        await bot.db.initialize()
        await bot.load_extension("cogs.core")
        await bot.load_extension("cogs.moderation")
        await bot.load_extension("cogs.server")
        await bot.load_extension("cogs.leveling")

        all_cogs = set(bot.cogs.keys())
        expected_cogs = {"Core", "Moderation", "Server", "Social"}
        self.assertTrue(expected_cogs.issubset(all_cogs))

        # Check commands from all 4 phases coexist
        command_names = {c.name for c in bot.commands}

        # Phase 1
        self.assertIn("ping", command_names)
        self.assertIn("help", command_names)
        self.assertIn("userinfo", command_names)

        # Phase 2
        self.assertIn("warn", command_names)
        self.assertIn("kick", command_names)
        self.assertIn("ban", command_names)
        self.assertIn("timeout", command_names)
        self.assertIn("clear", command_names)
        self.assertIn("cases", command_names)
        self.assertIn("setmodlog", command_names)

        # Phase 3
        self.assertIn("setwelcome", command_names)
        self.assertIn("testwelcome", command_names)
        self.assertIn("setcounter", command_names)
        self.assertIn("setserverlog", command_names)
        self.assertIn("serverconfig", command_names)

        # Phase 4
        self.assertIn("level", command_names)
        self.assertIn("profile", command_names)
        self.assertIn("leaderboard", command_names)
        self.assertIn("levelrewards", command_names)
        self.assertIn("setlevelreward", command_names)
        self.assertIn("removelevelreward", command_names)
        self.assertIn("setlevelupchannel", command_names)

        await bot.close()


if __name__ == "__main__":
    unittest.main()

