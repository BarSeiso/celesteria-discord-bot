"""Celesteria interactive UI components.

Provides reusable Views (buttons, select menus, pagination) used
across all bot commands. Every interactive component follows the
Celesteria design system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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

