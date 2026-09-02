import asyncio
from pathlib import Path

import discord
from discord.ext import commands

from bot.resources.constants import BOT_TOKEN, PREFIX
from bot.database.connector import Connector
from bot.logger import Logger

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

log = Logger()

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None
        )
        self.connector = Connector()
        self._synced_guilds = False

    async def setup_hook(self):
        await self.connector.connect()
        log.cog_load("database connector")

        if COGS_DIR.exists():
            for file in COGS_DIR.glob("*.py"):
                if file.name == "__init__.py":
                    continue

                ext_name = f"bot.cogs.{file.stem}"
                try:
                    await self.load_extension(ext_name)
                    log.cog_load(ext_name)
                except Exception as e:
                    log.cog_load(ext_name, False, f"Failed to Load Cog: {e}")

    async def on_ready(self):
        if not self._synced_guilds:
            await self.connector.sync_guild_configs([g.id for g in self.guilds])
            self._synced_guilds = True
        log.bot_start(str(self.user), len(self.guilds))

    async def close(self):
        await self.connector.close()
        await super().close()

bot = Bot()

async def main():
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())