CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    enabled_cogs TEXT DEFAULT '[]',
    tod_channel INTEGER,
    tod_role INTEGER,
    enable_mod_logs BOOLEAN NOT NULL DEFAULT 0,
    mod_logs_channel INTEGER,
    is_locked BOOLEAN NOT NULL DEFAULT 0,
    is_hard_locked BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    type TEXT NOT NULL CHECK (type IN ('truth', 'dare')),
    content TEXT NOT NULL,
    added_by INTEGER,
    is_banned BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prompts_guild_type
    ON prompts (guild_id, type, is_banned);

CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    is_global BOOLEAN NOT NULL DEFAULT 0,
    channels TEXT DEFAULT '[]',   -- JSON array of channel_ids, only used when is_global = 0
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS mod_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('warn', 'mute', 'kick', 'ban', 'blacklist', 'whitelist', 'unmute', 'unban')),
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_modlogs_guild_user
    ON mod_logs (guild_id, user_id);