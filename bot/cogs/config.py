# default config cog, always enabled
from discord.ext import commands
from discord import Embed, Colour

from bot.resources.constants import BOT_OWNER_ID, COG_METADATA, DEFAULT_COGS
from bot.logger import Logger

log = Logger()

# subcommands exempt from lock/hard-lock gating in cog_check
LOCK_EXEMPT = {
    "config", "config help", "config cogs list",
    "config lock", "config lock hard",
    "config unlock", "config unlock hard",
}


def error_embed(description: str) -> Embed:
    return Embed(title="Error", description=description, colour=Colour.red())


def success_embed(description: str) -> Embed:
    return Embed(title="Success", description=description, colour=Colour.green())


def missing_bot_permissions(guild, cog_name: str) -> list[str]:
    """Returns human-readable names of permissions the bot lacks for the given cog."""
    required = COG_METADATA.get(cog_name, {}).get("required_permissions", [])
    bot_perms = guild.me.guild_permissions
    return [
        perm.replace("_", " ").title()
        for perm in required
        if not getattr(bot_perms, perm, False)
    ]


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Applies lock/hard-lock gating to every command except read-only and lock/unlock themselves."""
        if ctx.guild is None:
            return False

        if ctx.author.id == BOT_OWNER_ID:
            return True

        if ctx.command.qualified_name in LOCK_EXEMPT:
            return True

        cfg = self.bot.connector.get_guild_config(ctx.guild.id)

        if cfg["is_hard_locked"]:
            await ctx.send(embed=error_embed(
                "This server's config has been hard-locked by the bot owner."
            ))
            return False

        if cfg["is_locked"] and ctx.author.id != ctx.guild.owner_id:
            await ctx.send(embed=error_embed(
                "This server's config is locked. Only the server owner can make changes."
            ))
            return False

        return True

    # ------------------------------------------------------------------
    # root
    # ------------------------------------------------------------------

    @commands.group(name="config", invoke_without_command=True)
    async def config(self, ctx: commands.Context) -> None:
        """Shows the current server configuration."""
        cfg = self.bot.connector.get_guild_config(ctx.guild.id)

        tod_channel = f"<#{cfg['tod_channel']}>" if cfg["tod_channel"] else "Not set"
        tod_role = f"<@&{cfg['tod_role']}>" if cfg["tod_role"] else "Not set"
        modlogs_channel = f"<#{cfg['mod_logs_channel']}>" if cfg["mod_logs_channel"] else "Not set"
        modlogs_enabled = "✅" if cfg["enable_mod_logs"] else "❌"

        if cfg["is_hard_locked"]:
            lock_status = "🔒 Hard Locked"
        elif cfg["is_locked"]:
            lock_status = "🔒 Locked"
        else:
            lock_status = "🔓 Unlocked"

        enabled_cogs = ", ".join(f"`{c}`" for c in cfg["enabled_cogs"]) or "None"

        embed = Embed(title="Server Configuration", colour=Colour.blue())
        embed.add_field(name="Lock Status", value=lock_status, inline=False)
        embed.add_field(name="TOD Channel", value=tod_channel, inline=True)
        embed.add_field(name="TOD Role", value=tod_role, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Mod Logs Channel", value=modlogs_channel, inline=True)
        embed.add_field(name="Mod Logs Enabled", value=modlogs_enabled, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Enabled Cogs", value=enabled_cogs, inline=False)
        embed.set_footer(text="Run +config help for a list of commands.")

        await ctx.send(embed=embed)

    @config.command(name="help")
    async def config_help(self, ctx: commands.Context) -> None:
        """Lists all config commands with a short description."""
        lines = []
        for command in sorted(self.config.walk_commands(), key=lambda c: c.qualified_name):
            doc = (command.help or "No description.").split("\n")[0]
            lines.append(f"`+{command.qualified_name}` - {doc}")

        embed = Embed(title="Config Help", description="\n".join(lines), colour=Colour.blue())
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # cogs
    # ------------------------------------------------------------------

    @config.group(name="cogs", invoke_without_command=True)
    async def config_cogs(self, ctx: commands.Context) -> None:
        """Shows cog-related subcommands."""
        await ctx.send_help(ctx.command)

    @config_cogs.command(name="list")
    async def cogs_list(self, ctx: commands.Context) -> None:
        """Lists all available cogs and whether they're enabled here."""
        cfg = self.bot.connector.get_guild_config(ctx.guild.id)
        enabled = set(cfg["enabled_cogs"]) | DEFAULT_COGS

        lines = []
        for name in sorted(COG_METADATA.keys()):
            mark = "✅" if name in enabled else "❌"
            tag = " *(default)*" if name in DEFAULT_COGS else ""
            lines.append(f"{mark} `{name}`{tag}")

        embed = Embed(title="Available Cogs", description="\n".join(lines), colour=Colour.blue())
        await ctx.send(embed=embed)

    @config_cogs.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def cogs_enable(self, ctx: commands.Context, cog_name: str) -> None:
        """Enables a cog for this server."""
        cog_name = cog_name.lower()

        if cog_name not in COG_METADATA:
            await ctx.send(embed=error_embed(f"Unknown cog `{cog_name}`."))
            return

        if cog_name in DEFAULT_COGS:
            await ctx.send(embed=error_embed(f"`{cog_name}` is a default cog and is always enabled."))
            return

        cfg = self.bot.connector.get_guild_config(ctx.guild.id)
        if cog_name in cfg["enabled_cogs"]:
            await ctx.send(embed=error_embed(f"`{cog_name}` is already enabled."))
            return

        missing = missing_bot_permissions(ctx.guild, cog_name)
        if missing:
            await ctx.send(embed=error_embed(
                f"Bot is missing required permissions for `{cog_name}`: "
                + ", ".join(missing)
            ))
            return

        updated = cfg["enabled_cogs"] + [cog_name]
        await self.bot.connector.set_enabled_cogs(ctx.guild.id, updated)
        await ctx.send(embed=success_embed(f"`{cog_name}` enabled."))

    @config_cogs.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def cogs_disable(self, ctx: commands.Context, cog_name: str) -> None:
        """Disables a cog for this server."""
        cog_name = cog_name.lower()

        if cog_name in DEFAULT_COGS:
            await ctx.send(embed=error_embed(f"`{cog_name}` is a default cog and cannot be disabled."))
            return

        cfg = self.bot.connector.get_guild_config(ctx.guild.id)
        if cog_name not in cfg["enabled_cogs"]:
            await ctx.send(embed=error_embed(f"`{cog_name}` is not enabled."))
            return

        updated = [c for c in cfg["enabled_cogs"] if c != cog_name]
        await self.bot.connector.set_enabled_cogs(ctx.guild.id, updated)
        await ctx.send(embed=success_embed(f"`{cog_name}` disabled."))

    # ------------------------------------------------------------------
    # tod
    # ------------------------------------------------------------------

    @config.group(name="tod", invoke_without_command=True)
    async def config_tod(self, ctx: commands.Context) -> None:
        """Shows TOD-related config subcommands."""
        await ctx.send_help(ctx.command)

    @config_tod.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def tod_channel(self, ctx: commands.Context, *, channel: str = None) -> None:
        """Sets or resets the channel TOD games are restricted to."""
        if channel is None:
            await ctx.send(embed=error_embed("Provide a channel mention/ID, or `reset` to clear it."))
            return

        if channel.lower() == "reset":
            await self.bot.connector.set_tod_channel(ctx.guild.id, None)
            await ctx.send(embed=success_embed("TOD channel reset. Game usable in any channel."))
            return

        try:
            resolved = await commands.TextChannelConverter().convert(ctx, channel)
        except commands.ChannelNotFound:
            await ctx.send(embed=error_embed("Could not find that channel."))
            return

        await self.bot.connector.set_tod_channel(ctx.guild.id, resolved.id)
        await ctx.send(embed=success_embed(f"TOD channel set to {resolved.mention}."))

    @config_tod.command(name="role")
    @commands.has_permissions(manage_guild=True)
    async def tod_role(self, ctx: commands.Context, *, role: str = None) -> None:
        """Sets or resets the role pinged when a TOD round starts."""
        if role is None:
            await ctx.send(embed=error_embed("Provide a role mention/ID, or `reset` to clear it."))
            return

        if role.lower() == "reset":
            await self.bot.connector.set_tod_role(ctx.guild.id, None)
            await ctx.send(embed=success_embed("TOD role reset. No role will be pinged."))
            return

        try:
            resolved = await commands.RoleConverter().convert(ctx, role)
        except commands.RoleNotFound:
            await ctx.send(embed=error_embed("Could not find that role."))
            return

        await self.bot.connector.set_tod_role(ctx.guild.id, resolved.id)
        await ctx.send(embed=success_embed(f"TOD role set to {resolved.mention}."))

    # ------------------------------------------------------------------
    # modlogs
    # ------------------------------------------------------------------

    @config.group(name="modlogs", invoke_without_command=True)
    async def config_modlogs(self, ctx: commands.Context) -> None:
        """Shows modlog-related config subcommands."""
        await ctx.send_help(ctx.command)

    @config_modlogs.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def modlogs_channel(self, ctx: commands.Context, *, channel: str = None) -> None:
        """Sets or resets the channel moderation actions are logged to."""
        if channel is None:
            await ctx.send(embed=error_embed("Provide a channel mention/ID, or `reset` to clear it."))
            return

        if channel.lower() == "reset":
            await self.bot.connector.set_mod_logs_channel(ctx.guild.id, None)
            await ctx.send(embed=success_embed("Mod logs channel reset."))
            return

        try:
            resolved = await commands.TextChannelConverter().convert(ctx, channel)
        except commands.ChannelNotFound:
            await ctx.send(embed=error_embed("Could not find that channel."))
            return

        await self.bot.connector.set_mod_logs_channel(ctx.guild.id, resolved.id)
        await ctx.send(embed=success_embed(f"Mod logs channel set to {resolved.mention}."))

    @config_modlogs.command(name="enable")
    @commands.has_permissions(manage_guild=True)
    async def modlogs_enable(self, ctx: commands.Context) -> None:
        """Enables mod log posting (requires a channel to be set first)."""
        cfg = self.bot.connector.get_guild_config(ctx.guild.id)
        if cfg["mod_logs_channel"] is None:
            await ctx.send(embed=error_embed(
                "Set a mod logs channel first with `+config modlogs channel`."
            ))
            return

        await self.bot.connector.set_enable_mod_logs(ctx.guild.id, True)
        await ctx.send(embed=success_embed("Mod logs enabled."))

    @config_modlogs.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def modlogs_disable(self, ctx: commands.Context) -> None:
        """Disables mod log posting."""
        await self.bot.connector.set_enable_mod_logs(ctx.guild.id, False)
        await ctx.send(embed=success_embed("Mod logs disabled."))

    # ------------------------------------------------------------------
    # lock / unlock
    # ------------------------------------------------------------------

    @config.group(name="lock", invoke_without_command=True)
    async def config_lock(self, ctx: commands.Context) -> None:
        """Locks the config so only the server owner can edit it."""
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != BOT_OWNER_ID:
            await ctx.send(embed=error_embed("Only the server owner can lock the config."))
            return

        await self.bot.connector.set_locked(ctx.guild.id, True)
        await ctx.send(embed=success_embed("Config locked. Only the server owner can make changes."))

    @config_lock.command(name="hard")
    async def config_lock_hard(self, ctx: commands.Context) -> None:
        """Hard-locks the config so only the bot owner can edit it."""
        if ctx.author.id != BOT_OWNER_ID:
            await ctx.send(embed=error_embed("Only the bot owner can hard-lock a config."))
            return

        await self.bot.connector.set_hard_locked(ctx.guild.id, True)
        await ctx.send(embed=success_embed("Config hard-locked. Only the bot owner can make changes now."))

    @config.group(name="unlock", invoke_without_command=True)
    async def config_unlock(self, ctx: commands.Context) -> None:
        """Removes the soft lock on the config."""
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != BOT_OWNER_ID:
            await ctx.send(embed=error_embed("Only the server owner can unlock the config."))
            return

        await self.bot.connector.set_locked(ctx.guild.id, False)
        await ctx.send(embed=success_embed("Config unlocked."))

    @config_unlock.command(name="hard")
    async def config_unlock_hard(self, ctx: commands.Context) -> None:
        """Removes the hard lock on the config (bot owner only)."""
        if ctx.author.id != BOT_OWNER_ID:
            await ctx.send(embed=error_embed("Only the bot owner can remove a hard lock."))
            return

        await self.bot.connector.set_hard_locked(ctx.guild.id, False)
        await ctx.send(embed=success_embed("Hard lock removed."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))