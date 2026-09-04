import re
import json
import random
import sqlite3
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

        self._guild_config_cache: dict[int, dict] = {}
        self._blacklist_cache: dict[int, dict] = {}

        # {guild_id_or_None: {"truth": [{"id", "content"}, ...], "dare": [...]}}
        self._prompts_cache: dict[int | None, dict[str, list[dict]]] = {}

        # {guild_id: {prompt_id, prompt_id, ...}}
        self._prompt_bans_cache: dict[int, set[int]] = {}

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
        await self._run_migrations()
        await self._load_guild_config_cache()
        await self._load_blacklist_cache()
        await self._sync_prompts_from_json()
        await self._load_prompts_cache()
        await self._load_prompt_bans_cache()

    async def _init_schema(self):
        schema_sql = self.schema_path.read_text()
        await self.db.executescript(schema_sql)
        await self.db.commit()

    async def _run_migrations(self):
        await self.db.execute(
            """CREATE TABLE IF NOT EXISTS _schema_migrations (
                   filename TEXT PRIMARY KEY,
                   applied_at TEXT DEFAULT (datetime('now'))
               )"""
        )
        await self.db.commit()

        migrations_dir = self.schema_path.parent / "migrations"
        if not migrations_dir.exists():
            return

        async with self.db.execute("SELECT filename FROM _schema_migrations") as cursor:
            applied = {row["filename"] async for row in cursor}

        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in applied:
                continue

            try:
                await self.db.executescript(path.read_text())
            except sqlite3.OperationalError:
                # Target state already satisfied (e.g. fresh DB via schema.sql) — safe to skip.
                pass

            await self.db.execute(
                "INSERT OR IGNORE INTO _schema_migrations (filename) VALUES (?)",
                (path.name,)
            )
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
            "is_locked": False,
            "is_hard_locked": False,
        }

    async def _load_guild_config_cache(self):
        self._guild_config_cache.clear()
        async with self.db.execute(
            """SELECT guild_id, enabled_cogs, tod_channel, tod_role,
                      enable_mod_logs, mod_logs_channel, is_locked, is_hard_locked
               FROM guild_config"""
        ) as cursor:
            async for row in cursor:
                self._guild_config_cache[row["guild_id"]] = {
                    "enabled_cogs": json.loads(row["enabled_cogs"] or "[]"),
                    "tod_channel": row["tod_channel"],
                    "tod_role": row["tod_role"],
                    "enable_mod_logs": bool(row["enable_mod_logs"]),
                    "mod_logs_channel": row["mod_logs_channel"],
                    "is_locked": bool(row["is_locked"]),
                    "is_hard_locked": bool(row["is_hard_locked"]),
                }

    async def create_guild_config(self, guild_id: int):
        await self.db.execute(
            """INSERT INTO guild_config
                   (guild_id, enabled_cogs, tod_channel, tod_role,
                    enable_mod_logs, mod_logs_channel, is_locked, is_hard_locked)
               VALUES (?, '[]', NULL, NULL, 0, NULL, 0, 0)
               ON CONFLICT(guild_id) DO NOTHING""",
            (guild_id,)
        )
        await self.db.commit()

        if guild_id not in self._guild_config_cache:
            self._guild_config_cache[guild_id] = self._default_guild_config()

    async def sync_guild_configs(self, guild_ids: list[int]):
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

    async def set_locked(self, guild_id: int, locked: bool):
        await self.db.execute(
            "UPDATE guild_config SET is_locked = ? WHERE guild_id = ?",
            (int(locked), guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["is_locked"] = locked

    async def set_hard_locked(self, guild_id: int, hard_locked: bool):
        await self.db.execute(
            "UPDATE guild_config SET is_hard_locked = ? WHERE guild_id = ?",
            (int(hard_locked), guild_id)
        )
        await self.db.commit()
        self._guild_config_cache.setdefault(guild_id, self._default_guild_config())["is_hard_locked"] = hard_locked

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

    @staticmethod
    def _normalize_prompt(content: str, prompt_type: str) -> str:
        """Collapses whitespace, capitalizes the first letter, and ensures
        proper terminal punctuation (? for truths, . for dares) unless the
        content already ends in ./!/?."""
        content = re.sub(r"\s+", " ", content.strip())
        if content:
            content = content[0].upper() + content[1:]
        if content and content[-1] not in ".!?":
            content += "?" if prompt_type == "truth" else "."
        return content

    async def _sync_prompts_from_json(self):
        """
        On every startup: read truths.json/dares.json (normalized), and insert
        any content not already present in the default pool (guild_id IS NULL).
        Existing DB entries are never touched or removed here.
        """
        raw_truths = json.loads(self.truths_path.read_text())
        raw_dares = json.loads(self.dares_path.read_text())

        for content_list, ptype in [(raw_truths, "truth"), (raw_dares, "dare")]:
            normalized = [self._normalize_prompt(c, ptype) for c in content_list]

            async with self.db.execute(
                "SELECT content FROM prompts WHERE guild_id IS NULL AND type = ?",
                (ptype,)
            ) as cursor:
                existing = {row["content"] async for row in cursor}

            new_entries = [c for c in normalized if c not in existing]

            if new_entries:
                await self.db.executemany(
                    """INSERT INTO prompts (guild_id, type, content, added_by)
                       VALUES (NULL, ?, ?, NULL)""",
                    [(ptype, content) for content in new_entries]
                )
                await self.db.commit()

    async def _load_prompts_cache(self):
        self._prompts_cache.clear()
        async with self.db.execute(
            "SELECT id, guild_id, type, content FROM prompts"
        ) as cursor:
            async for row in cursor:
                bucket = self._prompts_cache.setdefault(row["guild_id"], {"truth": [], "dare": []})
                bucket[row["type"]].append({"id": row["id"], "content": row["content"]})

    async def _load_prompt_bans_cache(self):
        self._prompt_bans_cache.clear()
        async with self.db.execute("SELECT guild_id, prompt_id FROM prompt_bans") as cursor:
            async for row in cursor:
                self._prompt_bans_cache.setdefault(row["guild_id"], set()).add(row["prompt_id"])

    def get_prompt(self, guild_id: int, prompt_type: str, exclude_ids: set[int] | None = None) -> dict | None:
        """
        Random non-banned (for this guild) prompt from the default pool + this
        guild's customs. `exclude_ids` lets a game avoid repeats. If everything
        available is excluded, falls back to ignoring the exclude set.
        Returns {"id": int, "content": str} or None if nothing is available.
        """
        exclude_ids = exclude_ids or set()
        banned = self._prompt_bans_cache.get(guild_id, set())

        def pool(skip_exclude: bool = False) -> list[dict]:
            result = []
            for gid in (None, guild_id):
                for p in self._prompts_cache.get(gid, {}).get(prompt_type, []):
                    if p["id"] in banned:
                        continue
                    if not skip_exclude and p["id"] in exclude_ids:
                        continue
                    result.append(p)
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
        content = self._normalize_prompt(content, prompt_type)

        cursor = await self.db.execute(
            """INSERT INTO prompts (guild_id, type, content, added_by)
               VALUES (?, ?, ?, ?)""",
            (guild_id, prompt_type, content, added_by)
        )
        await self.db.commit()
        prompt_id = cursor.lastrowid

        bucket = self._prompts_cache.setdefault(guild_id, {"truth": [], "dare": []})
        bucket[prompt_type].append({"id": prompt_id, "content": content})
        return prompt_id

    def get_prompt_by_id(self, prompt_id: int) -> dict | None:
        """Returns {"id", "content", "guild_id", "type"} or None if not found."""
        for gid, types in self._prompts_cache.items():
            for ptype, plist in types.items():
                for p in plist:
                    if p["id"] == prompt_id:
                        return {"id": p["id"], "content": p["content"], "guild_id": gid, "type": ptype}
        return None

    def is_prompt_visible_to_guild(self, guild_id: int, prompt_id: int) -> bool:
        prompt = self.get_prompt_by_id(prompt_id)
        if prompt is None:
            return False
        return prompt["guild_id"] is None or prompt["guild_id"] == guild_id

    def is_prompt_banned(self, guild_id: int, prompt_id: int) -> bool:
        return prompt_id in self._prompt_bans_cache.get(guild_id, set())

    async def ban_prompt(self, guild_id: int, prompt_id: int, banned_by: int | None = None):
        await self.db.execute(
            """INSERT INTO prompt_bans (guild_id, prompt_id, banned_by)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id, prompt_id) DO NOTHING""",
            (guild_id, prompt_id, banned_by)
        )
        await self.db.commit()
        self._prompt_bans_cache.setdefault(guild_id, set()).add(prompt_id)

    async def unban_prompt(self, guild_id: int, prompt_id: int):
        await self.db.execute(
            "DELETE FROM prompt_bans WHERE guild_id = ? AND prompt_id = ?",
            (guild_id, prompt_id)
        )
        await self.db.commit()
        self._prompt_bans_cache.get(guild_id, set()).discard(prompt_id)

    async def delete_prompt(self, prompt_id: int):
        await self.db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        await self.db.commit()

        for types in self._prompts_cache.values():
            for ptype, plist in types.items():
                types[ptype] = [p for p in plist if p["id"] != prompt_id]

        for banned_set in self._prompt_bans_cache.values():
            banned_set.discard(prompt_id)

    def list_default_prompts(self, prompt_type: str) -> list[dict]:
        return list(self._prompts_cache.get(None, {}).get(prompt_type, []))

    def list_guild_prompts(self, guild_id: int, prompt_type: str) -> list[dict]:
        return list(self._prompts_cache.get(guild_id, {}).get(prompt_type, []))