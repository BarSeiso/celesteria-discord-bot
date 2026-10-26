"""Celesteria interactive UI components.

Provides reusable Views (buttons, select menus, pagination) used
across all bot commands. Every interactive component follows the
Celesteria design system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import discord

from .embeds import CelesteriaEmbed
from .theme import Brand, Icon, Palette

if TYPE_CHECKING:
    from discord.ext import commands

    from bot.celesteria import Celesteria

log = logging.getLogger("celesteria.views")


# ── Help System ─────────────────────────────────────────────────


class HelpCategorySelect(discord.ui.Select["HelpView"]):
    """Dropdown that lets users browse command categories."""

    def __init__(self, bot: Celesteria) -> None:
        self.bot = bot
        options = self._build_options()
        super().__init__(
            placeholder="Choose a category…",
            options=options,
            min_values=1,
            max_values=1,
        )

    def _build_options(self) -> list[discord.SelectOption]:
        """Build select options from loaded cogs."""
        options: list[discord.SelectOption] = []
        for cog_name, cog in self.bot.cogs.items():
            # Only include cogs that have the 'emoji' attribute
            # (user-facing categories) and at least one visible command
            if not hasattr(cog, "emoji"):
                continue
            visible = [c for c in cog.get_commands() if not c.hidden]
            if not visible:
                continue
            emoji = getattr(cog, "emoji", "")
            label = f"{emoji} {cog_name}".strip() if emoji else cog_name
            options.append(
                discord.SelectOption(
                    label=label,
                    value=cog_name,
                    description=getattr(cog, "help_description", ""),
                )
            )
        # Fallback if no categories found
        if not options:
            options.append(
                discord.SelectOption(
                    label="No categories available",
                    value="_empty",
                )
            )
        return options

    async def callback(self, interaction: discord.Interaction) -> None:
        """Update the embed with the selected category's commands."""
        selected = self.values[0]
        if selected == "_empty":
            await interaction.response.defer()
            return

        cog = self.bot.get_cog(selected)
        if cog is None:
            await interaction.response.defer()
            return

        embed = _build_category_embed(cog, self.bot)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    """Interactive help menu with category navigation."""

    def __init__(
        self,
        bot: Celesteria,
        author_id: int,
        *,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.message: discord.Message | None = None
        self.add_item(HelpCategorySelect(bot))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the command invoker can use this menu."""
        if interaction.user.id != self.author_id:
            embed = CelesteriaEmbed.warning(
                "Not Your Menu",
                "This command menu belongs to someone else.\n"
                "Use `/help` or `!chelp` to open your own.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Disable the select menu when the view times out."""
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def build_help_embed(bot: Celesteria) -> discord.Embed:
    """Build the initial help overview embed."""
    # Collect categories
    categories: list[str] = []
    for cog_name, cog in bot.cogs.items():
        if not hasattr(cog, "emoji"):
            continue
        visible = [c for c in cog.get_commands() if not c.hidden]
        if not visible:
            continue
        categories.append(f"{cog.emoji} **{cog_name}** — {len(visible)} commands")

    category_list = "\n".join(categories) if categories else "*No commands loaded.*"

    embed = CelesteriaEmbed.standard(
        f"{Brand.NAME} — Command Codex",
        (
            f"*{Brand.TAGLINE}*\n\n"
            f"Select a category below to browse available commands.\n\n"
            f"{category_list}\n\n"
            f"-# Prefix: `{bot.config.prefix}` · "
            f"Example: `{bot.config.prefix}ping`"
        ),
    )
    return embed


def _build_category_embed(
    cog: commands.Cog,
    bot: Celesteria,
) -> discord.Embed:
    """Build an embed showing all commands in a category."""
    emoji = getattr(cog, "emoji", Icon.ACCENT)
    visible = [c for c in cog.get_commands() if not c.hidden]

    lines: list[str] = []
    for cmd in visible:
        description = cmd.description or cmd.brief or "No description."
        lines.append(f"**`/{cmd.qualified_name}`** — {description}")

    command_list = "\n".join(lines) if lines else "*No commands in this category.*"

    embed = CelesteriaEmbed._base(
        Palette.SECONDARY,
        title=f"{emoji} {cog.qualified_name}",
        description=(
            f"{command_list}\n\n"
            f"-# Prefix: `{bot.config.prefix}` · "
            f"Example: `{bot.config.prefix}{visible[0].qualified_name}`"
            if visible
            else command_list
        ),
    )
    return embed


# ── Confirmation View ───────────────────────────────────────────


class ConfirmView(discord.ui.View):
    """A confirmation prompt with Confirm / Cancel buttons.

    Used for destructive actions like bans. The result is stored
    in ``self.value`` after interaction: True for confirm, False
    for cancel, None for timeout.
    """

    def __init__(
        self,
        author_id: int,
        *,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the command invoker can confirm/cancel."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=CelesteriaEmbed.warning(
                    "Not Your Prompt",
                    "Only the moderator who initiated this action can respond.",
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfirmView"],
    ) -> None:
        """Handle confirm button press."""
        self.value = True
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfirmView"],
    ) -> None:
        """Handle cancel button press."""
        self.value = False
        self._disable_all()
        await interaction.response.edit_message(view=self)
        self.stop()

    def _disable_all(self) -> None:
        """Disable all buttons."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self) -> None:
        """Disable buttons on timeout."""
        self._disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ── Leaderboard Pagination ──────────────────────────────────────


class LeaderboardPaginationView(discord.ui.View):
    """Interactive pagination view for the Royal Hall of Fame."""

    def __init__(
        self,
        author_id: int,
        total_pages: int,
        page_loader: Callable[[int], Awaitable[discord.Embed]],
        *,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.total_pages = max(1, total_pages)
        self.current_page = 1
        self.page_loader = page_loader
        self.message: discord.Message | None = None
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update button enabled/disabled states and page indicator label."""
        self.prev_button.disabled = self.current_page <= 1
        self.page_indicator.label = f"Page {self.current_page} of {self.total_pages}"
        self.next_button.disabled = self.current_page >= self.total_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only the command invoker can paginate this view."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=CelesteriaEmbed.warning(
                    "Not Your Menu",
                    "This leaderboard view belongs to someone else.\n"
                    "Use `/leaderboard` or `!cleaderboard` to open your own.",
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["LeaderboardPaginationView"],
    ) -> None:
        """Navigate to the previous page."""
        if self.current_page > 1:
            self.current_page -= 1
            self._update_button_states()
            embed = await self.page_loader(self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Page 1 of 1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["LeaderboardPaginationView"],
    ) -> None:
        """Static button indicating the current page."""
        await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["LeaderboardPaginationView"],
    ) -> None:
        """Navigate to the next page."""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._update_button_states()
            embed = await self.page_loader(self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self) -> None:
        """Disable buttons upon timeout."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ── Royal Realm Configuration Dashboard ────────────────────────


def build_realm_config_embed(
    bot: Celesteria,
    guild: discord.Guild,
    config: Any,
    rewards_count: int,
) -> discord.Embed:
    """Build the comprehensive Royal Realm Configuration overview embed."""
    embed = CelesteriaEmbed.config_panel(
        f"{guild.name} — Royal Realm Configuration",
        "Overview of active kingdom administration channels, chronicles, and systems.",
    )

    # 1. Welcome System
    if config and config.welcome_channel_id:
        w_chan = guild.get_channel(config.welcome_channel_id)
        w_val = f"{w_chan.mention if w_chan else f'`ID: {config.welcome_channel_id}`'}"
        if config.welcome_message:
            w_val += f"\n└ *Greeting: \"{config.welcome_message[:55]}...\"*"
    else:
        w_val = "*Disabled / Unconfigured* (`/setwelcome`)"
    embed.add_field(name=f"{Icon.BRAND} Welcome System", value=w_val, inline=False)

    # 2. Member Counter
    if config and config.counter_channel_id:
        c_chan = guild.get_channel(config.counter_channel_id)
        c_val = (
            f"{c_chan.mention if c_chan else f'`ID: {config.counter_channel_id}`'}\n"
            f"└ *Template: `{config.counter_template}`*"
        )
    else:
        c_val = "*Disabled / Unconfigured* (`/setcounter`)"
    embed.add_field(name=f"{Icon.CASTLE} Member Counter", value=c_val, inline=False)

    # 3. Server Activity Log
    if config and config.server_log_channel_id:
        s_chan = guild.get_channel(config.server_log_channel_id)
        s_val = f"{s_chan.mention if s_chan else f'`ID: {config.server_log_channel_id}`'}"
    else:
        s_val = "*Disabled / Unconfigured* (`/setserverlog`)"
    embed.add_field(name=f"{Icon.SCROLL} Server Activity Log", value=s_val, inline=True)

    # 4. Moderation Decree Log
    if config and config.mod_log_channel_id:
        m_chan = guild.get_channel(config.mod_log_channel_id)
        m_val = f"{m_chan.mention if m_chan else f'`ID: {config.mod_log_channel_id}`'}"
    else:
        m_val = "*Disabled / Unconfigured* (`/setmodlog`)"
    embed.add_field(name=f"{Icon.MODERATION} Moderation Decree Log", value=m_val, inline=True)

    # 5. Leveling Progression
    is_lvl_enabled = getattr(config, "leveling_enabled", True)
    lvl_status = "🟢 **Enabled**" if is_lvl_enabled else "⚪ **Disabled**"
    lvl_chan_id = getattr(config, "levelup_channel_id", None)
    if lvl_chan_id == -1:
        lvl_chan_str = "Muted Throughout Realm"
    elif lvl_chan_id and lvl_chan_id > 0:
        l_chan = guild.get_channel(lvl_chan_id)
        lvl_chan_str = l_chan.mention if l_chan else f"`ID: {lvl_chan_id}`"
    else:
        lvl_chan_str = "Active Chat Channel"
    lvl_val = f"Status: {lvl_status}\n└ *Announcements: {lvl_chan_str}*"
    embed.add_field(name=f"{Icon.CROWN} Leveling Progression", value=lvl_val, inline=False)

    # 6. XP Role Rewards
    if rewards_count > 0:
        r_val = f"**{rewards_count}** reward tiers configured (`/levelrewards`)"
    else:
        r_val = "*No role rewards configured* (`/setlevelreward`)"
    embed.add_field(name=f"{Icon.SHIELD} Royal Role Rewards", value=r_val, inline=False)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"Guild ID: {guild.id} │ {Brand.FOOTER}")
    return embed


def build_config_category_embed(
    category: str,
    bot: Celesteria,
    guild: discord.Guild,
    config: Any,
    rewards: list[Any],
) -> discord.Embed:
    """Build a detailed view for a specific administrative subsystem."""
    if category == "welcome":
        embed = CelesteriaEmbed.config_panel(
            f"{Icon.BRAND} Welcome System Details",
            "Configuration for royal greetings announced upon citizen arrivals.",
        )
        chan = guild.get_channel(config.welcome_channel_id) if config and config.welcome_channel_id else None
        embed.add_field(
            name="Channel",
            value=chan.mention if chan else "*Not Configured*",
            inline=True,
        )
        embed.add_field(
            name="Template",
            value=f"`{config.welcome_message}`" if config and config.welcome_message else "*Default royal reception*",
            inline=False,
        )
        embed.add_field(
            name="Commands",
            value="• `/setwelcome [channel] [message]` — Bind channel and set greeting\n• `/setwelcome` (no args) — Disable\n• `/testwelcome` — Preview the welcome card",
            inline=False,
        )
        return embed

    if category == "counter":
        embed = CelesteriaEmbed.config_panel(
            f"{Icon.CASTLE} Member Counter Details",
            "Dynamic status channel updated periodically with realm population metrics.",
        )
        chan = guild.get_channel(config.counter_channel_id) if config and config.counter_channel_id else None
        embed.add_field(
            name="Channel",
            value=chan.mention if chan else "*Not Configured*",
            inline=True,
        )
        embed.add_field(
            name="Display Template",
            value=f"`{config.counter_template}`" if config and config.counter_template else "*Default*",
            inline=True,
        )
        embed.add_field(
            name="Commands",
            value="• `/setcounter [channel] [template]` — Bind counter channel\n• `/setcounter` (no args) — Disable\n• Placeholders: `{count}`, `{humans}`, `{bots}`",
            inline=False,
        )
        return embed

    if category == "logs":
        embed = CelesteriaEmbed.config_panel(
            f"{Icon.SCROLL} Chronicles & Audit Logs",
            "Dedicated archival channels for realm activity and moderation decrees.",
        )
        s_chan = guild.get_channel(config.server_log_channel_id) if config and config.server_log_channel_id else None
        m_chan = guild.get_channel(config.mod_log_channel_id) if config and config.mod_log_channel_id else None
        embed.add_field(
            name="Server Activity Log",
            value=s_chan.mention if s_chan else "*Not Configured*",
            inline=True,
        )
        embed.add_field(
            name="Moderation Decree Log",
            value=m_chan.mention if m_chan else "*Not Configured*",
            inline=True,
        )
        embed.add_field(
            name="Commands",
            value="• `/setserverlog [channel]` — Channel for member & server events\n• `/setmodlog [channel]` — Channel for warnings, kicks, bans, timeouts\n• Pass empty channel to disable either log",
            inline=False,
        )
        return embed

    if category == "leveling":
        is_enabled = getattr(config, "leveling_enabled", True)
        embed = CelesteriaEmbed.config_panel(
            f"{Icon.CROWN} Leveling & Role Rewards",
            "Renown accumulation, level-up heralds, and automatic role bestowments.",
        )
        embed.add_field(
            name="Leveling Status",
            value="🟢 **Enabled**" if is_enabled else "⚪ **Disabled**",
            inline=True,
        )
        lvl_chan_id = getattr(config, "levelup_channel_id", None)
        if lvl_chan_id == -1:
            chan_str = "*Muted Throughout Realm*"
        elif lvl_chan_id and lvl_chan_id > 0:
            c = guild.get_channel(lvl_chan_id)
            chan_str = c.mention if c else f"`ID: {lvl_chan_id}`"
        else:
            chan_str = "*Active Chat Channel (Default)*"
        embed.add_field(name="Level-Up Herald", value=chan_str, inline=True)

        if rewards:
            r_lines = []
            for r in rewards[:6]:
                role = guild.get_role(r.role_id)
                r_lines.append(f"• **Level {r.level}** → {role.mention if role else f'`ID: {r.role_id}`'}")
            if len(rewards) > 6:
                r_lines.append(f"*+{len(rewards) - 6} more reward tiers...*")
            rewards_str = "\n".join(r_lines)
        else:
            rewards_str = "*No role reward tiers configured.*"
        embed.add_field(name=f"Configured Role Rewards [{len(rewards)}]", value=rewards_str, inline=False)
        embed.add_field(
            name="Commands",
            value="• `/toggleveling` — Toggle leveling system on/off\n• `/setlevelupchannel [channel] [mute]` — Route level-up celebrations\n• `/setlevelreward [level] [role]` — Add role reward tier\n• `/removelevelreward [level]` — Remove reward tier",
            inline=False,
        )
        return embed

    # Fallback
    return build_realm_config_embed(bot, guild, config, len(rewards))


class ConfigCategorySelect(discord.ui.Select["ConfigDashboardView"]):
    """Dropdown menu to navigate between configuration subsystems."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label="Realm Overview",
                value="overview",
                description="Summary of all active systems and bindings",
                emoji=Icon.BRAND,
                default=True,
            ),
            discord.SelectOption(
                label="Welcome System",
                value="welcome",
                description="Arrival greeting message and announcement channel",
                emoji=Icon.BRAND,
            ),
            discord.SelectOption(
                label="Member Counter",
                value="counter",
                description="Dynamic live member counter channel",
                emoji=Icon.CASTLE,
            ),
            discord.SelectOption(
                label="Chronicles & Logs",
                value="logs",
                description="Server activity logs and moderation decree records",
                emoji=Icon.SCROLL,
            ),
            discord.SelectOption(
                label="Leveling & Rewards",
                value="leveling",
                description="Renown progression, announcement herald, and role rewards",
                emoji=Icon.CROWN,
            ),
        ]
        super().__init__(
            placeholder="Select a system to inspect…",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Render the selected subsystem view."""
        assert self.view is not None
        selected = self.values[0]

        # Update default flags
        for opt in self.options:
            opt.default = opt.value == selected

        self.view.current_category = selected
        embed = await self.view.render_embed()
        await interaction.response.edit_message(embed=embed, view=self.view)


class ConfigDashboardView(discord.ui.View):
    """Interactive administration dashboard view for /config."""

    def __init__(
        self,
        bot: Celesteria,
        guild: discord.Guild,
        author_id: int,
        *,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.author_id = author_id
        self.current_category: str = "overview"
        self.message: discord.Message | None = None

        # Add select menu
        self.select_menu = ConfigCategorySelect()
        self.add_item(self.select_menu)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only administrators or users with Manage Guild can interact."""
        if isinstance(interaction.user, discord.Member):
            if interaction.user.id == self.author_id or interaction.user.guild_permissions.manage_guild:
                return True

        embed = CelesteriaEmbed.permission_denied(
            "Only Realm Administrators may alter realm configuration."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    async def render_embed(self) -> discord.Embed:
        """Fetch current guild state and build the appropriate embed."""
        config = await self.bot.server_repo.get_server_config(self.guild.id)
        rewards = await self.bot.level_repo.get_level_rewards(self.guild.id)

        if self.current_category == "overview":
            return build_realm_config_embed(self.bot, self.guild, config, len(rewards))

        return build_config_category_embed(
            self.current_category,
            self.bot,
            self.guild,
            config,
            rewards,
        )

    @discord.ui.button(label="Toggle Leveling", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_leveling_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfigDashboardView"],
    ) -> None:
        """Toggle the guild leveling system on or off."""
        config = await self.bot.server_repo.get_server_config(self.guild.id)
        current = getattr(config, "leveling_enabled", True) if config else True
        new_state = not current

        await self.bot.server_repo.set_leveling_enabled(self.guild.id, new_state)
        await self.bot.level_repo.set_leveling_enabled(self.guild.id, new_state)

        status_str = "Enabled" if new_state else "Disabled"
        embed = await self.render_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Sync Counter", style=discord.ButtonStyle.secondary, row=1)
    async def sync_counter_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfigDashboardView"],
    ) -> None:
        """Force an immediate check/sync of the member counter."""
        synced = await self.bot.server_service.sync_guild_counter(self.guild.id, force=False)
        if synced:
            msg = "Member counter synchronized with current realm population."
        else:
            msg = (
                "Counter synchronization skipped. Either the counter is already accurate, "
                "not configured, or on cooldown (Discord limits channel renames to 2 per 10m)."
            )
        embed = await self.render_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(content=f"-# ⚜ *{msg}*", ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfigDashboardView"],
    ) -> None:
        """Refresh configuration from database."""
        self.bot.server_repo.invalidate_cache(self.guild.id)
        embed = await self.render_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["ConfigDashboardView"],
    ) -> None:
        """Close the configuration dashboard."""
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        """Disable components on timeout."""
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass



