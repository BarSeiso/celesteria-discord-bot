"""Command invocation and error path testing for Phase 1 and Phase 2 commands.

Verifies:
1. Phase 1 commands (ping, help, userinfo) functionality
2. Every Phase 2 command execution through Context
3. Hierarchy rejection in commands
4. Permission failure responses in commands
5. Invalid input handling in commands
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.celesteria import Celesteria
from bot.config import Config
from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette


class TestModerationCommandsExecution(unittest.IsolatedAsyncioTestCase):
    """Test cog command handlers with simulated contexts."""

    async def asyncSetUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "commands_test.db")
        self.config = Config(
            token="dummy_token_test",
            prefix="!c",
            env="development",
            version="1.0.0-test",
            log_level="ERROR",
            database_path=self.db_path,
            test_guild_id=None,
        )
        self.bot = Celesteria(self.config)
        await self.bot.db.initialize()
        await self.bot.load_extension("cogs.core")
        await self.bot.load_extension("cogs.moderation")

        self.core_cog = self.bot.get_cog("Core")
        self.mod_cog = self.bot.get_cog("Moderation")

        # Mock guild setup
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 7777
        self.guild.name = "Royal Celesteria"
        self.guild.icon = None
        self.guild.owner_id = 1

        # Bot member in guild
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = 999
        self.guild.me.guild = self.guild
        bot_role = MagicMock(position=50)
        bot_role.__ge__ = lambda s, o: s.position >= o.position
        bot_role.__lt__ = lambda s, o: s.position < o.position
        self.guild.me.top_role = bot_role
        perms = MagicMock()
        perms.kick_members = True
        perms.ban_members = True
        perms.moderate_members = True
        perms.manage_messages = True
        perms.send_messages = True
        perms.embed_links = True
        self.guild.me.guild_permissions = perms

        # Moderator member
        self.moderator = MagicMock(spec=discord.Member)
        self.moderator.id = 10
        self.moderator.guild = self.guild
        self.moderator.display_name = "LordCommander"
        self.moderator.mention = "<@10>"
        self.moderator.__str__ = lambda s: "LordCommander#0001"
        mod_role = MagicMock(position=40)
        mod_role.__ge__ = lambda s, o: s.position >= o.position
        mod_role.__lt__ = lambda s, o: s.position < o.position
        self.moderator.top_role = mod_role

        # Target member (lower role)
        self.target = MagicMock(spec=discord.Member)
        self.target.id = 20
        self.target.guild = self.guild
        self.target.display_name = "PeasantDave"
        self.target.mention = "<@20>"
        self.target.__str__ = lambda s: "PeasantDave#0001"
        self.target.send = AsyncMock()
        self.target.kick = AsyncMock()
        self.target.ban = AsyncMock()
        self.target.timeout = AsyncMock()
        target_role = MagicMock(position=10)
        target_role.__ge__ = lambda s, o: s.position >= o.position
        target_role.__lt__ = lambda s, o: s.position < o.position
        self.target.top_role = target_role

        # Target member (equal role)
        self.target_equal = MagicMock(spec=discord.Member)
        self.target_equal.id = 21
        self.target_equal.guild = self.guild
        self.target_equal.display_name = "LordEqual"
        self.target_equal.mention = "<@21>"
        self.target_equal.__str__ = lambda s: "LordEqual#0001"
        equal_role = MagicMock(position=40)
        equal_role.__ge__ = lambda s, o: s.position >= o.position
        equal_role.__lt__ = lambda s, o: s.position < o.position
        self.target_equal.top_role = equal_role

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_context(self) -> MagicMock:
        ctx = MagicMock(spec=commands.Context)
        ctx.bot = self.bot
        ctx.guild = self.guild
        ctx.author = self.moderator
        ctx.interaction = None
        ctx.message = MagicMock()
        ctx.message.delete = AsyncMock()
        ctx.send = AsyncMock()
        return ctx

    # ── Phase 1 Verification ────────────────────────────────────

    async def test_phase1_ping(self) -> None:
        ctx = self._create_mock_context()
        with patch.object(Celesteria, "latency", 0.042):
            await self.core_cog.ping(ctx)
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("Celesteria Status", embed.title)

    async def test_phase1_help(self) -> None:
        ctx = self._create_mock_context()
        await self.core_cog.help_command(ctx)
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        view = ctx.send.call_args.kwargs.get("view")
        self.assertIsNotNone(embed)
        self.assertIsNotNone(view)
        self.assertIn("Command Codex", embed.title)

    async def test_phase1_userinfo(self) -> None:
        ctx = self._create_mock_context()
        target_info = MagicMock(spec=discord.Member)
        target_info.display_name = "SirGalahad"
        target_info.mention = "<@55>"
        target_info.__str__ = lambda s: "SirGalahad#0001"
        target_info.colour = discord.Colour.default()
        target_info.display_avatar.url = "https://example.com/avatar.png"
        target_info.created_at = discord.utils.utcnow()
        target_info.joined_at = discord.utils.utcnow()
        target_info.roles = [self.guild.default_role]
        target_info.id = 55
        target_info.premium_since = None
        target_info.bot = False
        target_info.guild = self.guild

        await self.core_cog.userinfo(ctx, member=target_info)
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("SirGalahad", embed.title)

    # ── Phase 2 Verification: /warn ─────────────────────────────

    async def test_warn_success(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.warn(ctx, self.target, reason="Rule 1 breach")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("Warning Issued", embed.title)
        self.assertIn("Decree #1", embed.title)

    async def test_warn_hierarchy_denied(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.warn(ctx, self.target_equal, reason="Treason")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("Permission Denied", embed.title)
        self.assertIn("equal or higher role", embed.description)

    # ── Phase 2 Verification: /kick ─────────────────────────────

    async def test_kick_success(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.kick(ctx, self.target, reason="Insubordination")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("Member Banished", embed.title)
        self.target.kick.assert_awaited_once()

    async def test_kick_hierarchy_denied(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.kick(ctx, self.target_equal, reason="Insubordination")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Permission Denied", embed.title)
        self.target_equal.kick.assert_not_called()

    # ── Phase 2 Verification: /ban ──────────────────────────────

    async def test_ban_invalid_delete_days(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.ban(ctx, self.target, delete_days=10, reason="Exile")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Invalid Purge Window", embed.title)

    async def test_ban_hierarchy_denied_before_prompt(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.ban(ctx, self.target_equal, reason="Exile")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Permission Denied", embed.title)

    async def test_ban_confirmed(self) -> None:
        ctx = self._create_mock_context()
        self.guild.ban = AsyncMock()

        # Mock ConfirmView to return True on wait
        async def fake_wait(self_view):
            self_view.value = True

        with patch("cogs.moderation.ConfirmView.wait", side_effect=fake_wait, autospec=True):
            await self.mod_cog.ban(ctx, self.target, delete_days=1, reason="High Treason")

        self.assertEqual(ctx.send.await_count, 2)  # 1 prompt + 1 success decree
        final_call_embed = ctx.send.call_args_list[1].kwargs.get("embed")
        self.assertIn("Permanent Exile", final_call_embed.title)
        self.guild.ban.assert_awaited_once()

    async def test_ban_cancelled(self) -> None:
        ctx = self._create_mock_context()
        self.guild.ban = AsyncMock()

        # Mock ConfirmView to return False on wait
        async def fake_wait(self_view):
            self_view.value = False

        with patch("cogs.moderation.ConfirmView.wait", side_effect=fake_wait, autospec=True):
            await self.mod_cog.ban(ctx, self.target, reason="High Treason")

        self.assertEqual(ctx.send.await_count, 2)  # 1 prompt + 1 cancel embed
        final_call_embed = ctx.send.call_args_list[1].kwargs.get("embed")
        self.assertIn("Decree Cancelled", final_call_embed.title)
        self.guild.ban.assert_not_called()

    # ── Phase 2 Verification: /timeout ──────────────────────────

    async def test_timeout_success(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.timeout(ctx, self.target, duration="15m", reason="Rowdy behavior")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Member Silenced", embed.title)
        self.target.timeout.assert_awaited_once()

    async def test_timeout_invalid_duration(self) -> None:
        ctx = self._create_mock_context()
        await self.mod_cog.timeout(ctx, self.target, duration="999d", reason="Too long")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Invalid Duration", embed.title)
        self.target.timeout.assert_not_called()

    # ── Phase 2 Verification: /clear ────────────────────────────

    async def test_clear_success(self) -> None:
        ctx = self._create_mock_context()
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 333
        channel.guild = self.guild
        channel.mention = "<#333>"
        channel.name = "general"
        deleted = [MagicMock() for _ in range(5)]
        channel.purge = AsyncMock(return_value=deleted)
        ctx.channel = channel

        await self.mod_cog.clear(ctx, amount=5, reason="Cleaning hall")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Purge Decree Executed", embed.title)
        channel.purge.assert_awaited_once()

    async def test_clear_invalid_amount(self) -> None:
        ctx = self._create_mock_context()
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = self.guild
        ctx.channel = channel

        await self.mod_cog.clear(ctx, amount=0)
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Invalid Quantity", embed.title)

        await self.mod_cog.clear(ctx, amount=101)
        self.assertEqual(ctx.send.await_count, 2)
        embed2 = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Invalid Quantity", embed2.title)

    # ── Phase 2 Verification: /cases ────────────────────────────

    async def test_cases_member_and_id_lookup(self) -> None:
        ctx = self._create_mock_context()

        # Seed 1 case
        await self.bot.moderation_service.execute_warn(
            self.guild, self.moderator, self.target, "Initial warn"
        )

        # Lookup by case ID
        await self.mod_cog.cases(ctx, case_id=1)
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Decree #1 — WARN", embed.title)

        # Lookup by member
        await self.mod_cog.cases(ctx, member=self.target)
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Decrees for PeasantDave", embed.title)

        # Lookup nonexistent case ID
        await self.mod_cog.cases(ctx, case_id=999)
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Decree Not Found", embed.title)

    # ── Phase 2 Verification: /setmodlog ────────────────────────

    async def test_setmodlog_bind_and_unbind(self) -> None:
        ctx = self._create_mock_context()
        log_channel = MagicMock(spec=discord.TextChannel)
        log_channel.id = 9999
        log_channel.mention = "<#9999>"
        log_perms = MagicMock()
        log_perms.send_messages = True
        log_perms.embed_links = True
        log_channel.permissions_for = MagicMock(return_value=log_perms)

        # Bind
        await self.mod_cog.setmodlog(ctx, channel=log_channel)
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Decree Log Configured", embed.title)
        self.assertEqual(
            await self.bot.moderation_repo.get_mod_log_channel_id(self.guild.id),
            9999,
        )

        # Unbind
        await self.mod_cog.setmodlog(ctx, channel=None)
        embed = ctx.send.call_args.kwargs.get("embed")
        self.assertIn("Decree Log Unbound", embed.title)
        self.assertIsNone(
            await self.bot.moderation_repo.get_mod_log_channel_id(self.guild.id)
        )


if __name__ == "__main__":
    unittest.main()
