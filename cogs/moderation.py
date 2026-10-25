"""Celesteria Moderation Cog.

Provides hybrid commands for server moderation:
- /warn, !cwarn
- /kick, !ckick
- /ban, !cban
- /timeout, !ctimeout
- /clear, !cclear
- /cases, !ccases
- /setmodlog, !csetmodlog
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette
from ui.views import ConfirmView
from utils.duration import format_duration, parse_duration
from utils.permissions import bot_can_moderate, can_moderate, check_bot_permissions

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.cogs.moderation")


class ModerationCog(commands.Cog, name="Moderation"):
    """Royal decree & moderation commands."""

    emoji = "⚔"
    help_description = "Royal decree & server moderation"

    def __init__(self, bot: Celesteria) -> None:
        self.bot = bot
        self.service = bot.moderation_service
        self.repo = bot.moderation_repo

    # ── /warn · !cwarn ──────────────────────────────────────────

    @commands.hybrid_command(
        name="warn",
        description="Issue a formal royal warning to a member",
    )
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(
        member="The member to warn",
        reason="Reason for the decree",
    )
    async def warn(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Issue a formal warning recorded in the realm's annals."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        try:
            case, dm_sent = await self.service.execute_warn(
                ctx.guild,
                ctx.author,
                member,
                reason,
            )
        except PermissionError as exc:
            await ctx.send(embed=CelesteriaEmbed.permission_denied(str(exc)))
            return

        embed = CelesteriaEmbed.moderation(
            f"Decree #{case.case_id} — Warning Issued",
            f"**{member.display_name}** has been formally warned in the royal records.",
        )
        embed.add_field(name="Target", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        footer_text = (
            f"Case #{case.case_id} · Decree delivered to DM │ {Brand.FOOTER}"
            if dm_sent
            else f"Case #{case.case_id} · DM could not be delivered │ {Brand.FOOTER}"
        )
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    # ── /kick · !ckick ──────────────────────────────────────────

    @commands.hybrid_command(
        name="kick",
        description="Banish a member from the realm",
    )
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(
        member="The member to banish",
        reason="Reason for the decree",
    )
    async def kick(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Banish a member from the server."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        try:
            case, dm_sent = await self.service.execute_kick(
                ctx.guild,
                ctx.author,
                member,
                reason,
            )
        except PermissionError as exc:
            await ctx.send(embed=CelesteriaEmbed.permission_denied(str(exc)))
            return
        except discord.Forbidden:
            await ctx.send(
                embed=CelesteriaEmbed.error(
                    "Action Prohibited",
                    "Discord denied the banishment decree. Verify bot role hierarchy.",
                )
            )
            return

        embed = CelesteriaEmbed.moderation(
            f"Decree #{case.case_id} — Member Banished",
            f"**{member.display_name}** has been cast out from the realm.",
        )
        embed.add_field(name="Target", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        footer_text = (
            f"Case #{case.case_id} · Decree delivered to DM │ {Brand.FOOTER}"
            if dm_sent
            else f"Case #{case.case_id} · DM could not be delivered │ {Brand.FOOTER}"
        )
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    # ── /ban · !cban ────────────────────────────────────────────

    @commands.hybrid_command(
        name="ban",
        description="Permanently exile a member or user from the realm",
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        target="The member or user ID to exile",
        reason="Reason for the decree",
        delete_days="Days of messages to delete (0 to 7)",
    )
    async def ban(
        self,
        ctx: commands.Context[Celesteria],
        target: discord.Member | discord.User,
        delete_days: int = 0,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Permanently exile a member or user from the guild."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        if delete_days < 0 or delete_days > 7:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Invalid Purge Window",
                    "Message deletion window must be between 0 and 7 days.",
                )
            )
            return

        # Pre-check hierarchy before confirmation prompt
        if isinstance(target, discord.Member):
            can_mod, err = can_moderate(ctx.author, target)
            if not can_mod:
                await ctx.send(embed=CelesteriaEmbed.permission_denied(err))
                return

            bot_can, bot_err = bot_can_moderate(ctx.guild.me, target)
            if not bot_can:
                await ctx.send(embed=CelesteriaEmbed.permission_denied(bot_err))
                return

        has_perms, missing = check_bot_permissions(ctx.guild.me, ban_members=True)
        if not has_perms:
            await ctx.send(
                embed=CelesteriaEmbed.error(
                    "Bot Missing Permissions",
                    f"I need the following permissions: **{', '.join(missing)}**",
                )
            )
            return

        # Confirmation prompt with ConfirmView
        prompt_embed = CelesteriaEmbed.warning(
            "Decree of Permanent Exile",
            (
                f"Are you certain you wish to exile **{target.display_name}** (`{target.id}`)?\n\n"
                f"**Reason:** {reason}\n"
                f"**Message Purge:** {delete_days} days"
            ),
        )
        view = ConfirmView(author_id=ctx.author.id, timeout=30.0)
        msg = await ctx.send(embed=prompt_embed, view=view)
        view.message = msg

        await view.wait()

        if view.value is None:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Decree Expired",
                    "The exile confirmation prompt timed out. No decree was issued.",
                )
            )
            return
        if not view.value:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Decree Cancelled",
                    "The exile decree was cancelled by the moderator.",
                )
            )
            return

        try:
            case, dm_sent = await self.service.execute_ban(
                ctx.guild,
                ctx.author,
                target,
                reason,
                delete_days=delete_days,
            )
        except PermissionError as exc:
            await ctx.send(embed=CelesteriaEmbed.permission_denied(str(exc)))
            return
        except discord.Forbidden:
            await ctx.send(
                embed=CelesteriaEmbed.error(
                    "Action Prohibited",
                    "Discord denied the exile decree. Verify bot role hierarchy.",
                )
            )
            return

        embed = CelesteriaEmbed.moderation(
            f"Decree #{case.case_id} — Permanent Exile",
            f"**{target.display_name}** has been cast into exile for eternity.",
        )
        embed.add_field(name="Target", value=f"{target.mention} (`{target}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        if delete_days > 0:
            embed.add_field(name="Purged Messages", value=f"{delete_days} days", inline=True)

        footer_text = (
            f"Case #{case.case_id} · Decree delivered to DM │ {Brand.FOOTER}"
            if dm_sent
            else f"Case #{case.case_id} · DM could not be delivered │ {Brand.FOOTER}"
        )
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    # ── /timeout · !ctimeout ────────────────────────────────────

    @commands.hybrid_command(
        name="timeout",
        description="Temporarily silence a member in the realm",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        member="The member to silence",
        duration="Duration of silence (e.g., 10m, 2h, 1d, 7d)",
        reason="Reason for the decree",
    )
    async def timeout(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member,
        duration: str,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Temporarily silence a member via Discord timeout."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        try:
            duration_seconds, _ = parse_duration(duration)
        except ValueError as exc:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Invalid Duration",
                    str(exc),
                )
            )
            return

        try:
            case, dm_sent = await self.service.execute_timeout(
                ctx.guild,
                ctx.author,
                member,
                duration_seconds,
                reason,
            )
        except PermissionError as exc:
            await ctx.send(embed=CelesteriaEmbed.permission_denied(str(exc)))
            return
        except discord.Forbidden:
            await ctx.send(
                embed=CelesteriaEmbed.error(
                    "Action Prohibited",
                    "Discord denied the timeout decree. Verify bot role hierarchy.",
                )
            )
            return

        embed = CelesteriaEmbed.moderation(
            f"Decree #{case.case_id} — Member Silenced",
            f"**{member.display_name}** has been silenced in the realm.",
        )
        embed.add_field(name="Target", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
        embed.add_field(
            name="Duration",
            value=f"`{format_duration(duration_seconds)}`",
            inline=True,
        )
        embed.add_field(name="Reason", value=reason, inline=False)

        footer_text = (
            f"Case #{case.case_id} · Decree delivered to DM │ {Brand.FOOTER}"
            if dm_sent
            else f"Case #{case.case_id} · DM could not be delivered │ {Brand.FOOTER}"
        )
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    # ── /clear · !cclear ────────────────────────────────────────

    @commands.hybrid_command(
        name="clear",
        description="Purge scrolls of recent messages from this channel",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages to purge (1 to 100)",
        reason="Reason for the purge decree",
    )
    async def clear(
        self,
        ctx: commands.Context[Celesteria],
        amount: int,
        *,
        reason: str | None = None,
    ) -> None:
        """Purge 1 to 100 messages from the current channel."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)
        assert isinstance(ctx.channel, (discord.TextChannel, discord.Thread))

        if amount < 1 or amount > 100:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Invalid Quantity",
                    "The purge count must be between 1 and 100 scrolls (messages).",
                )
            )
            return

        # For prefix commands, delete the command invocation message if possible
        if ctx.interaction is None and ctx.message:
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            count, case = await self.service.execute_clear(
                ctx.channel,
                ctx.author,
                amount,
                reason,
            )
        except PermissionError as exc:
            await ctx.send(embed=CelesteriaEmbed.permission_denied(str(exc)))
            return
        except discord.Forbidden:
            await ctx.send(
                embed=CelesteriaEmbed.error(
                    "Action Prohibited",
                    "Discord denied message purge. Verify bot permissions.",
                )
            )
            return

        embed = CelesteriaEmbed.success(
            "Purge Decree Executed",
            f"Successfully purged **{count}** messages from {ctx.channel.mention}.",
        )
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=case.reason, inline=True)
        embed.set_footer(text=f"Case #{case.case_id} │ {Brand.FOOTER}")

        if ctx.interaction:
            await ctx.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed, delete_after=5.0)

    # ── /cases · !ccases ────────────────────────────────────────

    @commands.hybrid_command(
        name="cases",
        description="Inspect royal decree history or look up a specific case",
    )
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(
        member="The member whose records to inspect",
        case_id="Or a specific case ID to inspect",
    )
    async def cases(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member | discord.User | None = None,
        case_id: int | None = None,
    ) -> None:
        """Inspect recorded decrees for a member, a case ID, or the realm."""
        assert ctx.guild is not None

        # Lookup by single case ID
        if case_id is not None:
            case = await self.repo.get_case(ctx.guild.id, case_id)
            if not case:
                await ctx.send(
                    embed=CelesteriaEmbed.warning(
                        "Decree Not Found",
                        f"No decree found with ID **#{case_id}** in this realm.",
                    )
                )
                return

            embed = CelesteriaEmbed.moderation(
                f"Decree #{case.case_id} — {case.action.upper()}",
                "Archived decree record from the chronicles.",
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
            embed.add_field(name="Action", value=f"`{case.action.upper()}`", inline=True)
            if case.duration_seconds:
                embed.add_field(
                    name="Duration",
                    value=f"`{format_duration(case.duration_seconds)}`",
                    inline=True,
                )
            if case.extra_data:
                embed.add_field(name="Details", value=case.extra_data, inline=True)
            embed.add_field(name="Reason", value=case.reason, inline=False)
            embed.add_field(name="Recorded At", value=f"`{case.created_at}`", inline=False)
            embed.set_footer(text=f"Case #{case.case_id} │ {Brand.FOOTER}")
            await ctx.send(embed=embed)
            return

        # Lookup by member target
        if member is not None:
            records = await self.repo.get_cases_for_target(ctx.guild.id, member.id, limit=10)
            total = await self.repo.count_cases_for_target(ctx.guild.id, member.id)

            if total == 0:
                await ctx.send(
                    embed=CelesteriaEmbed.info(
                        "Spotless Record",
                        f"**{member.display_name}** has no recorded decrees in this realm.",
                    )
                )
                return

            lines: list[str] = []
            for c in records:
                dur_text = f" ({format_duration(c.duration_seconds)})" if c.duration_seconds else ""
                lines.append(
                    f"**Case #{c.case_id}** · `{c.action.upper()}`{dur_text}\n"
                    f"└ *{c.reason}* — <@{c.moderator_id}> (`{c.created_at[:10]}`)"
                )

            embed = CelesteriaEmbed.moderation(
                f"Decrees for {member.display_name} [{total}]",
                "\n\n".join(lines),
            )
            embed.set_footer(
                text=f"Showing latest {len(records)} of {total} decrees │ {Brand.FOOTER}"
            )
            await ctx.send(embed=embed)
            return

        # Overview of recent decrees in guild
        records = await self.repo.get_recent_cases(ctx.guild.id, limit=10)
        total = await self.repo.count_total_cases(ctx.guild.id)

        if total == 0:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Chronicles Empty",
                    "No decrees have been recorded in this realm yet.",
                )
            )
            return

        lines = []
        for c in records:
            dur_text = f" ({format_duration(c.duration_seconds)})" if c.duration_seconds else ""
            lines.append(
                f"**Case #{c.case_id}** · `{c.action.upper()}`{dur_text} against <@{c.target_id}>\n"
                f"└ *{c.reason}* — <@{c.moderator_id}>"
            )

        embed = CelesteriaEmbed.moderation(
            f"Realm Decree Chronicles [{total}]",
            "\n\n".join(lines),
        )
        embed.set_footer(
            text=f"Showing latest {len(records)} of {total} decrees │ {Brand.FOOTER}"
        )
        await ctx.send(embed=embed)

    # ── /setmodlog · !csetmodlog ────────────────────────────────

    @commands.hybrid_command(
        name="setmodlog",
        description="Configure the channel where royal decrees are logged",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="The channel for moderation records (leave empty to disable)",
    )
    async def setmodlog(
        self,
        ctx: commands.Context[Celesteria],
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Bind or unbind the moderation logging channel for this guild."""
        assert ctx.guild is not None

        if channel is None:
            await self.repo.set_mod_log_channel_id(ctx.guild.id, None)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Decree Log Unbound",
                    "Moderation decrees will no longer be logged to an archive channel.",
                )
            )
            return

        # Check bot permissions in target channel
        perms = channel.permissions_for(ctx.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Insufficient Permissions in Channel",
                    f"I need **Send Messages** and **Embed Links** permissions in {channel.mention}.",
                )
            )
            return

        await self.repo.set_mod_log_channel_id(ctx.guild.id, channel.id)
        await ctx.send(
            embed=CelesteriaEmbed.success(
                "Decree Log Configured",
                f"Royal decrees will henceforth be recorded in {channel.mention}.",
            )
        )


async def setup(bot: Celesteria) -> None:
    """Load the Moderation cog."""
    await bot.add_cog(ModerationCog(bot))

