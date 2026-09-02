# default events cog, always enabled
import discord
from discord.ext import commands
from bot.logger import Logger

log = Logger()

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        log.command(
            user=str(ctx.author),
            command_name=ctx.command.qualified_name,
            guild=ctx.guild.name
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.bot.connector.create_guild_config(guild.id)
        log.info(f"Joined guild {guild.name} ({guild.id}), config initialized")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        log.warning(f"Removed from guild {guild.name} ({guild.id})")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))