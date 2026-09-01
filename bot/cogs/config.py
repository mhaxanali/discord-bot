# default config cog, always enabled
from discord.ext import commands
from bot.logger import Logger

from discord import Embed, Colour

log = Logger()

class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="config")
    async def config(self, ctx):
        embed = Embed(
            title="Config Commands",
            description="This cog contains commands to edit the server-wide config",
            colour=Colour.blue()
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))