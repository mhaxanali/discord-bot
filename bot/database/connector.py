import json
import aiosqlite
from pathlib import Path

from bot.resources.constants import DB_PATH, SCHEMA_PATH


class Connector:
    def __init__(self, db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH):
        self.db_path = db_path
        self.schema_path = schema_path
        self.db: aiosqlite.Connection | None = None

        # {guild_id: {"enabled_cogs": list[str], "tod_channel": int | None, "tod_role": int | None}}
        self._guild_config_cache: dict[int, dict] = {}

        # {guild_id: {user_id: {"is_global": bool, "channels": set[int]}}}
        self._blacklist_cache: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self._init_schema()
        await self._load_guild_config_cache()
        await self._load_blacklist_cache()

    async def _init_schema(self):
        schema_sql = self.schema_path.read_text()
        await self.db.executescript(schema_sql)
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()

    # ------------------------------------------------------------------
    # guild_config
    # ------------------------------------------------------------------

    async def _load_guild_config_cache(self):
        self._guild_config_cache.clear()
        async with self.db.execute(
            "SELECT guild_id, enabled_cogs, tod_channel, tod_role FROM guild_config"
        ) as cursor:
            async for row in cursor:
                self._guild_config_cache[row["guild_id"]] = {
                    "enabled_cogs": json.loads(row["enabled_cogs"] or "[]"),
                    "tod_channel": row["tod_channel"],
                    "tod_role": row["tod_role"],
                }

    async def create_guild_config(self, guild_id: int):
        """Ensure a guild has a config row. Safe to call repeatedly (no-op if it exists)."""
        await self.db.execute(
            """INSERT INTO guild_config (guild_id, enabled_cogs, tod_channel, tod_role)
               VALUES (?, '[]', NULL, NULL)
               ON CONFLICT(guild_id) DO NOTHING""",
            (guild_id,)
        )
        await self.db.commit()

        if guild_id not in self._guild_config_cache:
            self._guild_config_cache[guild_id] = {
                "enabled_cogs": [],
                "tod_channel": None,
                "tod_role": None,
            }

    async def sync_guild_configs(self, guild_ids: list[int]):
        """Ensure every currently-joined guild has a config row. Call once on startup."""
        for guild_id in guild_ids:
            await self.create_guild_config(guild_id)

    def get_guild_config(self, guild_id: int) -> dict:
        return self._guild_config_cache.get(guild_id, {
            "enabled_cogs": [], "tod_channel": None, "tod_role": None
        })

    async def set_tod_channel(self, guild_id: int, channel_id: int | None):
        await self.db.execute(
            "UPDATE guild_config SET tod_channel = ? WHERE guild_id = ?",
            (channel_id, guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, {
            "enabled_cogs": [], "tod_channel": None, "tod_role": None
        })["tod_channel"] = channel_id

    async def set_tod_role(self, guild_id: int, role_id: int | None):
        await self.db.execute(
            "UPDATE guild_config SET tod_role = ? WHERE guild_id = ?",
            (role_id, guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, {
            "enabled_cogs": [], "tod_channel": None, "tod_role": None
        })["tod_role"] = role_id

    async def set_enabled_cogs(self, guild_id: int, enabled_cogs: list[str]):
        await self.db.execute(
            "UPDATE guild_config SET enabled_cogs = ? WHERE guild_id = ?",
            (json.dumps(enabled_cogs), guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, {
            "enabled_cogs": [], "tod_channel": None, "tod_role": None
        })["enabled_cogs"] = enabled_cogs

    def is_cog_enabled(self, guild_id: int, cog_name: str) -> bool:
        return cog_name in self.get_guild_config(guild_id)["enabled_cogs"]

    # ------------------------------------------------------------------
    # blacklist
    # ------------------------------------------------------------------

    async def _load_blacklist_cache(self):
        self._blacklist_cache.clear()
        async with self.db.execute(
            "SELECT guild_id, user_id, is_global, channels FROM blacklist"
        ) as cursor:
            async for row in cursor:
                guild = self._blacklist_cache.setdefault(row["guild_id"], {})
                guild[row["user_id"]] = {
                    "is_global": bool(row["is_global"]),
                    "channels": set(json.loads(row["channels"] or "[]")),
                }

    def is_blacklisted(self, guild_id: int, user_id: int, channel_id: int) -> bool:
        entry = self._blacklist_cache.get(guild_id, {}).get(user_id)
        if entry is None:
            return False
        if entry["is_global"]:
            return True
        return channel_id in entry["channels"]

    async def add_blacklist(
        self,
        guild_id: int,
        user_id: int,
        is_global: bool = False,
        channels: list[int] | None = None,
        reason: str | None = None,
    ):
        channels = channels or []
        await self.db.execute(
            """INSERT INTO blacklist (guild_id, user_id, is_global, channels, reason)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   is_global = excluded.is_global,
                   channels = excluded.channels,
                   reason = excluded.reason""",
            (guild_id, user_id, int(is_global), json.dumps(channels), reason)
        )
        await self.db.commit()

        guild = self._blacklist_cache.setdefault(guild_id, {})
        guild[user_id] = {"is_global": is_global, "channels": set(channels)}

    async def remove_blacklist(self, guild_id: int, user_id: int):
        await self.db.execute(
            "DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        await self.db.commit()
        self._blacklist_cache.get(guild_id, {}).pop(user_id, None)

    def get_blacklist_entry(self, guild_id: int, user_id: int) -> dict | None:
        return self._blacklist_cache.get(guild_id, {}).get(user_id)

    # ------------------------------------------------------------------
    # mod_logs
    # ------------------------------------------------------------------

    async def add_mod_log(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action: str,
        reason: str | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO mod_logs (guild_id, user_id, moderator_id, action, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, user_id, moderator_id, action, reason)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_mod_logs(self, guild_id: int, user_id: int, limit: int = 10) -> list[dict]:
        async with self.db.execute(
            """SELECT * FROM mod_logs
               WHERE guild_id = ? AND user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (guild_id, user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]