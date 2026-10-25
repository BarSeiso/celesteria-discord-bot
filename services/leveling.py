"""Celesteria Leveling and Social domain service.

Coordinates message XP evaluation, anti-spam heuristics, level and progression math,
role reward assignment, and embed generation for profile, level, and leaderboard.
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

from db.level_repository import LevelRepository, LevelReward, MemberLevel
from ui.embeds import CelesteriaEmbed
from ui.formatters import (
    format_number,
    format_progress_bar,
    format_relative,
    format_timestamp,
)
from ui.theme import Brand, Icon, Palette

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.services.leveling")


# ── Progression Math ────────────────────────────────────────────


def xp_required_for_level(level: int) -> int:
    """Calculate cumulative XP required from Level 0 to reach Level N.

    Formula: XP = 100 * N^2
    """
    if level <= 0:
        return 0
    return 100 * (level**2)


def level_from_xp(xp: int) -> int:
    """Calculate member level from cumulative total XP.

    Inverse formula: Level = isqrt(xp // 100)
    """
    if xp < 100:
        return 0
    return math.isqrt(xp // 100)


def get_level_tier_info(xp: int) -> tuple[int, int, int, float]:
    """Calculate level metrics for a given XP quantity.

    Returns:
        (level, base_xp, target_xp, progress_percentage)
    """
    level = level_from_xp(xp)
    base_xp = xp_required_for_level(level)
    target_xp = xp_required_for_level(level + 1)
    tier_range = target_xp - base_xp

    current_tier_xp = max(0, xp - base_xp)
    progress_pct = (current_tier_xp / tier_range * 100.0) if tier_range > 0 else 0.0
    return level, base_xp, target_xp, progress_pct


def get_level_title(level: int) -> str:
    """Return an immersive royal fantasy title for a given level."""
    tiers: list[tuple[int, str]] = [
        (0, "Wanderer"),
        (5, "Page"),
        (10, "Squire"),
        (20, "Knight"),
        (35, "Knight Captain"),
        (50, "Royal Paladin"),
        (75, "High Champion"),
        (100, "Grand Sovereign"),
        (150, "Realm Paragon"),
    ]

    base_title = "Wanderer"
    base_level = 0
    for min_lvl, title in tiers:
        if level >= min_lvl:
            base_title = title
            base_level = min_lvl
        else:
            break

    sub_rank = (level - base_level) % 10 + 1
    roman_numerals = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    roman_sub = roman_numerals[min(sub_rank - 1, 9)]
    return f"{base_title} {roman_sub}"


# ── Domain Service ──────────────────────────────────────────────


class LevelingService:
    """Domain service managing member progression, role rewards, and social UI."""

    COOLDOWN_SECONDS: float = 60.0
    XP_MIN: int = 15
    XP_MAX: int = 25

    def __init__(self, bot: Celesteria, repo: LevelRepository) -> None:
        self.bot = bot
        self.repo = repo
        self._cooldowns: dict[tuple[int, int], float] = {}

    def start(self) -> None:
        """Start background maintenance tasks."""
        if not self._cooldown_pruning_loop.is_running():
            self._cooldown_pruning_loop.start()

    def close(self) -> None:
        """Gracefully stop background loops."""
        if self._cooldown_pruning_loop.is_running():
            self._cooldown_pruning_loop.cancel()

    # ── Cooldown Pruning ────────────────────────────────────────

    @tasks.loop(minutes=30)
    async def _cooldown_pruning_loop(self) -> None:
        """Prune expired cooldown timestamps to prevent memory growth."""
        now = time.monotonic()
        expired = [
            key
            for key, timestamp in self._cooldowns.items()
            if now - timestamp > self.COOLDOWN_SECONDS * 5
        ]
        for key in expired:
            self._cooldowns.pop(key, None)

    @_cooldown_pruning_loop.before_loop
    async def _before_pruning(self) -> None:
        """Wait until bot is ready before starting loop."""
        await self.bot.wait_until_ready()

    # ── Anti-Spam & XP Qualification ────────────────────────────

    def should_award_xp(self, message: discord.Message) -> bool:
        """Evaluate if a message qualifies for XP award.

        Enforces:
        - Human members only (bots never gain XP)
        - Guild context only (no DMs)
        - Webhook messages rejected
        - Default or reply message types only
        - Non-empty content with at least 3 characters
        - Prefix commands excluded
        - 60s in-memory cooldown per user per guild
        """
        if message.author.bot:
            return False

        if not message.guild or not isinstance(message.author, discord.Member):
            return False

        if message.webhook_id is not None:
            return False

        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return False

        content = message.content.strip()
        if len(content) < 3:
            return False

        prefix = getattr(self.bot.config, "prefix", "!c")
        if content.lower().startswith(prefix.lower()):
            return False

        now = time.monotonic()
        key = (message.guild.id, message.author.id)
        last_time = self._cooldowns.get(key, 0.0)
        if now - last_time < self.COOLDOWN_SECONDS:
            return False

        return True

    # ── Message XP Processing ───────────────────────────────────

    async def process_message_xp(
        self,
        message: discord.Message,
    ) -> tuple[bool, MemberLevel | None, bool]:
        """Process incoming chat message for XP gain and level advancement.

        Returns:
            (awarded: bool, member_data: MemberLevel | None, leveled_up: bool)
        """
        if not self.should_award_xp(message):
            return False, None, False

        assert message.guild is not None
        assert isinstance(message.author, discord.Member)

        # Check if leveling is enabled in guild
        if not await self.repo.is_leveling_enabled(message.guild.id):
            return False, None, False

        # Set in-memory cooldown immediately
        self._cooldowns[(message.guild.id, message.author.id)] = time.monotonic()

        xp_gain = random.randint(self.XP_MIN, self.XP_MAX)
        current = await self.repo.get_or_create_member(
            message.guild.id, message.author.id
        )

        new_total_xp = current.xp + xp_gain
        new_level = level_from_xp(new_total_xp)

        updated = await self.repo.add_xp(
            message.guild.id,
            message.author.id,
            xp_gain,
            new_level,
        )

        leveled_up = new_level > current.level
        if leveled_up:
            awarded_roles = await self.check_and_assign_rewards(
                message.author, new_level
            )
            await self.dispatch_levelup_announcement(
                member=message.author,
                original_channel=message.channel,
                old_level=current.level,
                new_level=new_level,
                awarded_roles=awarded_roles,
            )

        return True, updated, leveled_up

    # ── Role Reward Management ──────────────────────────────────

    async def check_and_assign_rewards(
        self,
        member: discord.Member,
        new_level: int,
    ) -> list[discord.Role]:
        """Evaluate and grant role rewards attained at or below the new level.

        Safely validates bot permissions, role hierarchy, and duplicate roles.
        """
        guild = member.guild
        rewards = await self.repo.get_level_rewards(guild.id)
        if not rewards:
            return []

        bot_member = guild.me
        if not bot_member.guild_permissions.manage_roles:
            log.warning(
                "Cannot grant level role in guild %d: missing Manage Roles permission",
                guild.id,
            )
            return []

        awarded: list[discord.Role] = []
        for reward in rewards:
            if reward.level <= new_level:
                role = guild.get_role(reward.role_id)
                if role is None:
                    continue

                if role in member.roles:
                    continue

                # Ensure bot hierarchy is strictly superior to reward role
                if role >= bot_member.top_role:
                    log.warning(
                        "Cannot grant role '%s' in guild %d: role hierarchy restriction",
                        role.name,
                        guild.id,
                    )
                    continue

                try:
                    await member.add_roles(
                        role,
                        reason=f"Celesteria Level {reward.level} Reward",
                    )
                    awarded.append(role)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.warning(
                        "Failed to grant role '%s' to %d in guild %d: %s",
                        role.name,
                        member.id,
                        guild.id,
                        exc,
                    )

        return awarded

    # ── Level-Up Announcement ───────────────────────────────────

    async def dispatch_levelup_announcement(
        self,
        member: discord.Member,
        original_channel: discord.abc.Messageable,
        old_level: int,
        new_level: int,
        awarded_roles: list[discord.Role],
    ) -> bool:
        """Send a themed level-up card to the designated announcement channel."""
        guild = member.guild
        channel_id = await self.repo.get_levelup_channel_id(guild.id)

        # -1 represents completely muted/silent level-ups
        if channel_id == -1:
            return False

        target_channel = original_channel
        if channel_id and channel_id > 0:
            configured_channel = guild.get_channel(channel_id)
            if isinstance(configured_channel, (discord.TextChannel, discord.Thread)):
                perms = configured_channel.permissions_for(guild.me)
                if perms.send_messages and perms.embed_links:
                    target_channel = configured_channel

        embed = self.build_levelup_embed(member, new_level, awarded_roles)
        try:
            await target_channel.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    def build_levelup_embed(
        self,
        member: discord.Member,
        new_level: int,
        awarded_roles: list[discord.Role],
    ) -> discord.Embed:
        """Create a royal level-up celebration embed."""
        title_str = get_level_title(new_level)
        embed = CelesteriaEmbed._base(
            Palette.WARNING,
            title=f"{Icon.BRAND} A New Rank Has Been Earned",
            description=(
                f"Hail, {member.mention}! Through renown and service, "
                f"you have ascended to **Level {new_level}** (*{title_str}*)."
            ),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if awarded_roles:
            roles_text = " ".join(r.mention for r in awarded_roles)
            embed.add_field(
                name="Royal Bestowments",
                value=f"You have been granted: {roles_text}",
                inline=False,
            )

        embed.set_footer(text=f"Realm Honor │ {Brand.FOOTER}")
        return embed

    # ── Embed Builders ──────────────────────────────────────────

    def build_level_embed(
        self,
        member: discord.Member,
        data: MemberLevel,
        rank: int,
    ) -> discord.Embed:
        """Construct the compact `/level` progression embed."""
        level, base_xp, target_xp, progress_pct = get_level_tier_info(data.xp)
        title_str = get_level_title(level)
        bar = format_progress_bar(data.xp - base_xp, target_xp - base_xp, 10)

        embed = CelesteriaEmbed._base(
            Palette.SECONDARY,
            title=f"{Icon.BRAND} Level Progression — {member.display_name}",
            description=f"{member.mention} · *{title_str}*",
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Level", value=f"`{level}`", inline=True)
        embed.add_field(name="Server Rank", value=f"`#{rank}`", inline=True)
        embed.add_field(
            name="Total Experience",
            value=f"`{format_number(data.xp)} XP`",
            inline=True,
        )

        tier_current = max(0, data.xp - base_xp)
        tier_needed = target_xp - base_xp
        embed.add_field(
            name=f"Progress to Level {level + 1}",
            value=(
                f"`{bar}` **{int(progress_pct)}%**\n"
                f"└ `{format_number(tier_current)}` / `{format_number(tier_needed)} XP` "
                f"(*{format_number(tier_needed - tier_current)} XP remaining*)"
            ),
            inline=False,
        )
        return embed

    def build_profile_embed(
        self,
        member: discord.Member,
        data: MemberLevel,
        rank: int,
        held_rewards: list[discord.Role],
    ) -> discord.Embed:
        """Construct the royal `/profile` character progression embed."""
        level, base_xp, target_xp, progress_pct = get_level_tier_info(data.xp)
        title_str = get_level_title(level)
        bar = format_progress_bar(data.xp - base_xp, target_xp - base_xp, 10)

        embed_color = (
            member.colour
            if member.colour != discord.Colour.default()
            else Palette.PRIMARY
        )
        embed = CelesteriaEmbed._base(
            embed_color,
            title=f"{Icon.BRAND} Celesteria Profile",
            description=f"{member.mention} · *Citizen of {member.guild.name}*",
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(
            name="Level & Rank",
            value=f"**{title_str}**\nLevel `{level}`",
            inline=True,
        )
        embed.add_field(
            name="Hall of Fame",
            value=f"Rank **#{rank}**",
            inline=True,
        )
        embed.add_field(
            name="Experience",
            value=f"`{format_number(data.xp)}` / `{format_number(target_xp)}`",
            inline=True,
        )

        embed.add_field(
            name="Progress",
            value=f"`{bar}` **{int(progress_pct)}%**",
            inline=True,
        )
        embed.add_field(
            name="Chronicles Written",
            value=f"`{format_number(data.message_count)} scrolls`",
            inline=True,
        )

        joined_str = (
            f"{format_timestamp(member.joined_at, 'D')} ({format_relative(member.joined_at)})"
            if member.joined_at
            else "*Unknown*"
        )
        embed.add_field(name="Joined Realm", value=joined_str, inline=True)

        if held_rewards:
            roles_text = " ".join(r.mention for r in held_rewards[:8])
            if len(held_rewards) > 8:
                roles_text += f" *+{len(held_rewards) - 8} more*"
            embed.add_field(
                name="Earned Royal Roles",
                value=roles_text,
                inline=False,
            )

        embed.set_footer(
            text=f"User ID: {member.id} │ {Brand.FOOTER}"
        )
        return embed

    async def build_leaderboard_embed(
        self,
        guild: discord.Guild,
        page: int,
        total_pages: int,
        entries: list[MemberLevel],
        invoker: discord.Member,
        invoker_rank: int,
        invoker_data: MemberLevel,
    ) -> discord.Embed:
        """Construct a paginated Royal Hall of Fame leaderboard embed."""
        embed = CelesteriaEmbed.standard(
            f"Royal Hall of Fame — {guild.name}",
            f"*{Brand.TAGLINE}*\nTop citizens ranked by renown and wisdom.",
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        lines: list[str] = []
        start_rank = (page - 1) * 10 + 1

        for idx, entry in enumerate(entries):
            rank_num = start_rank + idx
            member = guild.get_member(entry.user_id)
            name = member.display_name if member else f"Citizen `{entry.user_id}`"
            lvl_title = get_level_title(entry.level)

            if rank_num == 1:
                prefix = f"{Icon.CROWN} **#1**"
            elif rank_num == 2:
                prefix = f"{Icon.MODERATION} **#2**"
            elif rank_num == 3:
                prefix = f"{Icon.SHIELD} **#3**"
            else:
                prefix = f"**#{rank_num}**"

            lines.append(
                f"{prefix} **{name}** — Level `{entry.level}` ({lvl_title}) · `{format_number(entry.xp)} XP`"
            )

        leaderboard_text = "\n".join(lines) if lines else "*No chronicles recorded yet.*"
        embed.add_field(name="Standings", value=leaderboard_text, inline=False)

        # Highlight invoker standing
        inv_title = get_level_title(invoker_data.level)
        embed.add_field(
            name="Your Standing",
            value=(
                f"**#{invoker_rank}** {invoker.mention} — "
                f"Level `{invoker_data.level}` (*{inv_title}*) · `{format_number(invoker_data.xp)} XP`"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Page {page} of {total_pages} │ {Brand.FOOTER}"
        )
        return embed

