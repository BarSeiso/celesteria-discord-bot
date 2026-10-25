"""Moderation domain service.

Coordinates hierarchy validation, target DM notifications, Discord API actions,
database persistence, and guild mod log channel dispatching.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord

from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette
from utils.duration import format_duration
from utils.permissions import bot_can_moderate, can_moderate, check_bot_permissions

if TYPE_CHECKING:
    from bot.celesteria import Celesteria
    from db.repository import ModerationCase, ModerationRepository

log = logging.getLogger("celesteria.services.moderation")


class ModerationService:
    """Domain service for royal moderation decrees."""

    def __init__(self, bot: Celesteria, repo: ModerationRepository) -> None:
        self.bot = bot
        self.repo = repo

    # ── Notification Helpers ────────────────────────────────────

    @staticmethod
    async def send_dm_decree(
        target: discord.Member | discord.User,
        guild: discord.Guild,
        action: str,
        reason: str,
        duration_text: str | None = None,
    ) -> bool:
        """Attempt to deliver a royal decree DM to the target before sanctions.

        Returns True if delivered, False if failed (closed DMs/bot).
        """
        try:
            embed = CelesteriaEmbed.moderation(
                f"Royal Decree — {action.title()}",
                f"A decree has been issued against you in **{guild.name}**.",
            )
            embed.add_field(name="Action", value=f"`{action.upper()}`", inline=True)
            if duration_text:
                embed.add_field(name="Duration", value=f"`{duration_text}`", inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)

            await target.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return False

    async def dispatch_mod_log(
        self,
        guild: discord.Guild,
        case: ModerationCase,
        *,
        extra_name: str | None = None,
        extra_value: str | None = None,
    ) -> None:
        """Publish a formatted decree case embed to the guild's mod log channel."""
        channel_id = await self.repo.get_mod_log_channel_id(guild.id)
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        embed = CelesteriaEmbed.moderation(
            f"Decree #{case.case_id} — {case.action.upper()}",
            "A decree has been recorded in the royal chronicles.",
        )
        embed.add_field(
            name="Target",
            value=f"<@{case.target_id}> (`{case.target_tag}` · `{case.target_id}`)",
            inline=True,
        )
        embed.add_field(
            name="Moderator",
            value=f"<@{case.moderator_id}> (`{case.moderator_tag}`)",
            inline=True,
        )
        embed.add_field(
            name="Action",
            value=f"`{case.action.upper()}`",
            inline=True,
        )
        if case.duration_seconds:
            embed.add_field(
                name="Duration",
                value=f"`{format_duration(case.duration_seconds)}`",
                inline=True,
            )
        if extra_name and extra_value:
            embed.add_field(name=extra_name, value=extra_value, inline=True)

        embed.add_field(name="Reason", value=case.reason, inline=False)
        embed.set_footer(text=f"Case #{case.case_id} │ {Brand.FOOTER}")

        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Unable to dispatch mod log to channel %d in guild %d",
                channel_id,
                guild.id,
            )

    # ── Decrees ─────────────────────────────────────────────────

    async def execute_warn(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        reason: str,
    ) -> tuple[ModerationCase, bool]:
        """Validate hierarchy, send DM, persist warn case, and dispatch mod log."""
        can_mod, err_msg = can_moderate(moderator, target)
        if not can_mod:
            raise PermissionError(err_msg)

        bot_can, bot_err = bot_can_moderate(guild.me, target)
        if not bot_can:
            raise PermissionError(bot_err)

        dm_sent = await self.send_dm_decree(target, guild, "Warn", reason)

        case = await self.repo.create_case(
            guild_id=guild.id,
            action="warn",
            target_id=target.id,
            target_tag=str(target),
            moderator_id=moderator.id,
            moderator_tag=str(moderator),
            reason=reason,
        )

        await self.dispatch_mod_log(guild, case)
        return case, dm_sent

    async def execute_kick(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        reason: str,
    ) -> tuple[ModerationCase, bool]:
        """Validate, send DM, kick member via Discord API, record case, and log."""
        can_mod, err_msg = can_moderate(moderator, target)
        if not can_mod:
            raise PermissionError(err_msg)

        bot_can, bot_err = bot_can_moderate(guild.me, target)
        if not bot_can:
            raise PermissionError(bot_err)

        has_perms, missing = check_bot_permissions(guild.me, kick_members=True)
        if not has_perms:
            raise PermissionError(f"I need permissions: {', '.join(missing)}")

        dm_sent = await self.send_dm_decree(target, guild, "Kick", reason)

        await target.kick(reason=f"[{moderator}] {reason}")

        case = await self.repo.create_case(
            guild_id=guild.id,
            action="kick",
            target_id=target.id,
            target_tag=str(target),
            moderator_id=moderator.id,
            moderator_tag=str(moderator),
            reason=reason,
        )

        await self.dispatch_mod_log(guild, case)
        return case, dm_sent

    async def execute_ban(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member | discord.User,
        reason: str,
        delete_days: int = 0,
    ) -> tuple[ModerationCase, bool]:
        """Validate, send DM, ban member/user, record case, and log."""
        member = guild.get_member(target.id) if isinstance(target, discord.User) else target
        if member:
            can_mod, err_msg = can_moderate(moderator, member)
            if not can_mod:
                raise PermissionError(err_msg)

            bot_can, bot_err = bot_can_moderate(guild.me, member)
            if not bot_can:
                raise PermissionError(bot_err)

        has_perms, missing = check_bot_permissions(guild.me, ban_members=True)
        if not has_perms:
            raise PermissionError(f"I need permissions: {', '.join(missing)}")

        dm_sent = await self.send_dm_decree(target, guild, "Ban", reason)

        delete_seconds = max(0, min(7, delete_days)) * 86400
        await guild.ban(
            target,
            reason=f"[{moderator}] {reason}",
            delete_message_seconds=delete_seconds,
        )

        case = await self.repo.create_case(
            guild_id=guild.id,
            action="ban",
            target_id=target.id,
            target_tag=str(target),
            moderator_id=moderator.id,
            moderator_tag=str(moderator),
            reason=reason,
            extra_data=f"Pruned {delete_days} days of messages" if delete_days > 0 else None,
        )

        await self.dispatch_mod_log(
            guild,
            case,
            extra_name="Purge Window" if delete_days > 0 else None,
            extra_value=f"{delete_days} days" if delete_days > 0 else None,
        )
        return case, dm_sent

    async def execute_timeout(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        duration_seconds: int,
        reason: str,
    ) -> tuple[ModerationCase, bool]:
        """Validate, send DM, apply Discord timeout, record case, and log."""
        can_mod, err_msg = can_moderate(moderator, target)
        if not can_mod:
            raise PermissionError(err_msg)

        bot_can, bot_err = bot_can_moderate(guild.me, target)
        if not bot_can:
            raise PermissionError(bot_err)

        has_perms, missing = check_bot_permissions(guild.me, moderate_members=True)
        if not has_perms:
            raise PermissionError(f"I need permissions: {', '.join(missing)}")

        duration_text = format_duration(duration_seconds)
        dm_sent = await self.send_dm_decree(
            target,
            guild,
            "Timeout",
            reason,
            duration_text=duration_text,
        )

        until_dt = discord.utils.utcnow() + timedelta(seconds=duration_seconds)
        await target.timeout(until_dt, reason=f"[{moderator}] {reason}")

        case = await self.repo.create_case(
            guild_id=guild.id,
            action="timeout",
            target_id=target.id,
            target_tag=str(target),
            moderator_id=moderator.id,
            moderator_tag=str(moderator),
            reason=reason,
            duration_seconds=duration_seconds,
        )

        await self.dispatch_mod_log(guild, case)
        return case, dm_sent

    async def execute_clear(
        self,
        channel: discord.TextChannel | discord.Thread,
        moderator: discord.Member,
        amount: int,
        reason: str | None = None,
    ) -> tuple[int, ModerationCase]:
        """Purge messages in a channel, record case, and log."""
        guild = channel.guild
        has_perms, missing = check_bot_permissions(guild.me, manage_messages=True)
        if not has_perms:
            raise PermissionError(f"I need permissions: {', '.join(missing)}")

        actual_reason = reason or "Royal purge decree"
        deleted = await channel.purge(limit=amount, reason=f"[{moderator}] {actual_reason}")
        deleted_count = len(deleted)

        case = await self.repo.create_case(
            guild_id=guild.id,
            action="clear",
            target_id=channel.id,
            target_tag=f"#{channel.name}",
            moderator_id=moderator.id,
            moderator_tag=str(moderator),
            reason=actual_reason,
            extra_data=f"{deleted_count} messages purged",
        )

        await self.dispatch_mod_log(
            guild,
            case,
            extra_name="Messages Cleared",
            extra_value=str(deleted_count),
        )
        return deleted_count, case
