"""Celesteria Level and XP data access repository.

Handles persistence and querying for:
- Member experience points (XP), levels, and message counts
- Guild leaderboard rankings
- Configurable level role rewards
- Guild leveling feature toggles and announcement channels
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database


@dataclass(frozen=True)
class MemberLevel:
    """Represents a member's XP and leveling progress in a guild."""

    guild_id: int
    user_id: int
    xp: int = 0
    level: int = 0
    message_count: int = 0
    last_xp_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> MemberLevel:
        """Construct a MemberLevel from an aiosqlite Row."""
        return cls(
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            xp=int(row["xp"]),
            level=int(row["level"]),
            message_count=int(row["message_count"]),
            last_xp_at=str(row["last_xp_at"]) if row["last_xp_at"] else "",
        )


@dataclass(frozen=True)
class LevelReward:
    """Represents a configured role reward for attaining a level tier."""

    guild_id: int
    level: int
    role_id: int
    created_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> LevelReward:
        """Construct a LevelReward from an aiosqlite Row."""
        return cls(
            guild_id=int(row["guild_id"]),
            level=int(row["level"]),
            role_id=int(row["role_id"]),
            created_at=str(row["created_at"]) if row["created_at"] else "",
        )


class LevelRepository:
    """Repository managing guild member leveling and reward data."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Member Progression ──────────────────────────────────────

    async def get_member(self, guild_id: int, user_id: int) -> MemberLevel | None:
        """Fetch leveling progress for a member in a guild."""
        sql = "SELECT * FROM member_levels WHERE guild_id = ? AND user_id = ?"
        row = await self.db.fetchone(sql, (guild_id, user_id))
        return MemberLevel.from_row(row) if row else None

    async def get_or_create_member(self, guild_id: int, user_id: int) -> MemberLevel:
        """Fetch member level or return default Level 0 instance if non-existent."""
        record = await self.get_member(guild_id, user_id)
        if record is not None:
            return record
        return MemberLevel(guild_id=guild_id, user_id=user_id)

    async def add_xp(
        self,
        guild_id: int,
        user_id: int,
        xp_gain: int,
        new_level: int,
    ) -> MemberLevel:
        """Atomically award XP, update level, and increment message counter."""
        sql = """
            INSERT INTO member_levels (
                guild_id, user_id, xp, level, message_count, last_xp_at
            ) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = xp + excluded.xp,
                level = excluded.level,
                message_count = message_count + 1,
                last_xp_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, user_id, xp_gain, new_level))
        updated = await self.get_member(guild_id, user_id)
        if updated is None:
            raise RuntimeError(f"Failed to fetch updated member {user_id} in {guild_id}")
        return updated

    async def get_user_rank(self, guild_id: int, user_id: int) -> int:
        """Calculate member's 1-indexed leaderboard rank in the guild."""
        # Check current member's XP
        member = await self.get_member(guild_id, user_id)
        if member is None or member.xp <= 0:
            count_sql = "SELECT COUNT(*) AS total FROM member_levels WHERE guild_id = ? AND xp > 0"
            row = await self.db.fetchone(count_sql, (guild_id,))
            return (int(row["total"]) + 1) if row else 1

        sql = """
            SELECT COUNT(*) + 1 AS rank
            FROM member_levels
            WHERE guild_id = ? AND (
                xp > ? OR (xp = ? AND last_xp_at < ?)
            )
        """
        row = await self.db.fetchone(sql, (guild_id, member.xp, member.xp, member.last_xp_at))
        return int(row["rank"]) if row else 1

    # ── Leaderboard ─────────────────────────────────────────────

    async def get_leaderboard(
        self,
        guild_id: int,
        limit: int = 10,
        offset: int = 0,
    ) -> list[MemberLevel]:
        """Fetch a page of ranked guild members ordered by XP descending."""
        sql = """
            SELECT * FROM member_levels
            WHERE guild_id = ? AND xp > 0
            ORDER BY xp DESC, last_xp_at ASC
            LIMIT ? OFFSET ?
        """
        rows = await self.db.fetchall(sql, (guild_id, limit, offset))
        return [MemberLevel.from_row(r) for r in rows]

    async def count_ranked_members(self, guild_id: int) -> int:
        """Count total members who have acquired XP in this guild."""
        sql = "SELECT COUNT(*) AS total FROM member_levels WHERE guild_id = ? AND xp > 0"
        row = await self.db.fetchone(sql, (guild_id,))
        return int(row["total"]) if row else 0

    # ── Level Role Rewards ──────────────────────────────────────

    async def get_level_rewards(self, guild_id: int) -> list[LevelReward]:
        """Fetch all role rewards configured for a guild ordered by level."""
        sql = "SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level ASC"
        rows = await self.db.fetchall(sql, (guild_id,))
        return [LevelReward.from_row(r) for r in rows]

    async def get_reward_for_level(self, guild_id: int, level: int) -> LevelReward | None:
        """Fetch role reward configured for an exact level tier."""
        sql = "SELECT * FROM level_rewards WHERE guild_id = ? AND level = ?"
        row = await self.db.fetchone(sql, (guild_id, level))
        return LevelReward.from_row(row) if row else None

    async def set_level_reward(self, guild_id: int, level: int, role_id: int) -> LevelReward:
        """Assign or update a role reward for attaining a level tier."""
        sql = """
            INSERT INTO level_rewards (guild_id, level, role_id, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, level) DO UPDATE SET
                role_id = excluded.role_id,
                created_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, level, role_id))
        reward = await self.get_reward_for_level(guild_id, level)
        if reward is None:
            raise RuntimeError(f"Failed to record level reward for {guild_id} level {level}")
        return reward

    async def remove_level_reward(self, guild_id: int, level: int) -> bool:
        """Remove a configured level reward. Returns True if removed, False if not found."""
        existing = await self.get_reward_for_level(guild_id, level)
        if existing is None:
            return False
        sql = "DELETE FROM level_rewards WHERE guild_id = ? AND level = ?"
        await self.db.execute(sql, (guild_id, level))
        return True

    # ── Leveling Configuration ──────────────────────────────────

    async def is_leveling_enabled(self, guild_id: int) -> bool:
        """Check whether the leveling progression system is enabled for a guild."""
        sql = "SELECT leveling_enabled FROM guild_config WHERE guild_id = ?"
        row = await self.db.fetchone(sql, (guild_id,))
        if row and row["leveling_enabled"] is not None:
            return bool(row["leveling_enabled"])
        return True  # Default enabled

    async def set_leveling_enabled(self, guild_id: int, enabled: bool) -> None:
        """Toggle leveling progression for a guild."""
        val = 1 if enabled else 0
        sql = """
            INSERT INTO guild_config (guild_id, leveling_enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                leveling_enabled = excluded.leveling_enabled,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, val))

    async def get_levelup_channel_id(self, guild_id: int) -> int | None:
        """Retrieve the configured level-up announcement channel ID."""
        sql = "SELECT levelup_channel_id FROM guild_config WHERE guild_id = ?"
        row = await self.db.fetchone(sql, (guild_id,))
        if row and row["levelup_channel_id"] is not None:
            return int(row["levelup_channel_id"])
        return None

    async def set_levelup_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        """Configure or clear the level-up celebration announcement channel."""
        sql = """
            INSERT INTO guild_config (guild_id, levelup_channel_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id) DO UPDATE SET
                levelup_channel_id = excluded.levelup_channel_id,
                updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute(sql, (guild_id, channel_id))

