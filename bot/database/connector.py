import aiosqlite
from pathlib import Path

from bot.resources.constants import DB_PATH, SCHEMA_PATH

class Connector:
    def __init__(self, db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH):
        self.db_path = db_path
        self.schema_path = schema_path
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self._init_schema()

    async def _init_schema(self):
        schema_sql = self.schema_path.read_text()
        await self.db.executescript(schema_sql)
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()
