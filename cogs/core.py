"""Core commands for Celesteria.

Provides essential commands: ping, help, userinfo.
Also includes the owner-only sync command for development.
"""

from __future__ import annotations

import platform
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ui.embeds import CelesteriaEmbed
from ui.formatters import format_number, format_relative, format_timestamp, format_uptime
from ui.theme import Brand, Icon, Palette
from ui.views import HelpView, build_help_embed

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.cogs.core")


class CoreCog(commands.Cog, name="Core"):
    """Essential commands for the realm."""

    emoji = "✦"
    help_description = "Essential commands"

    def __init__(self, bot: Celesteria) -> None:
        self.bot = bot

    # ── /ping ───────────────────────────────────────────────────

    @commands.hybrid_command(
        name="ping",
        description="Check bot latency and status",
    )
    async def ping(self, ctx: commands.Context[Celesteria]) -> None:
        """Display bot latency, uptime, and version information."""
        latency_ms = round(self.bot.latency * 1000)
        uptime = format_uptime(self.bot.uptime_seconds)
        guild_count = len(self.bot.guilds)
        member_count = sum(g.member_count or 0 for g in self.bot.guilds)

        embed = CelesteriaEmbed.standard(
            "Celesteria Status",
            f"*{Brand.TAGLINE}*",
        )
        embed.add_field(
            name="Latency",
            value=f"`{latency_ms}ms`",
            inline=True,
        )
        embed.add_field(
            name="Uptime",
            value=f"`{uptime}`",
            inline=True,
        )
        embed.add_field(
            name="Version",
            value=f"`{self.bot.config.version}`",
            inline=True,
        )
        embed.add_field(
            name="Guilds",
            value=f"`{guild_count}`",
            inline=True,
        )
        embed.add_field(
            name="Members",
            value=f"`{format_number(member_count)}`",
            inline=True,
        )
        embed.add_field(
            name="Python",
            value=f"`{platform.python_version()}`",
            inline=True,
        )

        await ctx.send(embed=embed)

    # ── /help ───────────────────────────────────────────────────

    @commands.hybrid_command(
        name="help",
        description="Browse available commands",
    )
    async def help_command(self, ctx: commands.Context[Celesteria]) -> None:
        """Open the interactive command codex."""
        embed = build_help_embed(self.bot)
        view = HelpView(self.bot, author_id=ctx.author.id)

        message = await ctx.send(embed=embed, view=view)
        view.message = message

    # ── /userinfo ───────────────────────────────────────────────

    @commands.hybrid_command(
        name="userinfo",
        description="View information about a member",
    )
    @commands.guild_only()
    @discord.app_commands.describe(member="The member to inspect (defaults to you)")
    async def userinfo(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member | None = None,
    ) -> None:
        """Display detailed information about a server member."""
        target = member or ctx.author

        # Ensure we have a Member object (not just User)
        if not isinstance(target, discord.Member):
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Invalid Target",
                    "Could not find that member in this server.",
                )
            )
            return

        embed = self._build_userinfo_embed(target)
        await ctx.send(embed=embed)

    @staticmethod
    def _build_userinfo_embed(member: discord.Member) -> discord.Embed:
        """Construct the userinfo embed for a member."""
        # Header
        embed = CelesteriaEmbed._base(
            member.colour if member.colour != discord.Colour.default() else Palette.SECONDARY,
            title=f"{Icon.BRAND} {member.display_name}",
            description=f"{member.mention} · `{member}`",
        )

        # Avatar
        embed.set_thumbnail(url=member.display_avatar.url)

        # Account dates
        embed.add_field(
            name="Account Created",
            value=f"{format_timestamp(member.created_at, 'D')}\n{format_relative(member.created_at)}",
            inline=True,
        )
        embed.add_field(
            name="Joined Server",
            value=(
                f"{format_timestamp(member.joined_at, 'D')}\n{format_relative(member.joined_at)}"
                if member.joined_at
                else "Unknown"
            ),
            inline=True,
        )

        # Roles (excluding @everyone)
        roles = [r.mention for r in reversed(member.roles) if r != member.guild.default_role]
        if roles:
            # Show up to 15 roles, then indicate how many more
            displayed = roles[:15]
            role_text = " ".join(displayed)
            if len(roles) > 15:
                role_text += f" *+{len(roles) - 15} more*"
            embed.add_field(
                name=f"Roles [{len(roles)}]",
                value=role_text,
                inline=False,
            )
        else:
            embed.add_field(name="Roles", value="*No roles*", inline=False)

        # Badges / Status
        badges: list[str] = []
        if member.id == member.guild.owner_id:
            badges.append(f"{Icon.CROWN} Server Owner")
        if member.premium_since:
            badges.append(
                f"{Icon.ACCENT} Booster since "
                f"{format_timestamp(member.premium_since, 'D')}"
            )
        if member.bot:
            badges.append(f"{Icon.SHIELD} Bot")

        if badges:
            embed.add_field(
                name="Status",
                value="\n".join(badges),
                inline=False,
            )

        # User ID in footer
        embed.set_footer(text=f"ID: {member.id} │ {Brand.FOOTER}")

        return embed

    # ── !csync (owner-only, development) ────────────────────────

    @commands.command(name="sync", hidden=True)
    @commands.check_any(commands.is_owner(), commands.has_permissions(administrator=True))
    async def sync_command(self, ctx: commands.Context[Celesteria]) -> None:
        """Manually sync slash commands (owner or administrator).

        Usage:
            !csync          — sync immediately to current server (instant)
            !csync global   — force global sync (up to 1 hour propagation)
            !csync clear    — clear guild commands and fall back to global
        """
        arg = ctx.message.content.split(maxsplit=1)
        mode = arg[1].strip().lower() if len(arg) > 1 else ""

        if mode == "global":
            synced = await self.bot.tree.sync()
            await ctx.send(
                embed=CelesteriaEmbed.success(
                    "Commands Synced Globally",
                    f"Synced **{len(synced)}** commands globally.\n"
                    "Changes may take up to 1 hour to propagate to all servers.",
                )
            )

        elif mode == "clear":
            target_guild = ctx.guild or (
                discord.Object(id=self.bot.config.test_guild_id)
                if self.bot.config.test_guild_id
                else None
            )
            if target_guild:
                self.bot.tree.clear_commands(guild=target_guild)
                await self.bot.tree.sync(guild=target_guild)
            synced = await self.bot.tree.sync()
            await ctx.send(
                embed=CelesteriaEmbed.success(
                    "Commands Cleared",
                    "Cleared server-specific commands.\n"
                    f"Synced **{len(synced)}** commands globally.",
                )
            )

        elif ctx.guild:
            self.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await self.bot.tree.sync(guild=ctx.guild)
            await ctx.send(
                embed=CelesteriaEmbed.success(
                    "Commands Synced Instantly",
                    f"Synced **{len(synced)}** slash commands directly to **{ctx.guild.name}**!\n\n"
                    "All commands (`/warn`, `/kick`, `/ban`, `/timeout`, `/clear`, etc.) are now immediately active.\n"
                    "-# *Tip: If not visible immediately, press `Ctrl+R` in Discord to refresh.*",
                )
            )

        elif self.bot.config.test_guild_id:
            guild = discord.Object(id=self.bot.config.test_guild_id)
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            await ctx.send(
                embed=CelesteriaEmbed.success(
                    "Commands Synced",
                    f"Synced **{len(synced)}** commands to test guild.",
                )
            )

        else:
            synced = await self.bot.tree.sync()
            await ctx.send(
                embed=CelesteriaEmbed.success(
                    "Commands Synced",
                    f"Synced **{len(synced)}** commands globally.\n"
                    "Changes may take up to 1 hour to propagate.",
                )
            )


async def setup(bot: Celesteria) -> None:
    """Load the Core cog."""
    await bot.add_cog(CoreCog(bot))

