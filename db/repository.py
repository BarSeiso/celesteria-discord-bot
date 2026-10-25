"""Moderation data access repository.

Provides structured methods to store and query moderation cases
and guild configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database import Database


@dataclass(frozen=True)
class ModerationCase:
    """Represents a single moderation decree/case record."""

    case_id: int
    guild_id: int
    action: str
    target_id: int
    target_tag: str
    moderator_id: int
    moderator_tag: str
    reason: str
    duration_seconds: int | None = None
    extra_data: str | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: dict | any) -> ModerationCase:
        """Construct a ModerationCase from an aiosqlite Row."""
        return cls(
            case_id=row["case_id"],
            guild_id=row["guild_id"],
            action=row["action"],
            target_id=row["target_id"],
            target_tag=row["target_tag"],
            moderator_id=row["moderator_id"],
            moderator_tag=row["moderator_tag"],
            reason=row["reason"],
            duration_seconds=row["duration_seconds"],
            extra_data=row["extra_data"],
            created_at=str(row["created_at"]),
        )


class ModerationRepository:
    """Repository for querying and updating moderation data."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_case(
        self,
        *,
        guild_id: int,
        action: str,
        target_id: int,
        target_tag: str,
        moderator_id: int,
        moderator_tag: str,
        reason: str,
        duration_seconds: int | None = None,
        extra_data: str | None = None,
    ) -> ModerationCase:
        """Create a new moderation case with an auto-incrementing case_id per guild."""
        query_max = (
            "SELECT COALESCE(MAX(case_id), 0) + 1 AS next_id "
            "FROM moderation_cases WHERE guild_id = ?"
        )
        row = await self.db.fetchone(query_max, (guild_id,))
        next_case_id = row["next_id"] if row else 1

        insert_sql = """
            INSERT INTO moderation_cases (
                case_id, guild_id, action, target_id, target_tag,
                moderator_id, moderator_tag, reason, duration_seconds, extra_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self.db.execute(
            insert_sql,
            (
                int(next_case_id),
                int(guild_id),
                str(action).lower(),
                int(target_id),
                str(target_tag),
                int(moderator_id),
                str(moderator_tag),
                str(reason),
                int(duration_seconds) if duration_seconds is not None else None,
                str(extra_data) if extra_data is not None else None,
            ),
        )

        created = await self.get_case(guild_id, next_case_id)
        if created is None:
            raise RuntimeError(f"Failed to create case {next_case_id} for guild {guild_id}")
        return created

    async def get_case(self, guild_id: int, case_id: int) -> ModerationCase | None:
        """Fetch a specific moderation case by its per-guild case ID."""
        sql = "SELECT * FROM moderation_cases WHERE guild_id = ? AND case_id = ?"
        row = await self.db.fetchone(sql, (guild_id, case_id))
        return ModerationCase.from_row(row) if row else None

    async def get_cases_for_target(
        self,
        guild_id: int,
        target_id: int,
        limit: int = 10,
        offset: int = 0,
    ) -> list[ModerationCase]:
        """Fetch cases issued against a specific target in a guild."""
        sql = """
            SELECT * FROM moderation_cases
            WHERE guild_id = ? AND target_id = ?
            ORDER BY case_id DESC
            LIMIT ? OFFSET ?
        """
        rows = await self.db.fetchall(sql, (guild_id, target_id, limit, offset))
        return [ModerationCase.from_row(r) for r in rows]

    async def count_cases_for_target(self, guild_id: int, target_id: int) -> int:
        """Count total cases recorded against a target member in a guild."""
        sql = (
            "SELECT COUNT(*) AS total FROM moderation_cases "
            "WHERE guild_id = ? AND target_id = ?"
        )
        row = await self.db.fetchone(sql, (guild_id, target_id))
        return int(row["total"]) if row else 0

    async def get_recent_cases(
        self,
        guild_id: int,
        limit: int = 10,
        offset: int = 0,
    ) -> list[ModerationCase]:
        """Fetch recent cases recorded in a guild."""
        sql = """
            SELECT * FROM moderation_cases
            WHERE guild_id = ?
            ORDER BY case_id DESC
            LIMIT ? OFFSET ?
        """
        rows = await self.db.fetchall(sql, (guild_id, limit, offset))
        return [ModerationCase.from_row(r) for r in rows]

    async def count_total_cases(self, guild_id: int) -> int:
        """Count total cases recorded for a guild."""
        sql = "SELECT COUNT(*) AS total FROM moderation_cases WHERE guild_id = ?"
        row = await self.db.fetchone(sql, (guild_id,))
        return int(row["total"]) if row else 0

    async def get_mod_log_channel_id(self, guild_id: int) -> int | None:
        """Get the configured mod log channel ID for a guild, if set."""
        sql = "SELECT mod_log_channel_id FROM guild_config WHERE guild_id = ?"
        row = await self.db.fetchone(sql, (guild_id,))
        if row and row["mod_log_channel_id"]:
            return int(row["mod_log_channel_id"])
        return None

    async def set_mod_log_channel_id(
        self,
        guild_id: int,
        channel_id: int | None,
    ) -> None:
        """Configure or clear the mod log channel ID for a guild."""
        sql = """
            INSERT INTO guild_config (guild_id, mod_log_channel_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                mod_log_channel_id = excluded.mod_log_channel_id,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, channel_id))
