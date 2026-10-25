"""Celesteria visual design system.

Defines the color palette, iconography, and branding constants
used across all bot responses. Every embed must use colors and
icons from this module — no ad-hoc hex values.
"""

from __future__ import annotations

import discord


class Palette:
    """Celesteria color palette — 7 design tokens."""

    PRIMARY   = discord.Colour(0x2B2D42)   # Deep midnight navy
    SECONDARY = discord.Colour(0x5C4B8A)   # Muted royal violet
    SUCCESS   = discord.Colour(0x4A7C59)   # Forest green
    WARNING   = discord.Colour(0xC9A227)   # Antique gold
    ERROR     = discord.Colour(0x8B2035)   # Dark crimson
    INFO      = discord.Colour(0x3D5A80)   # Steel blue
    NEUTRAL   = discord.Colour(0x393B4F)   # Dark charcoal


class Icon:
    """Approved icon set. Only these emoji are used in bot responses."""

    BRAND      = "⚜"
    ACCENT     = "✦"
    MODERATION = "⚔"
    SHIELD     = "🛡"
    SCROLL     = "📜"
    CROWN      = "♛"
    CASTLE     = "🏰"
    WARNING    = "⚠"


class Brand:
    """Celesteria branding constants."""

    NAME    = "Celesteria"
    TAGLINE = "The Royal Companion"
    CREDIT  = "by sunflower1y"
    FOOTER  = "Celesteria · by sunflower1y"

