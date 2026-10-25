"""Duration parsing and formatting utilities for Celesteria.

Handles human-friendly duration strings (e.g. '10m', '2h', '1d', '7d')
and enforces Discord timeout constraints (5 seconds to 28 days).
"""

from __future__ import annotations

import re
from datetime import timedelta

_DURATION_REGEX = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

_UNIT_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}

MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 28 * 86400  # 28 days (Discord API limit)


def parse_duration(duration_str: str) -> tuple[int, timedelta]:
    """Parse a duration string into total seconds and a timedelta.

    Supported units:
        s -> seconds
        m -> minutes
        h -> hours
        d -> days
        w -> weeks

    Examples:
        '10m'    -> 600 seconds
        '2h 30m' -> 9000 seconds
        '7d'     -> 604800 seconds

    Raises:
        ValueError: If duration format is invalid, less than 5 seconds,
                    or exceeds 28 days.
    """
    clean_str = duration_str.strip().lower()
    matches = _DURATION_REGEX.findall(clean_str)

    if not matches:
        raise ValueError(
            f"Invalid duration format: `{duration_str}`. "
            "Use formats like `10m`, `2h`, `1d`, or `7d`."
        )

    # Check for unrecognized tokens
    reconstructed = "".join(f"{num}{unit}" for num, unit in matches)
    stripped_original = re.sub(r"\s+", "", clean_str)
    if reconstructed != stripped_original:
        raise ValueError(
            f"Invalid duration format: `{duration_str}`. "
            "Use formats like `10m`, `2h`, `1d`, or `7d`."
        )

    total_seconds = sum(int(num) * _UNIT_MULTIPLIERS[unit] for num, unit in matches)

    if total_seconds < MIN_TIMEOUT_SECONDS:
        raise ValueError(
            f"Duration must be at least {MIN_TIMEOUT_SECONDS} seconds."
        )

    if total_seconds > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            "Duration cannot exceed 28 days (Discord restriction)."
        )

    return total_seconds, timedelta(seconds=total_seconds)


def format_duration(seconds: int) -> str:
    """Format seconds into a descriptive human-readable duration.

    Examples:
        60     -> '1 minute'
        3600   -> '1 hour'
        90000  -> '1 day 1 hour'
    """
    if seconds <= 0:
        return "0 seconds"

    weeks, remainder = divmod(seconds, 604800)
    days, remainder = divmod(remainder, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if weeks:
        parts.append(f"{weeks} week{'s' if weeks != 1 else ''}")
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs and not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")

    return " ".join(parts[:2])

