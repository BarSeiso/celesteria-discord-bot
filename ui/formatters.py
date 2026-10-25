"""Formatting utilities for Celesteria.

Provides consistent number formatting, relative time display,
uptime rendering, and other text transformations used across
all bot responses.
"""

from __future__ import annotations

from datetime import datetime


def format_number(n: int) -> str:
    """Format a number with commas.

    Example: 1248 → '1,248'
    """
    return f"{n:,}"


def format_uptime(seconds: float) -> str:
    """Format an uptime duration into a human-readable string.

    Shows at most 3 components for readability.

    Examples:
        42      → '42s'
        125     → '2m 5s'
        3661    → '1h 1m 1s'
        90061   → '1d 1h 1m'
    """
    total = int(seconds)

    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts[:3])


def format_timestamp(dt: datetime, style: str = "f") -> str:
    """Format a datetime as a Discord timestamp.

    Discord renders these as localised, live-updating timestamps
    in the client.

    Styles:
        t → Short time       (16:20)
        T → Long time        (16:20:30)
        d → Short date       (20/04/2021)
        D → Long date        (20 April 2021)
        f → Short date/time  (20 April 2021 16:20)  [default]
        F → Long date/time   (Tuesday, 20 April 2021 16:20)
        R → Relative         (2 months ago)
    """
    return f"<t:{int(dt.timestamp())}:{style}>"


def format_relative(dt: datetime) -> str:
    """Format a datetime as a Discord relative timestamp.

    Example: <t:1698163200:R> → '2 days ago' (rendered by Discord).
    """
    return format_timestamp(dt, "R")

