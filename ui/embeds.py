"""Celesteria embed builder system.

Provides factory methods for creating consistent, themed embeds.
Every user-facing embed MUST be created through this module to
maintain visual consistency across all bot responses.

Usage:
    from ui.embeds import CelesteriaEmbed

    embed = CelesteriaEmbed.success("Action Complete", "The decree has been issued.")
    embed.add_field(name="Target", value="@user")
    await ctx.send(embed=embed)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from .theme import Brand, Icon, Palette


class CelesteriaEmbed:
    """Factory for creating themed Celesteria embeds.

    All methods return a ``discord.Embed`` that can be further
    customised with fields, images, etc. before sending.
    """

    # ── Private base ────────────────────────────────────────────

    @staticmethod
    def _base(
        colour: discord.Colour,
        title: str | None = None,
        description: str | None = None,
        *,
        timestamp: bool = False,
        footer: str = Brand.FOOTER,
    ) -> discord.Embed:
        """Create a base embed with consistent Celesteria styling."""
        embed = discord.Embed(
            colour=colour,
            title=title,
            description=description,
        )
        embed.set_footer(text=footer)
        if timestamp:
            embed.timestamp = datetime.now(timezone.utc)
        return embed

    # ── Public factories ────────────────────────────────────────

    @classmethod
    def standard(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Standard themed embed — PRIMARY color.

        Use for: general responses, bot information, neutral displays.
        """
        return cls._base(
            Palette.PRIMARY,
            title=f"{Icon.BRAND} {title}",
            description=description,
            **kwargs,
        )

    @classmethod
    def success(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Success embed — SUCCESS color.

        Use for: confirmed actions, completed operations.
        """
        return cls._base(
            Palette.SUCCESS,
            title=f"{Icon.ACCENT} {title}",
            description=description,
            **kwargs,
        )

    @classmethod
    def error(
        cls,
        title: str,
        description: str | None = None,
        *,
        error_id: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Error embed — ERROR color.

        Use for: errors, failures, critical issues.
        If ``error_id`` is provided, it appears in the footer.
        """
        footer = (
            f"Error ID: {error_id} │ {Brand.NAME}"
            if error_id
            else Brand.FOOTER
        )
        return cls._base(
            Palette.ERROR,
            title=f"{Icon.WARNING} {title}",
            description=description,
            footer=footer,
            **kwargs,
        )

    @classmethod
    def warning(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Warning embed — WARNING color.

        Use for: caution states, soft denials, missing arguments.
        """
        return cls._base(
            Palette.WARNING,
            title=f"{Icon.WARNING} {title}",
            description=description,
            **kwargs,
        )

    @classmethod
    def info(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Informational embed — INFO color.

        Use for: neutral information, stats, details.
        """
        return cls._base(
            Palette.INFO,
            title=f"{Icon.ACCENT} {title}",
            description=description,
            **kwargs,
        )

    @classmethod
    def moderation(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Moderation embed — WARNING color with moderation icon.

        Use for: moderation actions, case records. Always timestamped.
        """
        return cls._base(
            Palette.WARNING,
            title=f"{Icon.MODERATION} {title}",
            description=description,
            timestamp=True,
            **kwargs,
        )

    @classmethod
    def permission_denied(cls, reason: str | None = None) -> discord.Embed:
        """Standard permission denied embed.

        Use when a user lacks permission for a command.
        """
        return cls._base(
            Palette.ERROR,
            title=f"{Icon.SHIELD} Permission Denied",
            description=reason or "You don't have permission to use this command.",
        )

    @classmethod
    def welcome(
        cls,
        title: str,
        description: str | None = None,
        *,
        colour: discord.Colour = Palette.PRIMARY,
        icon: str = Icon.BRAND,
        **kwargs: Any,
    ) -> discord.Embed:
        """Welcome announcement embed — themed with timestamp.

        Use for: member arrival announcements.
        """
        return cls._base(
            colour,
            title=f"{icon} {title}",
            description=description,
            timestamp=True,
            **kwargs,
        )

    @classmethod
    def server_log(
        cls,
        title: str,
        description: str | None = None,
        *,
        colour: discord.Colour = Palette.INFO,
        icon: str = Icon.SCROLL,
        **kwargs: Any,
    ) -> discord.Embed:
        """Server activity log embed — configurable theme color and icon.

        Use for: server activity logs. Always timestamped.
        """
        return cls._base(
            colour,
            title=f"{icon} {title}",
            description=description,
            timestamp=True,
            **kwargs,
        )

    @classmethod
    def levelup(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Level-up celebration embed — WARNING (gold) color with brand icon.

        Use for: rank ascensions and reward role bestowments.
        """
        return cls._base(
            Palette.WARNING,
            title=f"{Icon.BRAND} {title}",
            description=description,
            **kwargs,
        )

    @classmethod
    def config_panel(
        cls,
        title: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> discord.Embed:
        """Configuration dashboard embed — PRIMARY color with royal brand icon.

        Use for: server configuration and administrative control centers.
        """
        return cls._base(
            Palette.PRIMARY,
            title=f"{Icon.BRAND} {title}",
            description=description,
            **kwargs,
        )

