"""Celesteria SQLite database manager.

Handles database connection lifecycle, directory setup, WAL mode,
and table initialization using aiosqlite.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

log = logging.getLogger("celesteria.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    mod_log_channel_id INTEGER DEFAULT NULL,
    welcome_channel_id INTEGER DEFAULT NULL,
    welcome_message TEXT DEFAULT NULL,
    counter_channel_id INTEGER DEFAULT NULL,
    counter_template TEXT DEFAULT '🏰 Members: {count}',
    server_log_channel_id INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS moderation_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    target_tag TEXT NOT NULL,
    moderator_id INTEGER NOT NULL,
    moderator_tag TEXT NOT NULL,
    reason TEXT NOT NULL,
    duration_seconds INTEGER DEFAULT NULL,
    extra_data TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_cases_guild_target 
    ON moderation_cases (guild_id, target_id);

CREATE INDEX IF NOT EXISTS idx_cases_guild_case_id 
    ON moderation_cases (guild_id, case_id);
"""


class Database:
    """Asynchronous SQLite connection manager."""

    def __init__(self, database_path: str = "data/celesteria.db") -> None:
        self.path = database_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create directory, open SQLite connection, apply schema and migrations."""
        db_path = Path(self.path)
        if db_path.parent:
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row

        # Performance and safety pragmas
        await self._conn.execute("PRAGMA journal_mode = WAL;")
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.executescript(SCHEMA_SQL)

        # Idempotent column migrations for Phase 3
        async with self._conn.execute("PRAGMA table_info(guild_config);") as cursor:
            rows = await cursor.fetchall()
            existing_cols = {row["name"] for row in rows}

        migrations = [
            ("welcome_channel_id", "INTEGER DEFAULT NULL"),
            ("welcome_message", "TEXT DEFAULT NULL"),
            ("counter_channel_id", "INTEGER DEFAULT NULL"),
            ("counter_template", "TEXT DEFAULT '🏰 Members: {count}'"),
            ("server_log_channel_id", "INTEGER DEFAULT NULL"),
        ]
        for col_name, col_type in migrations:
            if col_name not in existing_cols:
                await self._conn.execute(
                    f"ALTER TABLE guild_config ADD COLUMN {col_name} {col_type};"
                )

        await self._conn.commit()

        log.info("Database initialized at %s", self.path)

    async def close(self) -> None:
        """Gracefully close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("Database connection closed")

    @property
    def connection(self) -> aiosqlite.Connection:
        """Active connection instance. Raises RuntimeError if not initialized."""
        if self._conn is None:
            raise RuntimeError("Database is not initialized. Call initialize() first.")
        return self._conn

    async def execute(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> aiosqlite.Cursor:
        """Execute a query and return cursor."""
        cursor = await self.connection.execute(query, parameters)
        await self.connection.commit()
        return cursor

    async def fetchone(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> aiosqlite.Row | None:
        """Execute a query and fetch one row."""
        async with self.connection.execute(query, parameters) as cursor:
            return await cursor.fetchone()

    async def fetchall(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> list[aiosqlite.Row]:
        """Execute a query and fetch all rows."""
        async with self.connection.execute(query, parameters) as cursor:
            rows = await cursor.fetchall()
            return list(rows)

