"""Celesteria Server domain service.

Coordinates welcome announcements, dynamic member counter synchronization,
and server activity audit logs.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

from db.server_repository import (
    DEFAULT_COUNTER_TEMPLATE,
    DEFAULT_WELCOME_MESSAGE,
    ServerConfig,
    ServerRepository,
)
from ui.embeds import CelesteriaEmbed
from ui.formatters import format_number, format_relative, format_timestamp
from ui.theme import Brand, Icon, Palette

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.services.server")


class ServerService:
    """Domain service managing welcome cards, counter channels, and server activity logs."""

    # Discord imposes a rate limit of 2 channel renames per 10 minutes per channel.
    MIN_RENAME_INTERVAL: float = 600.0

    def __init__(self, bot: Celesteria, repo: ServerRepository) -> None:
        self.bot = bot
        self.repo = repo
        self._dirty_counters: set[int] = set()
        self._last_rename_time: dict[int, float] = {}

    def start(self) -> None:
        """Start background loops."""
        if not self._counter_sync_loop.is_running():
            self._counter_sync_loop.start()

    def close(self) -> None:
        """Stop background loops gracefully."""
        if self._counter_sync_loop.is_running():
            self._counter_sync_loop.cancel()

    # ── Welcome System ──────────────────────────────────────────

    def build_welcome_embed(
        self,
        member: discord.Member,
        custom_template: str | None = None,
    ) -> discord.Embed:
        """Generate a themed Celesteria welcome announcement embed."""
        guild = member.guild
        member_count_str = format_number(guild.member_count or len(guild.members))

        if member.bot:
            embed = CelesteriaEmbed.welcome(
                title="Arcane Construct Registered",
                description=(
                    f"An automated sentinel, {member.mention}, "
                    f"has been integrated into **{guild.name}**."
                ),
                colour=Palette.INFO,
                icon=Icon.SHIELD,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(
                name="Account Created",
                value=(
                    f"{format_timestamp(member.created_at, 'D')}\n"
                    f"{format_relative(member.created_at)}"
                ),
                inline=True,
            )
            embed.add_field(
                name="Sentinel ID",
                value=f"`{member.id}`",
                inline=True,
            )
            embed.set_footer(text=f"Realm Sentinel │ {Brand.FOOTER}")
            return embed

        template = custom_template.strip() if custom_template and custom_template.strip() else DEFAULT_WELCOME_MESSAGE
        greeting = template.format(
            mention=member.mention,
            user=member.name,
            username=member.name,
            server=guild.name,
            member_count=member_count_str,
        )

        embed = CelesteriaEmbed.welcome(
            title="A New Member Has Entered the Realm",
            description=greeting,
            colour=Palette.PRIMARY,
            icon=Icon.BRAND,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Account Created",
            value=(
                f"{format_timestamp(member.created_at, 'D')}\n"
                f"{format_relative(member.created_at)}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Realm Member",
            value=f"`#{member_count_str}`",
            inline=True,
        )
        embed.set_footer(text=f"Welcome to {guild.name} │ {Brand.FOOTER}")
        return embed

    async def dispatch_welcome(self, member: discord.Member) -> bool:
        """Deliver the welcome announcement to the configured channel.

        Returns True if delivered, False if unconfigured or permissions missing.
        """
        config = await self.repo.get_server_config(member.guild.id)
        if not config or not config.welcome_channel_id:
            return False

        channel = member.guild.get_channel(config.welcome_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        perms = channel.permissions_for(member.guild.me)
        if not perms.send_messages or not perms.embed_links:
            log.warning(
                "Cannot dispatch welcome in channel %d (guild %d): missing permissions",
                channel.id,
                member.guild.id,
            )
            return False

        embed = self.build_welcome_embed(member, config.welcome_message)
        try:
            await channel.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Failed to send welcome embed to channel %d in guild %d",
                channel.id,
                member.guild.id,
            )
            return False

    # ── Member Counter System ───────────────────────────────────

    @staticmethod
    def format_counter_name(guild: discord.Guild, template: str) -> str:
        """Render the counter channel name using member metrics."""
        total = guild.member_count or len(guild.members)
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)

        # Fallback if member cache has not completed populating
        if humans + bots == 0 and total > 0:
            humans = total

        rendered = template.format(
            count=format_number(total),
            total=format_number(total),
            humans=format_number(humans),
            bots=format_number(bots),
        )
        return rendered[:100]

    def mark_counter_dirty(self, guild_id: int) -> None:
        """Mark a guild's counter channel as needing synchronization."""
        self._dirty_counters.add(guild_id)

    async def sync_guild_counter(self, guild_id: int, force: bool = False) -> bool:
        """Synchronize a guild's counter channel name with rate-limit protection."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False

        config = await self.repo.get_server_config(guild_id)
        if not config or not config.counter_channel_id:
            self._dirty_counters.discard(guild_id)
            return False

        channel = guild.get_channel(config.counter_channel_id)
        if channel is None:
            return False

        perms = channel.permissions_for(guild.me)
        if not perms.manage_channels:
            log.warning(
                "Cannot rename counter channel %d in guild %d: missing Manage Channels",
                channel.id,
                guild_id,
            )
            return False

        target_name = self.format_counter_name(guild, config.counter_template)
        if channel.name == target_name:
            self._dirty_counters.discard(guild_id)
            return True

        now = time.monotonic()
        last = self._last_rename_time.get(guild_id, 0.0)
        if not force and (now - last) < self.MIN_RENAME_INTERVAL:
            # Keep dirty for the background sync loop once cooldown elapses
            return False

        try:
            await channel.edit(name=target_name, reason="Celesteria member counter sync")
            self._last_rename_time[guild_id] = now
            self._dirty_counters.discard(guild_id)
            log.info("Synchronized counter for guild %d to '%s'", guild_id, target_name)
            return True
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning(
                "Failed to rename counter channel %d in guild %d: %s",
                channel.id,
                guild_id,
                exc,
            )
            return False

    async def sync_all_counters(self, force: bool = False) -> None:
        """Synchronize all configured guild counters across the bot."""
        configs = await self.repo.get_all_counter_configs()
        for cfg in configs:
            await self.sync_guild_counter(cfg.guild_id, force=force)

    @tasks.loop(minutes=10)
    async def _counter_sync_loop(self) -> None:
        """Background maintenance loop to flush pending dirty counters."""
        pending = list(self._dirty_counters)
        for guild_id in pending:
            await self.sync_guild_counter(guild_id)

    @_counter_sync_loop.before_loop
    async def _before_counter_loop(self) -> None:
        """Wait until the bot is completely connected before running loop."""
        await self.bot.wait_until_ready()

    # ── Server Logging System ───────────────────────────────────

    async def dispatch_server_log(self, guild: discord.Guild, embed: discord.Embed) -> bool:
        """Send a server activity embed to the guild's configured server log channel."""
        config = await self.repo.get_server_config(guild.id)
        if not config or not config.server_log_channel_id:
            return False

        channel = guild.get_channel(config.server_log_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        perms = channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.embed_links:
            log.warning(
                "Cannot write to server log channel %d in guild %d: missing permissions",
                channel.id,
                guild.id,
            )
            return False

        try:
            await channel.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning(
                "Failed to write server log to channel %d in guild %d: %s",
                channel.id,
                guild.id,
                exc,
            )
            return False

    async def log_member_join(self, member: discord.Member) -> None:
        """Log a member arrival event in the server chronicles."""
        guild = member.guild
        embed = CelesteriaEmbed.server_log(
            title="Member Joined Realm",
            description=f"{member.mention} has arrived in the server.",
            colour=Palette.SUCCESS,
            icon=Icon.ACCENT,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Member",
            value=f"`{member}` (`{member.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Account Created",
            value=f"{format_timestamp(member.created_at, 'D')}\n{format_relative(member.created_at)}",
            inline=True,
        )
        embed.add_field(
            name="Type",
            value="`Bot Sentinel`" if member.bot else "`Human Citizen`",
            inline=True,
        )
        embed.add_field(
            name="Total Realm Count",
            value=f"`{format_number(guild.member_count or len(guild.members))}`",
            inline=True,
        )
        await self.dispatch_server_log(guild, embed)

    async def log_member_leave(self, member: discord.Member) -> None:
        """Log a member departure event in the server chronicles."""
        guild = member.guild
        embed = CelesteriaEmbed.server_log(
            title="Member Departed Realm",
            description=f"**{member}** has left the realm.",
            colour=Palette.NEUTRAL,
            icon=Icon.SCROLL,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Member",
            value=f"`{member}` (`{member.id}`)",
            inline=True,
        )
        joined_str = (
            f"{format_timestamp(member.joined_at, 'D')}\n{format_relative(member.joined_at)}"
            if member.joined_at
            else "*Unknown*"
        )
        embed.add_field(
            name="Joined Realm",
            value=joined_str,
            inline=True,
        )

        non_default_roles = [r.name for r in member.roles if r != guild.default_role]
        roles_text = ", ".join(f"`{r}`" for r in non_default_roles[:10]) if non_default_roles else "*None*"
        if len(non_default_roles) > 10:
            roles_text += f" *+{len(non_default_roles) - 10} more*"
        embed.add_field(name="Roles Held", value=roles_text, inline=False)

        embed.add_field(
            name="Remaining Members",
            value=f"`{format_number(guild.member_count or len(guild.members))}`",
            inline=True,
        )
        await self.dispatch_server_log(guild, embed)

    async def log_message_delete(self, message: discord.Message) -> None:
        """Log a deleted message."""
        if not message.guild or message.author.bot:
            return

        embed = CelesteriaEmbed.server_log(
            title="Message Expunged",
            description=f"A message from {message.author.mention} was deleted in {message.channel.mention}.",
            colour=Palette.ERROR,
            icon=Icon.WARNING,
        )
        embed.add_field(
            name="Author",
            value=f"{message.author.mention} (`{message.author}` · `{message.author.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Channel",
            value=message.channel.mention,
            inline=True,
        )

        content = message.clean_content if message.clean_content else message.content
        if content:
            display_content = content[:1000] + ("..." if len(content) > 1000 else "")
            embed.add_field(name="Content", value=display_content, inline=False)
        else:
            embed.add_field(name="Content", value="*[No text content]*", inline=False)

        if message.attachments:
            att_names = ", ".join(f"`{a.filename}`" for a in message.attachments[:5])
            if len(message.attachments) > 5:
                att_names += f" *+{len(message.attachments) - 5} more*"
            embed.add_field(
                name=f"Attachments [{len(message.attachments)}]",
                value=att_names,
                inline=False,
            )

        embed.set_footer(text=f"Message ID: {message.id} │ {Brand.FOOTER}")
        await self.dispatch_server_log(message.guild, embed)

    async def log_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Log a message modification."""
        if not before.guild or before.author.bot:
            return

        if before.content == after.content:
            return

        embed = CelesteriaEmbed.server_log(
            title="Message Modified",
            description=(
                f"A message by {before.author.mention} was edited in {before.channel.mention}.\n"
                f"└ [Jump to Message]({after.jump_url})"
            ),
            colour=Palette.INFO,
            icon=Icon.SCROLL,
        )
        embed.add_field(
            name="Author",
            value=f"{before.author.mention} (`{before.author}` · `{before.author.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Channel",
            value=before.channel.mention,
            inline=True,
        )

        before_text = before.clean_content or before.content or "*[Empty]*"
        after_text = after.clean_content or after.content or "*[Empty]*"

        b_disp = before_text[:1000] + ("..." if len(before_text) > 1000 else "")
        a_disp = after_text[:1000] + ("..." if len(after_text) > 1000 else "")

        embed.add_field(name="Before", value=b_disp, inline=False)
        embed.add_field(name="After", value=a_disp, inline=False)
        embed.set_footer(text=f"Message ID: {after.id} │ {Brand.FOOTER}")

        await self.dispatch_server_log(before.guild, embed)

    async def log_role_create(self, role: discord.Role) -> None:
        """Log a role creation."""
        embed = CelesteriaEmbed.server_log(
            title="Role Created",
            description=f"Role {role.mention} (`{role.name}`) has been created.",
            colour=Palette.INFO,
            icon=Icon.SHIELD,
        )
        embed.add_field(name="Role ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color", value=f"`{str(role.colour)}`", inline=True)
        await self.dispatch_server_log(role.guild, embed)

    async def log_role_delete(self, role: discord.Role) -> None:
        """Log a role deletion."""
        embed = CelesteriaEmbed.server_log(
            title="Role Deleted",
            description=f"Role **@{role.name}** (`{role.id}`) has been deleted.",
            colour=Palette.WARNING,
            icon=Icon.SHIELD,
        )
        await self.dispatch_server_log(role.guild, embed)

    async def log_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Log a role modification."""
        changes: list[str] = []
        if before.name != after.name:
            changes.append(f"• **Name**: `{before.name}` → `{after.name}`")
        if before.colour != after.colour:
            changes.append(f"• **Color**: `{str(before.colour)}` → `{str(after.colour)}`")
        if before.permissions != after.permissions:
            changes.append("• **Permissions**: Guild permissions modified")

        if not changes:
            return

        embed = CelesteriaEmbed.server_log(
            title="Role Updated",
            description=f"Role {after.mention} (`{after.id}`) was modified:\n" + "\n".join(changes),
            colour=Palette.INFO,
            icon=Icon.SHIELD,
        )
        await self.dispatch_server_log(after.guild, embed)

    async def log_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Log a channel creation."""
        embed = CelesteriaEmbed.server_log(
            title="Channel Created",
            description=f"Channel {channel.mention} (`{channel.name}`) was created.",
            colour=Palette.INFO,
            icon=Icon.CASTLE,
        )
        embed.add_field(name="Channel ID", value=f"`{channel.id}`", inline=True)
        embed.add_field(name="Type", value=f"`{str(channel.type)}`", inline=True)
        await self.dispatch_server_log(channel.guild, embed)

    async def log_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Log a channel deletion."""
        embed = CelesteriaEmbed.server_log(
            title="Channel Deleted",
            description=f"Channel **#{channel.name}** (`{channel.id}`) was deleted.",
            colour=Palette.WARNING,
            icon=Icon.CASTLE,
        )
        embed.add_field(name="Type", value=f"`{str(channel.type)}`", inline=True)
        await self.dispatch_server_log(channel.guild, embed)

    async def log_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        """Log a channel update."""
        changes: list[str] = []
        if before.name != after.name:
            changes.append(f"• **Name**: `#{before.name}` → `#{after.name}`")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("• **Topic**: Channel topic was updated")

        if not changes:
            return

        embed = CelesteriaEmbed.server_log(
            title="Channel Updated",
            description=f"Channel {after.mention} (`{after.id}`) was modified:\n" + "\n".join(changes),
            colour=Palette.INFO,
            icon=Icon.CASTLE,
        )
        await self.dispatch_server_log(after.guild, embed)

