# default events cog, always enabled
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))