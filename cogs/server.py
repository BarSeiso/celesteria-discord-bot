"""Celesteria Server Cog.

Provides hybrid commands and event listeners for:
- Welcome announcements (/setwelcome, /testwelcome)
- Dynamic member counter (/setcounter)
- Server activity chronicles (/setserverlog)
- Configuration inspection (/serverconfig)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from db.server_repository import DEFAULT_COUNTER_TEMPLATE, DEFAULT_WELCOME_MESSAGE
from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.cogs.server")


class ServerCog(commands.Cog, name="Server"):
    """Server administration, chronicles & welcome."""

    emoji = "🏰"
    help_description = "Server administration & chronicles"

    def __init__(self, bot: Celesteria) -> None:
        self.bot = bot
        self.service = bot.server_service
        self.repo = bot.server_repo

    # ── /setwelcome · !csetwelcome ──────────────────────────────

    @commands.hybrid_command(
        name="setwelcome",
        description="Configure the royal welcome announcements channel and greeting",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="The channel for welcome announcements (leave empty to disable)",
        message="Custom greeting template (placeholders: {mention}, {user}, {server}, {member_count})",
    )
    async def setwelcome(
        self,
        ctx: commands.Context[Celesteria],
        channel: discord.TextChannel | None = None,
        *,
        message: str | None = None,
    ) -> None:
        """Configure or disable royal welcome greetings for new arrivals."""
        assert ctx.guild is not None

        if channel is None:
            await self.repo.set_welcome_config(ctx.guild.id, None)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Welcome Announcements Disabled",
                    "New arrivals will no longer receive a formal reception announcement.",
                )
            )
            return

        perms = channel.permissions_for(ctx.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Insufficient Permissions in Channel",
                    f"I require **Send Messages** and **Embed Links** permissions in {channel.mention}.",
                )
            )
            return

        await self.repo.set_welcome_config(ctx.guild.id, channel.id, message)

        embed = CelesteriaEmbed.success(
            "Welcome Channel Configured",
            f"New arrivals will henceforth be welcomed in {channel.mention}.",
        )
        msg_preview = message if message else f"*{DEFAULT_WELCOME_MESSAGE} (default)*"
        embed.add_field(name="Greeting Message", value=msg_preview, inline=False)
        embed.add_field(
            name="Available Placeholders",
            value="`{mention}` · `{user}` · `{server}` · `{member_count}`",
            inline=False,
        )
        embed.set_footer(text=f"Tip: Use /testwelcome to preview the card │ {Brand.FOOTER}")
        await ctx.send(embed=embed)

    # ── /testwelcome · !ctestwelcome ────────────────────────────

    @commands.hybrid_command(
        name="testwelcome",
        description="Preview the royal welcome announcement card",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def testwelcome(self, ctx: commands.Context[Celesteria]) -> None:
        """Preview how new member reception embeds appear with current settings."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        config = await self.repo.get_server_config(ctx.guild.id)
        custom_msg = config.welcome_message if config else None
        preview_embed = self.service.build_welcome_embed(ctx.author, custom_msg)

        await ctx.send(
            content="-# *⚜ Welcome Card Preview (only visible to command invoker):*",
            embed=preview_embed,
        )

    # ── /setcounter · !csetcounter ──────────────────────────────

    @commands.hybrid_command(
        name="setcounter",
        description="Configure dynamic member counter channel and display format",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel to display member count (leave empty to disable)",
        template="Format template, e.g. 🏰 Members: {count} ({count}, {humans}, {bots})",
    )
    async def setcounter(
        self,
        ctx: commands.Context[Celesteria],
        channel: discord.abc.GuildChannel | None = None,
        *,
        template: str | None = None,
    ) -> None:
        """Bind a channel as a live member counter."""
        assert ctx.guild is not None

        if channel is None:
            await self.repo.set_counter_config(ctx.guild.id, None)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Member Counter Disabled",
                    "The member counter channel has been unbound and deactivated.",
                )
            )
            return

        perms = channel.permissions_for(ctx.guild.me)
        if not perms.manage_channels:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Insufficient Permissions on Channel",
                    f"I require the **Manage Channels** permission on {channel.mention} to rename it.",
                )
            )
            return

        resolved_template = template if template else DEFAULT_COUNTER_TEMPLATE
        await self.repo.set_counter_config(ctx.guild.id, channel.id, resolved_template)

        # Attempt immediate synchronization
        synced = await self.service.sync_guild_counter(ctx.guild.id, force=True)

        embed = CelesteriaEmbed.success(
            "Member Counter Configured",
            f"The counter has been bound to **{channel.name}** (`{channel.id}`).",
        )
        embed.add_field(name="Template", value=f"`{resolved_template}`", inline=True)
        embed.add_field(
            name="Initial Sync",
            value="`Synchronized instantly`" if synced else "`Queued for sync`",
            inline=True,
        )
        embed.add_field(
            name="Available Metrics",
            value="`{count}` (total) · `{humans}` · `{bots}`",
            inline=False,
        )
        embed.set_footer(
            text="Channel renames are rate-limited by Discord to at most 2 per 10 minutes │ " + Brand.FOOTER
        )
        await ctx.send(embed=embed)

    # ── /setserverlog · !csetserverlog ──────────────────────────

    @commands.hybrid_command(
        name="setserverlog",
        description="Configure the channel where server activity chronicles are recorded",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="The channel for server activity chronicles (leave empty to disable)",
    )
    async def setserverlog(
        self,
        ctx: commands.Context[Celesteria],
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Bind or unbind the server activity audit chronicles channel."""
        assert ctx.guild is not None

        if channel is None:
            await self.repo.set_server_log_channel_id(ctx.guild.id, None)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Server Log Unbound",
                    "Server activities and member events will no longer be logged to an archive channel.",
                )
            )
            return

        perms = channel.permissions_for(ctx.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Insufficient Permissions in Channel",
                    f"I require **Send Messages** and **Embed Links** permissions in {channel.mention}.",
                )
            )
            return

        await self.repo.set_server_log_channel_id(ctx.guild.id, channel.id)
        await ctx.send(
            embed=CelesteriaEmbed.success(
                "Server Log Configured",
                f"Server events and activity chronicles will henceforth be recorded in {channel.mention}.",
            )
        )

    # ── /serverconfig · !cserverconfig ──────────────────────────

    @commands.hybrid_command(
        name="serverconfig",
        description="Display current server configuration for logs, welcome, and counter",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def serverconfig(self, ctx: commands.Context[Celesteria]) -> None:
        """View the realm's active channel bindings and configurations."""
        assert ctx.guild is not None

        config = await self.repo.get_server_config(ctx.guild.id)
        mod_log_id = await self.bot.moderation_repo.get_mod_log_channel_id(ctx.guild.id)

        embed = CelesteriaEmbed.standard(
            f"{ctx.guild.name} — Realm Configuration",
            "Overview of active administration channels and system integrations.",
        )

        # Welcome
        if config and config.welcome_channel_id:
            w_chan = ctx.guild.get_channel(config.welcome_channel_id)
            w_val = f"{w_chan.mention if w_chan else f'`ID: {config.welcome_channel_id}`'}"
            if config.welcome_message:
                w_val += f"\n└ *Template: {config.welcome_message[:60]}...*"
        else:
            w_val = "*Disabled / Unconfigured*"
        embed.add_field(name=f"{Icon.BRAND} Welcome Channel", value=w_val, inline=False)

        # Member Counter
        if config and config.counter_channel_id:
            c_chan = ctx.guild.get_channel(config.counter_channel_id)
            c_val = (
                f"{c_chan.mention if c_chan else f'`ID: {config.counter_channel_id}`'}\n"
                f"└ *Format: `{config.counter_template}`*"
            )
        else:
            c_val = "*Disabled / Unconfigured*"
        embed.add_field(name=f"{Icon.CASTLE} Member Counter", value=c_val, inline=False)

        # Server Chronicles Log
        if config and config.server_log_channel_id:
            s_chan = ctx.guild.get_channel(config.server_log_channel_id)
            s_val = f"{s_chan.mention if s_chan else f'`ID: {config.server_log_channel_id}`'}"
        else:
            s_val = "*Disabled / Unconfigured*"
        embed.add_field(name=f"{Icon.SCROLL} Server Activity Log", value=s_val, inline=False)

        # Moderation Decree Log
        if mod_log_id:
            m_chan = ctx.guild.get_channel(mod_log_id)
            m_val = f"{m_chan.mention if m_chan else f'`ID: {mod_log_id}`'}"
        else:
            m_val = "*Disabled / Unconfigured*"
        embed.add_field(name=f"{Icon.MODERATION} Moderation Decree Log", value=m_val, inline=False)

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_footer(text=f"Guild ID: {ctx.guild.id} │ {Brand.FOOTER}")

        await ctx.send(embed=embed)

    # ── Gateway Event Listeners ─────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle member arrival: welcome announcement, join log, and counter refresh."""
        await self.service.dispatch_welcome(member)
        await self.service.log_member_join(member)
        self.service.mark_counter_dirty(member.guild.id)
        await self.service.sync_guild_counter(member.guild.id, force=False)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle member departure: leave log and counter refresh."""
        await self.service.log_member_leave(member)
        self.service.mark_counter_dirty(member.guild.id)
        await self.service.sync_guild_counter(member.guild.id, force=False)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Handle message deletion log."""
        await self.service.log_message_delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Handle message modification log."""
        await self.service.log_message_edit(before, after)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Handle role creation log."""
        await self.service.log_role_create(role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Handle role deletion log."""
        await self.service.log_role_delete(role)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Handle role modification log."""
        await self.service.log_role_update(before, after)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel creation log."""
        await self.service.log_channel_create(channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel deletion log."""
        await self.service.log_channel_delete(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        """Handle channel modification log."""
        await self.service.log_channel_update(before, after)


async def setup(bot: Celesteria) -> None:
    """Load the Server cog."""
    await bot.add_cog(ServerCog(bot))

