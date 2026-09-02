import json
import random
import aiosqlite
from pathlib import Path

from bot.resources.constants import DB_PATH, SCHEMA_PATH, TOD_TRUTHS, TOD_DARES


class Connector:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        schema_path: Path = SCHEMA_PATH,
        truths_path: Path = TOD_TRUTHS,
        dares_path: Path = TOD_DARES,
    ):
        self.db_path = db_path
        self.schema_path = schema_path
        self.truths_path = truths_path
        self.dares_path = dares_path
        self.db: aiosqlite.Connection | None = None

        # {guild_id: {"enabled_cogs": list[str], "tod_channel": int | None,
        #             "tod_role": int | None, "enable_mod_logs": bool,
        #             "mod_logs_channel": int | None}}
        self._guild_config_cache: dict[int, dict] = {}

        # {guild_id: {user_id: {"is_global": bool, "channels": set[int]}}}
        self._blacklist_cache: dict[int, dict] = {}

        # {guild_id_or_None: {"truth": [{"id", "content", "is_banned"}, ...],
        #                      "dare":  [...]}}
        # guild_id = None holds the default/global pool seeded from JSON
        self._prompts_cache: dict[int | None, dict[str, list[dict]]] = {}

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
        await self._sync_prompts_from_json()
        await self._load_prompts_cache()

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

    def _default_guild_config(self) -> dict:
        return {
            "enabled_cogs": [],
            "tod_channel": None,
            "tod_role": None,
            "enable_mod_logs": False,
            "mod_logs_channel": None,
        }

    async def _load_guild_config_cache(self):
        self._guild_config_cache.clear()
        async with self.db.execute(
            """SELECT guild_id, enabled_cogs, tod_channel, tod_role,
                      enable_mod_logs, mod_logs_channel
               FROM guild_config"""
        ) as cursor:
            async for row in cursor:
                self._guild_config_cache[row["guild_id"]] = {
                    "enabled_cogs": json.loads(row["enabled_cogs"] or "[]"),
                    "tod_channel": row["tod_channel"],
                    "tod_role": row["tod_role"],
                    "enable_mod_logs": bool(row["enable_mod_logs"]),
                    "mod_logs_channel": row["mod_logs_channel"],
                }

    async def create_guild_config(self, guild_id: int):
        """Ensure a guild has a config row. Safe to call repeatedly (no-op if it exists)."""
        await self.db.execute(
            """INSERT INTO guild_config
                   (guild_id, enabled_cogs, tod_channel, tod_role, enable_mod_logs, mod_logs_channel)
               VALUES (?, '[]', NULL, NULL, 0, NULL)
               ON CONFLICT(guild_id) DO NOTHING""",
            (guild_id,)
        )
        await self.db.commit()

        if guild_id not in self._guild_config_cache:
            self._guild_config_cache[guild_id] = self._default_guild_config()

    async def sync_guild_configs(self, guild_ids: list[int]):
        """Ensure every currently-joined guild has a config row. Call once on startup."""
        for guild_id in guild_ids:
            await self.create_guild_config(guild_id)

    def get_guild_config(self, guild_id: int) -> dict:
        return self._guild_config_cache.get(guild_id, self._default_guild_config())

    async def set_tod_channel(self, guild_id: int, channel_id: int | None):
        await self.db.execute(
            "UPDATE guild_config SET tod_channel = ? WHERE guild_id = ?",
            (channel_id, guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["tod_channel"] = channel_id

    async def set_tod_role(self, guild_id: int, role_id: int | None):
        await self.db.execute(
            "UPDATE guild_config SET tod_role = ? WHERE guild_id = ?",
            (role_id, guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["tod_role"] = role_id

    async def set_enabled_cogs(self, guild_id: int, enabled_cogs: list[str]):
        await self.db.execute(
            "UPDATE guild_config SET enabled_cogs = ? WHERE guild_id = ?",
            (json.dumps(enabled_cogs), guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["enabled_cogs"] = enabled_cogs

    async def set_enable_mod_logs(self, guild_id: int, enabled: bool):
        await self.db.execute(
            "UPDATE guild_config SET enable_mod_logs = ? WHERE guild_id = ?",
            (int(enabled), guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["enable_mod_logs"] = enabled

    async def set_mod_logs_channel(self, guild_id: int, channel_id: int | None):
        await self.db.execute(
            "UPDATE guild_config SET mod_logs_channel = ? WHERE guild_id = ?",
            (channel_id, guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["mod_logs_channel"] = channel_id

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

    # ------------------------------------------------------------------
    # prompts
    # ------------------------------------------------------------------

    async def _sync_prompts_from_json(self):
        """
        On every startup: read truths.json/dares.json, and insert any content
        not already present in the default pool (guild_id IS NULL). Existing
        DB entries (including bans) are never touched or removed here.
        """
        truths = json.loads(self.truths_path.read_text())
        dares = json.loads(self.dares_path.read_text())

        for content_list, ptype in [(truths, "truth"), (dares, "dare")]:
            async with self.db.execute(
                "SELECT content FROM prompts WHERE guild_id IS NULL AND type = ?",
                (ptype,)
            ) as cursor:
                existing = {row["content"] async for row in cursor}

            new_entries = [c for c in content_list if c not in existing]

            if new_entries:
                await self.db.executemany(
                    """INSERT INTO prompts (guild_id, type, content, added_by, is_banned)
                       VALUES (NULL, ?, ?, NULL, 0)""",
                    [(ptype, content) for content in new_entries]
                )
                await self.db.commit()

    async def _load_prompts_cache(self):
        self._prompts_cache.clear()
        async with self.db.execute(
            "SELECT id, guild_id, type, content, is_banned FROM prompts"
        ) as cursor:
            async for row in cursor:
                bucket = self._prompts_cache.setdefault(row["guild_id"], {"truth": [], "dare": []})
                bucket[row["type"]].append({
                    "id": row["id"],
                    "content": row["content"],
                    "is_banned": bool(row["is_banned"]),
                })

    def get_prompt(self, guild_id: int, prompt_type: str, exclude: set[str] | None = None) -> str | None:
        """
        Random non-banned prompt from the default pool + this guild's customs.
        `exclude` lets a game avoid repeats (e.g. last_prompts). If everything
        available is excluded, falls back to ignoring the exclude set rather
        than returning None.
        """
        exclude = exclude or set()

        def pool(skip_exclude: bool = False) -> list[str]:
            result = []
            for gid in (None, guild_id):
                for p in self._prompts_cache.get(gid, {}).get(prompt_type, []):
                    if p["is_banned"]:
                        continue
                    if not skip_exclude and p["content"] in exclude:
                        continue
                    result.append(p["content"])
            return result

        candidates = pool()
        if not candidates:
            candidates = pool(skip_exclude=True)

        return random.choice(candidates) if candidates else None

    async def add_prompt(
        self,
        guild_id: int | None,
        prompt_type: str,
        content: str,
        added_by: int | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO prompts (guild_id, type, content, added_by, is_banned)
               VALUES (?, ?, ?, ?, 0)""",
            (guild_id, prompt_type, content, added_by)
        )
        await self.db.commit()
        prompt_id = cursor.lastrowid

        bucket = self._prompts_cache.setdefault(guild_id, {"truth": [], "dare": []})
        bucket[prompt_type].append({"id": prompt_id, "content": content, "is_banned": False})
        return prompt_id

    def _locate_prompt(self, prompt_id: int) -> dict | None:
        for types in self._prompts_cache.values():
            for plist in types.values():
                for p in plist:
                    if p["id"] == prompt_id:
                        return p
        return None

    async def ban_prompt(self, prompt_id: int):
        await self.db.execute("UPDATE prompts SET is_banned = 1 WHERE id = ?", (prompt_id,))
        await self.db.commit()
        entry = self._locate_prompt(prompt_id)
        if entry:
            entry["is_banned"] = True

    async def unban_prompt(self, prompt_id: int):
        await self.db.execute("UPDATE prompts SET is_banned = 0 WHERE id = ?", (prompt_id,))
        await self.db.commit()
        entry = self._locate_prompt(prompt_id)
        if entry:
            entry["is_banned"] = False

    async def delete_prompt(self, prompt_id: int):
        await self.db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        await self.db.commit()
        for types in self._prompts_cache.values():
            for ptype, plist in types.items():
                types[ptype] = [p for p in plist if p["id"] != prompt_id]

    def list_prompts(self, guild_id: int, prompt_type: str, include_banned: bool = False) -> list[dict]:
        combined = (
            self._prompts_cache.get(None, {}).get(prompt_type, [])
            + self._prompts_cache.get(guild_id, {}).get(prompt_type, [])
        )
        if not include_banned:
            combined = [p for p in combined if not p["is_banned"]]
        return combined