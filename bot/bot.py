import asyncio
from pathlib import Path

import discord
from discord.ext import commands

from bot.resources.constants import BOT_TOKEN, PREFIX

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        if COGS_DIR.exists():
            for file in COGS_DIR.glob("*.py"):
                if file.name == "__init__.py":
                    continue

                ext_name = f"bot.cogs.{file.stem}"
                try:
                    await self.load_extension(ext_name)
                    print(f"[COG] Loaded: {file.name}")
                except Exception as e:
                    print(f"[COG] Failed: {file.name} -> {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Bot is online.")

bot = Bot()

async def main():
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())