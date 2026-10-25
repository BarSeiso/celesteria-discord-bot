"""Celesteria error handling.

Provides the global error handler that ensures users always see
a clean, themed error embed — never a raw traceback or unhandled
exception. Internal details are logged; users see friendly messages.
"""

from __future__ import annotations

import logging
import secrets

import discord
from discord.ext import commands

from ui.embeds import CelesteriaEmbed

log = logging.getLogger("celesteria.errors")


def generate_error_id() -> str:
    """Generate a short, memorable error ID for user-facing errors.

    Format: CELESTERIA-XXXX (4 hex characters, uppercase).
    """
    return f"CELESTERIA-{secrets.token_hex(2).upper()}"


def build_error_embed(
    error: Exception,
    ctx: commands.Context | None = None,
) -> discord.Embed:
    """Create an appropriate themed embed for a command error.

    Routes known error types to specific messages. Unknown errors
    get a generic message with an Error ID for support tracking.

    Returns:
        A ``discord.Embed`` ready to send to the user.
    """
    # Unwrap wrapped errors (hybrid commands wrap the original)
    original = getattr(error, "original", error)

    if isinstance(original, commands.MissingPermissions):
        missing = ", ".join(original.missing_permissions)
        return CelesteriaEmbed.permission_denied(
            f"You need the following permissions: **{missing}**"
        )

    if isinstance(original, commands.BotMissingPermissions):
        missing = ", ".join(original.missing_permissions)
        return CelesteriaEmbed.error(
            "Bot Missing Permissions",
            f"I need the following permissions to do that: **{missing}**",
        )

    if isinstance(original, commands.MissingRequiredArgument):
        usage = ""
        if ctx and ctx.command:
            usage = (
                f"\n\nUsage: `{ctx.prefix}{ctx.command.qualified_name}"
                f" {ctx.command.signature}`"
            )
        return CelesteriaEmbed.warning(
            "Missing Argument",
            f"The `{original.param.name}` argument is required.{usage}",
        )

    if isinstance(original, commands.BadArgument):
        return CelesteriaEmbed.warning(
            "Invalid Argument",
            str(original),
        )

    if isinstance(original, commands.CommandOnCooldown):
        return CelesteriaEmbed.warning(
            "Command on Cooldown",
            f"Please wait **{original.retry_after:.1f}s** before using this again.",
        )

    if isinstance(original, commands.NotOwner):
        return CelesteriaEmbed.permission_denied(
            "This command is restricted to the bot owner."
        )

    if isinstance(original, commands.CheckFailure):
        return CelesteriaEmbed.permission_denied()

    # ── Unexpected error ────────────────────────────────────────
    error_id = generate_error_id()
    cmd_name = ctx.command.qualified_name if ctx and ctx.command else "unknown"
    log.error(
        "Unhandled error [%s] in command '%s': %s",
        error_id,
        cmd_name,
        original,
        exc_info=original,
    )
    return CelesteriaEmbed.error(
        "Something Went Wrong",
        "An unexpected error occurred while processing that command.\n"
        "This has been logged for investigation.",
        error_id=error_id,
    )


async def send_error_response(
    target: commands.Context | discord.Interaction,
    embed: discord.Embed,
) -> None:
    """Send an error embed to either a Context or an Interaction.

    Handles both prefix (Context) and slash (Interaction) invocations.
    Silently fails if the message cannot be sent (permissions, etc.).
    """
    try:
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                await target.followup.send(embed=embed, ephemeral=True)
            else:
                await target.response.send_message(embed=embed, ephemeral=True)
        else:
            await target.send(embed=embed)
    except discord.HTTPException:
        pass

