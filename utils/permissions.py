"""Permission and role hierarchy utilities for Celesteria.

Provides helper functions for validating permissions, checking
role hierarchy, and ensuring the bot can safely perform actions
before attempting them.
"""

from __future__ import annotations

import discord


def can_moderate(
    moderator: discord.Member,
    target: discord.Member,
) -> tuple[bool, str]:
    """Check if a moderator can perform a moderation action on a target.

    Validates:
        - Target is not the guild owner
        - Target is not the moderator themselves
        - Target is not the bot
        - Moderator's top role is higher than target's top role
          (unless moderator is the guild owner)

    Returns:
        (allowed, reason) — if not allowed, reason explains why.
    """
    if target.id == moderator.guild.owner_id:
        return False, "You cannot moderate the server owner."

    if target.id == moderator.id:
        return False, "You cannot moderate yourself."

    if target.id == moderator.guild.me.id:
        return False, "You cannot moderate the bot."

    if (
        target.top_role >= moderator.top_role
        and moderator.id != moderator.guild.owner_id
    ):
        return False, "You cannot moderate someone with an equal or higher role."

    return True, ""


def bot_can_moderate(
    bot_member: discord.Member,
    target: discord.Member,
) -> tuple[bool, str]:
    """Check if the bot itself can perform a moderation action on a target.

    Validates:
        - Target is not the guild owner
        - Bot's top role is higher than target's top role

    Returns:
        (allowed, reason) — if not allowed, reason explains why.
    """
    if target.id == target.guild.owner_id:
        return False, "I cannot moderate the server owner."

    if target.top_role >= bot_member.top_role:
        return False, (
            "I cannot moderate someone with an equal or higher role than mine."
        )

    return True, ""


def check_bot_permissions(
    bot_member: discord.Member,
    **permissions: bool,
) -> tuple[bool, list[str]]:
    """Check if the bot has specific guild-level permissions.

    Args:
        bot_member: The bot's Member object in the guild.
        **permissions: Permission flags to check (e.g., kick_members=True).

    Returns:
        (has_all, missing) — missing is a list of human-readable
        permission names the bot lacks.
    """
    bot_perms = bot_member.guild_permissions
    missing = [
        perm.replace("_", " ").title()
        for perm, required in permissions.items()
        if required and not getattr(bot_perms, perm, False)
    ]
    return len(missing) == 0, missing

