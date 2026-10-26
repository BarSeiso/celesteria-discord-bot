"""Celesteria error handling.

Provides the global error handler that ensures users always see
a clean, themed error embed — never a raw traceback or unhandled
exception. Internal details are logged; users see friendly messages.
"""

from __future__ import annotations

import logging
import secrets

import discord
from discord import app_commands
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
    ctx: commands.Context | discord.Interaction | None = None,
) -> discord.Embed:
    """Create an appropriate themed embed for a command error.

    Routes known error types (both prefix and app/slash commands) to specific
    user-friendly messages. Unknown errors get a generic royal message with an
    Error ID for support tracking.

    Returns:
        A ``discord.Embed`` ready to send to the user.
    """
    # Unwrap wrapped errors (hybrid commands or command invoke errors wrap the original)
    original = getattr(error, "original", error)

    # ── Permission & Role Hierarchy Errors ──────────────────────
    if isinstance(original, (commands.MissingPermissions, app_commands.MissingPermissions)):
        missing_perms = [p.replace("_", " ").title() for p in original.missing_permissions]
        missing_str = ", ".join(missing_perms)
        return CelesteriaEmbed.permission_denied(
            f"You require the following permission{'s' if len(missing_perms) > 1 else ''}: **{missing_str}**"
        )

    if isinstance(original, (commands.BotMissingPermissions, app_commands.BotMissingPermissions)):
        missing_perms = [p.replace("_", " ").title() for p in original.missing_permissions]
        missing_str = ", ".join(missing_perms)
        return CelesteriaEmbed.error(
            "Bot Missing Permissions",
            f"I require the following permission{'s' if len(missing_perms) > 1 else ''} to execute this decree: **{missing_str}**",
        )

    if isinstance(original, PermissionError):
        # Domain services raise PermissionError with descriptive hierarchy messages
        return CelesteriaEmbed.permission_denied(str(original))

    if isinstance(original, discord.Forbidden):
        return CelesteriaEmbed.error(
            "Access Denied by Discord",
            "Discord rejected this action due to missing bot permissions or role hierarchy restrictions in this server.",
        )

    if isinstance(original, discord.NotFound):
        return CelesteriaEmbed.warning(
            "Resource Not Found",
            "The requested Discord channel, message, role, or member no longer exists.",
        )

    # ── Cooldowns ───────────────────────────────────────────────
    if isinstance(original, (commands.CommandOnCooldown, app_commands.CommandOnCooldown)):
        return CelesteriaEmbed.warning(
            "Command on Cooldown",
            f"Please wait **{original.retry_after:.1f}s** before invoking this decree again.",
        )

    # ── Argument & Resolution Errors ────────────────────────────
    if isinstance(original, commands.MissingRequiredArgument):
        usage = ""
        if isinstance(ctx, commands.Context) and ctx.command:
            usage = f"\n\nUsage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`"
        return CelesteriaEmbed.warning(
            "Missing Argument",
            f"The `{original.param.name}` argument is required.{usage}",
        )

    if isinstance(original, commands.MemberNotFound):
        return CelesteriaEmbed.warning(
            "Member Not Found",
            f"Could not locate member `{original.argument}` in this server.",
        )

    if isinstance(original, commands.UserNotFound):
        return CelesteriaEmbed.warning(
            "User Not Found",
            f"Could not locate user `{original.argument}`.",
        )

    if isinstance(original, commands.ChannelNotFound):
        return CelesteriaEmbed.warning(
            "Channel Not Found",
            f"Could not locate channel `{original.argument}` in this server.",
        )

    if isinstance(original, commands.RoleNotFound):
        return CelesteriaEmbed.warning(
            "Role Not Found",
            f"Could not locate role `{original.argument}` in this server.",
        )

    if isinstance(original, commands.RangeError):
        return CelesteriaEmbed.warning(
            "Value Out of Range",
            str(original),
        )

    if isinstance(original, (commands.BadArgument, app_commands.TransformerError)):
        return CelesteriaEmbed.warning(
            "Invalid Argument",
            str(original),
        )

    # ── Checks & Restrictions ───────────────────────────────────
    if isinstance(original, commands.NotOwner):
        return CelesteriaEmbed.permission_denied(
            "This command is restricted to the bot sovereign."
        )

    if isinstance(original, (commands.CheckFailure, app_commands.CheckFailure)):
        return CelesteriaEmbed.permission_denied(
            "You do not meet the prerequisites to execute this command."
        )

    # ── Unexpected Errors ───────────────────────────────────────
    error_id = generate_error_id()
    if isinstance(ctx, commands.Context) and ctx.command:
        cmd_name = ctx.command.qualified_name
    elif isinstance(ctx, discord.Interaction) and ctx.command:
        cmd_name = ctx.command.qualified_name
    else:
        cmd_name = "unknown"

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
        "This incident has been recorded in the royal chronicles for investigation.",
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
