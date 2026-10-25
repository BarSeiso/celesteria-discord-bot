"""Celesteria Leveling and Social Cog.

Provides hybrid commands and event listeners for:
- /level, !clevel: Inspect individual XP and progression metrics
- /profile, !cprofile: Full royal character profile card
- /leaderboard, !cleaderboard: Paginated Royal Hall of Fame
- /levelrewards, !clevelrewards: View configured role rewards
- /setlevelreward, !csetlevelreward: Configure role rewards for level tiers
- /removelevelreward, !cremovelevelreward: Unbind role rewards
- /setlevelupchannel, !csetlevelupchannel: Direct or mute level-up announcements
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from db.level_repository import LevelReward
from ui.embeds import CelesteriaEmbed
from ui.theme import Brand, Icon, Palette
from ui.views import LeaderboardPaginationView

if TYPE_CHECKING:
    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.cogs.leveling")


class LevelingCog(commands.Cog, name="Social"):
    """Social renown, leveling & character profiles."""

    emoji = "⚜"
    help_description = "Progression, profiles & hall of fame"

    def __init__(self, bot: Celesteria) -> None:
        self.bot = bot
        self.service = bot.level_service
        self.repo = bot.level_repo

    # ── /level · !clevel ────────────────────────────────────────

    @commands.hybrid_command(
        name="level",
        description="Inspect your or another member's level and experience",
    )
    @commands.guild_only()
    @app_commands.describe(member="The member whose level to inspect (defaults to you)")
    async def level(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member | None = None,
    ) -> None:
        """View current level, XP progress bar, and server ranking."""
        assert ctx.guild is not None
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Member Not Found",
                    "Could not locate that member within this server.",
                )
            )
            return

        if target.bot:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Arcane Construct",
                    f"{target.mention} is an automated sentinel and does not accumulate renown.",
                )
            )
            return

        data = await self.repo.get_or_create_member(ctx.guild.id, target.id)
        rank = await self.repo.get_user_rank(ctx.guild.id, target.id)

        embed = self.service.build_level_embed(target, data, rank)
        await ctx.send(embed=embed)

    # ── /profile · !cprofile ────────────────────────────────────

    @commands.hybrid_command(
        name="profile",
        description="Display your or another member's Celesteria character profile",
    )
    @commands.guild_only()
    @app_commands.describe(member="The member whose profile to view (defaults to you)")
    async def profile(
        self,
        ctx: commands.Context[Celesteria],
        member: discord.Member | None = None,
    ) -> None:
        """Display an immersive royal character profile with Celesteria progression."""
        assert ctx.guild is not None
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Member Not Found",
                    "Could not locate that member within this server.",
                )
            )
            return

        if target.bot:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Arcane Construct",
                    f"{target.mention} is an automated sentinel and does not hold a mortal profile.",
                )
            )
            return

        data = await self.repo.get_or_create_member(ctx.guild.id, target.id)
        rank = await self.repo.get_user_rank(ctx.guild.id, target.id)

        # Collect reward roles held by this member
        all_rewards = await self.repo.get_level_rewards(ctx.guild.id)
        held_roles: list[discord.Role] = []
        for r in all_rewards:
            role = ctx.guild.get_role(r.role_id)
            if role and role in target.roles:
                held_roles.append(role)

        embed = self.service.build_profile_embed(target, data, rank, held_roles)
        await ctx.send(embed=embed)

    # ── /leaderboard · !cleaderboard ────────────────────────────

    @commands.hybrid_command(
        name="leaderboard",
        description="Behold the Royal Hall of Fame and top-ranked realm citizens",
    )
    @commands.guild_only()
    @app_commands.describe(page="Page number of the Hall of Fame (defaults to 1)")
    async def leaderboard(
        self,
        ctx: commands.Context[Celesteria],
        page: int = 1,
    ) -> None:
        """View the top-ranked members in the server with interactive pagination."""
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        total_ranked = await self.repo.count_ranked_members(ctx.guild.id)
        if total_ranked == 0:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Hall of Fame Empty",
                    "No citizens have accumulated renown in this realm yet. "
                    "Converse in the channels to earn the first honors!",
                )
            )
            return

        total_pages = max(1, math.ceil(total_ranked / 10))
        clamped_page = max(1, min(page, total_pages))

        invoker_rank = await self.repo.get_user_rank(ctx.guild.id, ctx.author.id)
        invoker_data = await self.repo.get_or_create_member(
            ctx.guild.id, ctx.author.id
        )

        async def page_loader(target_p: int) -> discord.Embed:
            offset = (target_p - 1) * 10
            entries = await self.repo.get_leaderboard(
                ctx.guild.id, limit=10, offset=offset
            )
            return await self.service.build_leaderboard_embed(
                guild=ctx.guild,
                page=target_p,
                total_pages=total_pages,
                entries=entries,
                invoker=ctx.author,
                invoker_rank=invoker_rank,
                invoker_data=invoker_data,
            )

        initial_embed = await page_loader(clamped_page)

        if total_pages > 1:
            view = LeaderboardPaginationView(
                author_id=ctx.author.id,
                total_pages=total_pages,
                page_loader=page_loader,
                timeout=60.0,
            )
            view.current_page = clamped_page
            view._update_button_states()
            msg = await ctx.send(embed=initial_embed, view=view)
            view.message = msg
        else:
            await ctx.send(embed=initial_embed)

    # ── /levelrewards · !clevelrewards ──────────────────────────

    @commands.hybrid_command(
        name="levelrewards",
        description="Inspect all configured role rewards for level progression",
    )
    @commands.guild_only()
    async def levelrewards(self, ctx: commands.Context[Celesteria]) -> None:
        """List all role rewards configured for reaching level milestones."""
        assert ctx.guild is not None

        rewards = await self.repo.get_level_rewards(ctx.guild.id)
        if not rewards:
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "No Level Rewards Configured",
                    "This server currently has no role rewards bound to levels.\n"
                    "Administrators can configure rewards with `/setlevelreward`.",
                )
            )
            return

        lines: list[str] = []
        for r in rewards:
            role = ctx.guild.get_role(r.role_id)
            if role:
                status = ""
                if role >= ctx.guild.me.top_role:
                    status = " ⚠ *(Bot cannot assign: role higher than bot)*"
                lines.append(f"• **Level {r.level}** → {role.mention}{status}")
            else:
                lines.append(f"• **Level {r.level}** → `Deleted Role ({r.role_id})`")

        embed = CelesteriaEmbed.standard(
            f"Royal Decrees — Level Rewards",
            f"Role honors automatically bestowed upon reaching level tiers:\n\n"
            + "\n".join(lines),
        )
        embed.set_footer(
            text=f"Total Rewards: {len(rewards)} │ {Brand.FOOTER}"
        )
        await ctx.send(embed=embed)

    # ── /setlevelreward · !csetlevelreward ──────────────────────

    @commands.hybrid_command(
        name="setlevelreward",
        description="Assign a Discord role as a reward for attaining a level tier",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        level="The level required to earn this role (1 or higher)",
        role="The role to bestow upon reaching this level tier",
    )
    async def setlevelreward(
        self,
        ctx: commands.Context[Celesteria],
        level: int,
        role: discord.Role,
    ) -> None:
        """Bind a Discord role to be awarded automatically when reaching a level."""
        assert ctx.guild is not None

        if level < 1:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Invalid Level Tier",
                    "Reward level must be at least Level 1.",
                )
            )
            return

        if role >= ctx.guild.me.top_role and ctx.guild.owner_id != ctx.guild.me.id:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Role Hierarchy Conflict",
                    f"The role {role.mention} is equal to or higher than my highest role "
                    f"({ctx.guild.me.top_role.mention}). I will not be able to assign it.",
                )
            )
            return

        if role.is_default() or role.managed:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Unassignable Role",
                    f"The role {role.mention} is managed by an integration or is the default role.",
                )
            )
            return

        await self.repo.set_level_reward(ctx.guild.id, level, role.id)

        embed = CelesteriaEmbed.success(
            "Level Reward Configured",
            f"Members attaining **Level {level}** will henceforth be bestowed {role.mention}.",
        )
        embed.add_field(name="Level Required", value=f"`Level {level}`", inline=True)
        embed.add_field(name="Bestowed Role", value=role.mention, inline=True)
        await ctx.send(embed=embed)

    # ── /removelevelreward · !cremovelevelreward ────────────────

    @commands.hybrid_command(
        name="removelevelreward",
        description="Remove a configured role reward for a level tier",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(level="The level tier whose reward should be revoked")
    async def removelevelreward(
        self,
        ctx: commands.Context[Celesteria],
        level: int,
    ) -> None:
        """Unbind any role reward assigned to a specific level tier."""
        assert ctx.guild is not None

        removed = await self.repo.remove_level_reward(ctx.guild.id, level)
        if not removed:
            await ctx.send(
                embed=CelesteriaEmbed.warning(
                    "Reward Not Found",
                    f"No role reward is currently configured for **Level {level}**.",
                )
            )
            return

        await ctx.send(
            embed=CelesteriaEmbed.success(
                "Level Reward Removed",
                f"The role reward for **Level {level}** has been revoked.",
            )
        )

    # ── /setlevelupchannel · !csetlevelupchannel ────────────────

    @commands.hybrid_command(
        name="setlevelupchannel",
        description="Configure where level advancement celebrations are heralded",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel for announcements (leave empty to celebrate in chat)",
        mute="Silence level-up announcements entirely across the realm",
    )
    async def setlevelupchannel(
        self,
        ctx: commands.Context[Celesteria],
        channel: discord.TextChannel | None = None,
        mute: bool = False,
    ) -> None:
        """Direct level-up celebrations to a specific channel or mute them entirely."""
        assert ctx.guild is not None

        if mute:
            await self.repo.set_levelup_channel_id(ctx.guild.id, -1)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Level-Up Herald Muted",
                    "Level advancement announcements have been muted throughout the realm.",
                )
            )
            return

        if channel is None:
            await self.repo.set_levelup_channel_id(ctx.guild.id, None)
            await ctx.send(
                embed=CelesteriaEmbed.info(
                    "Level-Up Herald Reset",
                    "Level advancement announcements will now be heralded directly in the active chat channel.",
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

        await self.repo.set_levelup_channel_id(ctx.guild.id, channel.id)
        await ctx.send(
            embed=CelesteriaEmbed.success(
                "Level-Up Channel Configured",
                f"Level advancement announcements will henceforth be heralded in {channel.mention}.",
            )
        )

    # ── Gateway Message Listener ────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Process chat messages for XP accumulation and rank advancement."""
        await self.service.process_message_xp(message)


async def setup(bot: Celesteria) -> None:
    """Load the Leveling cog."""
    await bot.add_cog(LevelingCog(bot))

