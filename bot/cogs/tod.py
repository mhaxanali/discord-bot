from discord.ext import commands
from typing import Callable
import discord
import random
import asyncio


class TOD(commands.Cog):
    """Contains the Truth and Dare game and relevant commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, dict] = {}  # guild_id -> game state

    # ------------------------------------------------------------------
    # embeds / small helpers
    # ------------------------------------------------------------------

    def build_lobby_embed(self, guild_id: int, title: str = "TOD Lobby") -> discord.Embed:
        game = self.games[guild_id]
        players_list = "\n".join(f"<@{pid}>" for pid in game["players"])

        description = (
            f"Session Owner: <@{game['session_owner']}>\n"
            f"Players:\n{players_list if players_list else 'No players yet.'}\n\n"
            f"Run `+tod help` for commands."
        )

        return discord.Embed(title=title, description=description, colour=discord.Colour.blue())

    def get_prompt(self, guild_id: int, choice: str) -> dict | None:
        """Retrieves a prompt dict {'id','content'} for this guild, avoiding recent repeats."""
        game = self.games[guild_id]
        prompt = self.bot.connector.get_prompt(guild_id, choice, exclude_ids=set(game["last_prompts"]))

        if prompt is None:
            return None

        if len(game["last_prompts"]) >= 25:
            game["last_prompts"].pop(0)
        game["last_prompts"].append(prompt["id"])

        return prompt

    def check_message(self, guild_id: int, tod_channel: int | None, pid: int) -> Callable:
        def inner(msg: discord.Message) -> bool:
            if msg.guild is None or msg.guild.id != guild_id:
                return False
            if tod_channel is not None and msg.channel.id != tod_channel:
                return False
            return (
                msg.author.id == pid and
                msg.content.lower() in ["truth", "dare", "t", "d"]
            )
        return inner

    async def run_turn(self, ctx: commands.Context, player: int) -> None:
        guild_id = ctx.guild.id
        game = self.games[guild_id]
        cfg = self.bot.connector.get_guild_config(guild_id)

        await ctx.send(f"<@{player}> It's your turn. Truth or Dare (30s).")

        try:
            game["waiting_for_response"] = True
            msg = await self.bot.wait_for(
                "message",
                check=self.check_message(guild_id, cfg["tod_channel"], player),
                timeout=30
            )

            if guild_id not in self.games:
                return

            choice = "truth" if msg.content.lower() in ("t", "truth") else "dare"

            owner_member = ctx.guild.get_member(game["session_owner"])
            player_member = ctx.guild.get_member(player)

            prompt = self.get_prompt(guild_id, choice)
            if prompt is None:
                await ctx.send("No prompts are available right now.")
                return

            embed = discord.Embed(colour=discord.Colour.blue(), title=prompt["content"])

            embed.set_author(
                name=player_member.name if player_member else "Player",
                icon_url=player_member.display_avatar.url if player_member else None
            )

            embed.set_footer(
                text=(
                    f"ID: #{prompt['id']} | TYPE: {choice.upper()} | "
                    f"Session Owner: {owner_member.name if owner_member else 'Unknown'}"
                )
            )

            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send(f"<@{player}> took too long.")
        finally:
            if guild_id in self.games:
                self.games[guild_id]["waiting_for_response"] = False
        return

    def remove_player_turn(self, guild_id: int, user_id: int) -> None:
        game = self.games[guild_id]
        if "turn_order" in game:
            if user_id in game["turn_order"]:
                removed_index = game["turn_order"].index(user_id)
                game["turn_order"].remove(user_id)

                if game["turn_order"]:
                    if removed_index <= game["turn_index"]:
                        game["turn_index"] -= 1
                    game["turn_index"] %= len(game["turn_order"])
                else:
                    game["turn_index"] = 0
        return

    # ------------------------------------------------------------------
    # pagination
    # ------------------------------------------------------------------

    def _paginate_prompt_group(self, title: str, prompts: list[dict], guild_id: int) -> list[discord.Embed]:
        if not prompts:
            return []

        per_page = 10
        total_pages = (len(prompts) - 1) // per_page + 1
        pages = []

        for page_num in range(total_pages):
            chunk = prompts[page_num * per_page: page_num * per_page + per_page]
            lines = []
            for p in chunk:
                banned = self.bot.connector.is_prompt_banned(guild_id, p["id"])
                mark = "❌" if banned else "✅"
                lines.append(f"{mark} `#{p['id']}` {p['content']}")

            pages.append(discord.Embed(
                title=f"{title} (Page {page_num + 1}/{total_pages})",
                description="\n".join(lines),
                colour=discord.Colour.dark_orange()
            ))

        return pages

    def build_prompt_list_pages(self, ctx: commands.Context, prompt_type: str) -> list[discord.Embed]:
        guild_id = ctx.guild.id
        label = "Truths" if prompt_type == "truth" else "Dares"

        default_prompts = self.bot.connector.list_default_prompts(prompt_type)
        guild_prompts = self.bot.connector.list_guild_prompts(guild_id, prompt_type)

        pages = (
            self._paginate_prompt_group(f"Default {label}", default_prompts, guild_id)
            + self._paginate_prompt_group(f"Server {label}", guild_prompts, guild_id)
        )

        if not pages:
            pages = [discord.Embed(
                title=label,
                description="No prompts found.",
                colour=discord.Colour.dark_orange()
            )]

        return pages

    async def paginate(self, ctx: commands.Context, pages: list[discord.Embed]) -> None:
        if len(pages) == 1:
            await ctx.send(embed=pages[0])
            return

        index = 0
        message = await ctx.send(embed=pages[index])
        controls = ["◀️", "⏹️", "▶️"]

        for emoji in controls:
            await message.add_reaction(emoji)

        def check(reaction: discord.Reaction, user: discord.User) -> bool:
            return (
                user.id == ctx.author.id
                and reaction.message.id == message.id
                and str(reaction.emoji) in controls
            )

        while True:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except (discord.Forbidden, discord.NotFound):
                    pass
                return

            emoji = str(reaction.emoji)
            if emoji == "▶️":
                index = (index + 1) % len(pages)
            elif emoji == "◀️":
                index = (index - 1) % len(pages)
            elif emoji == "⏹️":
                try:
                    await message.clear_reactions()
                except (discord.Forbidden, discord.NotFound):
                    pass
                return

            await message.edit(embed=pages[index])
            try:
                await message.remove_reaction(reaction.emoji, user)
            except (discord.Forbidden, discord.NotFound):
                pass

    # ------------------------------------------------------------------
    # cog check
    # ------------------------------------------------------------------

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False

        cfg = self.bot.connector.get_guild_config(ctx.guild.id)
        tod_channel = cfg["tod_channel"]

        if tod_channel is not None and ctx.channel.id != tod_channel:
            await ctx.send(
                embed=discord.Embed(
                    title="Failed to Run Command",
                    description=f"Can only run commands in <#{tod_channel}>",
                    colour=discord.Colour.red()
                )
            )
            return False

        return True

    # ------------------------------------------------------------------
    # game commands
    # ------------------------------------------------------------------

    @commands.group(name="tod", invoke_without_command=True)
    async def tod(self, ctx: commands.Context) -> None:
        """The command group for TOD related commands, runs when no subcommand is invoked."""
        async with ctx.typing():
            guild_id = ctx.guild.id

            if guild_id in self.games:
                await ctx.send(
                    embed=discord.Embed(
                        title="Failed",
                        description="A TOD game is already running.",
                        colour=discord.Colour.red()
                    )
                )
                return

            self.games[guild_id] = {
                "session_owner": ctx.author.id,
                "players": [ctx.author.id],
                "message": None,
                "last_prompts": [],
                "waiting_for_response": False,
            }

            cfg = self.bot.connector.get_guild_config(guild_id)
            tod_role = cfg["tod_role"]
            ping = f"<@&{tod_role}>" if tod_role else ""

            embed = self.build_lobby_embed(guild_id, "TOD Lobby Created")
            self.games[guild_id]["message"] = await ctx.send(
                f"|| {ping} ||" if ping else None,
                embed=embed
            )

    @tod.command(name="help")
    async def tod_help(self, ctx: commands.Context) -> None:
        """Command to send the help embed with all the available commands."""
        async with ctx.typing():
            await ctx.send(
                embed=discord.Embed(
                    title="TOD Help",
                    description=(
                        "`+tod join` - join game\n"
                        "`+tod leave` - leave game\n"
                        "`+tod start` - start game (session owner only)\n"
                        "`+tod end` - end game (session owner/admin only)\n"
                        "`+tod next` - next player's turn (session owner only)\n"
                        "`+tod owner <user>` - transfer the session ownership (session owner only)\n"
                        "`+tod room` - view the details about the current TOD session\n"
                        "`+tod kick <user>` - remove a player from the tod session (session owner only)\n"
                        "`+tod truths` - list available truths\n"
                        "`+tod dares` - list available dares\n"
                        "`+tod ban <id>` - ban a prompt for this server (manage server)\n"
                        "`+tod unban <id>` - unban a prompt for this server (manage server)\n"
                        "`+tod add truth <prompt>` - add a custom truth (manage server)\n"
                        "`+tod add dare <prompt>` - add a custom dare (manage server)"
                    ),
                    colour=discord.Colour.blue()
                )
            )
            return

    @tod.command(name="room")
    async def tod_room(self, ctx: commands.Context) -> None:
        """Command to view details about the current TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            if guild_id not in self.games:
                await ctx.send("No TOD game is running.")
                return
            await ctx.send(embed=self.build_lobby_embed(guild_id))
            return

    @tod.command(name="next")
    async def tod_next(self, ctx: commands.Context) -> None:
        """Command to advance player turns."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send("No active game.")
                return
            if ctx.author.id != game["session_owner"]:
                await ctx.send("Only session owner can advance turns.")
                return
            if "turn_order" not in game or not game["turn_order"]:
                await ctx.send("Game hasn't been started properly.")
                return
            if game["waiting_for_response"]:
                await ctx.send("Already waiting for a player's response.")
                return

            game["turn_index"] = (game["turn_index"] + 1) % len(game["turn_order"])
            player = game["turn_order"][game["turn_index"]]

            await self.run_turn(ctx, player)
            return

    @tod.command(name="start")
    async def tod_start(self, ctx: commands.Context) -> None:
        """Command to start the TOD game if a session is available."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send("No available room.")
                return
            if ctx.author.id != game["session_owner"]:
                await ctx.send("Only session owner can start.")
                return
            if len(game["players"]) < 1:
                await ctx.send("Need at least 1 player.")
                return
            if game.get("turn_order"):
                await ctx.send("Game has already been started.")
                return

            game["turn_order"] = game["players"].copy()
            random.shuffle(game["turn_order"])
            game["turn_index"] = 0

            player = game["turn_order"][game["turn_index"]]
            await self.run_turn(ctx, player)
            return

    @tod.command(name="end")
    async def tod_end(self, ctx: commands.Context) -> None:
        """Command to end a running TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send("No running game.")
                return

            is_owner = ctx.author.id == game["session_owner"]
            is_admin = ctx.author.guild_permissions.administrator

            if not (is_owner or is_admin):
                await ctx.send("You don't have permission to end this game.")
                return

            await game["message"].edit(
                embed=discord.Embed(
                    title="Game Ended",
                    description="TOD session has been ended.",
                    colour=discord.Colour.red()
                )
            )

            del self.games[guild_id]
            await ctx.send("Game ended.")
            return

    @tod.command(name="join")
    async def tod_join(self, ctx: commands.Context) -> None:
        """Command to join a running TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send("No TOD game is running.")
                return
            if ctx.author.id in game["players"]:
                await ctx.send("You are already in the game.")
                return

            game["players"].append(ctx.author.id)
            if "turn_order" in game and ctx.author.id not in game["turn_order"]:
                game["turn_order"].append(ctx.author.id)

            await game["message"].edit(embed=self.build_lobby_embed(guild_id))
            await ctx.send(f"{ctx.author.mention} joined.")
            return

    @tod.command(name="leave")
    async def tod_leave(self, ctx: commands.Context) -> None:
        """Command to leave a running TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send("No TOD game is running.")
                return
            if ctx.author.id not in game["players"]:
                await ctx.send("You're not in this game.")
                return
            if ctx.author.id == game["session_owner"]:
                await ctx.send("Session owner cannot leave the game.")
                return

            game["players"].remove(ctx.author.id)
            self.remove_player_turn(guild_id, ctx.author.id)

            await game["message"].edit(embed=self.build_lobby_embed(guild_id))
            await ctx.send(f"{ctx.author.mention} left.")
            return

    @tod.command(name="owner")
    async def transfer_ownership(self, ctx: commands.Context, user: discord.Member = None) -> None:
        """Command to transfer ownership of a running TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send(":x: There is no running game.")
                return
            if ctx.author.id != game["session_owner"]:
                await ctx.send(":x: Only the session owner can run this command.")
                return
            if user is None:
                await ctx.send(":x: Must mention a user.")
                return
            if user.id not in game["players"]:
                await ctx.send(":x: User must be a player in the running game.")
                return
            if user.id == game["session_owner"]:
                await ctx.send(":x: That user is already the session owner.")
                return

            game["session_owner"] = user.id
            await game["message"].edit(embed=self.build_lobby_embed(guild_id))
            await ctx.send(f"Ownership transferred to <@{user.id}>.")
            return

    @tod.command(name="kick")
    async def tod_kick(self, ctx: commands.Context, user: discord.Member = None) -> None:
        """Command to remove a player from a running TOD session."""
        async with ctx.typing():
            guild_id = ctx.guild.id
            game = self.games.get(guild_id)

            if game is None:
                await ctx.send(":x: There is no running game.")
                return
            if ctx.author.id != game["session_owner"]:
                await ctx.send(":x: Only the session owner can run this command.")
                return
            if user is None:
                await ctx.send(":x: Must mention a user.")
                return
            if user.id not in game["players"]:
                await ctx.send(":x: User must be a player in the running game.")
                return
            if user.id == game["session_owner"]:
                await ctx.send(":x: Session owner cannot be kicked.")
                return

            game["players"].remove(user.id)
            self.remove_player_turn(guild_id, user.id)

            await game["message"].edit(embed=self.build_lobby_embed(guild_id))
            await ctx.send(f"<@{user.id}> has been removed from running game.")
            return

    # ------------------------------------------------------------------
    # prompt browsing / management
    # ------------------------------------------------------------------

    @tod.command(name="truths")
    async def tod_truths(self, ctx: commands.Context) -> None:
        """Lists all available truths for this server, paginated."""
        pages = self.build_prompt_list_pages(ctx, "truth")
        await self.paginate(ctx, pages)

    @tod.command(name="dares")
    async def tod_dares(self, ctx: commands.Context) -> None:
        """Lists all available dares for this server, paginated."""
        pages = self.build_prompt_list_pages(ctx, "dare")
        await self.paginate(ctx, pages)

    @tod.command(name="ban")
    @commands.has_permissions(manage_guild=True)
    async def tod_ban(self, ctx: commands.Context, prompt_id: int) -> None:
        """Bans a prompt from this server's pool."""
        connector = self.bot.connector

        if not connector.is_prompt_visible_to_guild(ctx.guild.id, prompt_id):
            await ctx.send(embed=discord.Embed(
                title="Error", description=f"No prompt found with ID `#{prompt_id}`.",
                colour=discord.Colour.red()
            ))
            return

        if connector.is_prompt_banned(ctx.guild.id, prompt_id):
            await ctx.send(embed=discord.Embed(
                title="Error", description=f"Prompt `#{prompt_id}` is already banned.",
                colour=discord.Colour.red()
            ))
            return

        await connector.ban_prompt(ctx.guild.id, prompt_id, banned_by=ctx.author.id)
        await ctx.send(embed=discord.Embed(
            title="Success", description=f"Prompt `#{prompt_id}` banned for this server.",
            colour=discord.Colour.green()
        ))

    @tod.command(name="unban")
    @commands.has_permissions(manage_guild=True)
    async def tod_unban(self, ctx: commands.Context, prompt_id: int) -> None:
        """Unbans a prompt for this server's pool."""
        connector = self.bot.connector

        if not connector.is_prompt_visible_to_guild(ctx.guild.id, prompt_id):
            await ctx.send(embed=discord.Embed(
                title="Error", description=f"No prompt found with ID `#{prompt_id}`.",
                colour=discord.Colour.red()
            ))
            return

        if not connector.is_prompt_banned(ctx.guild.id, prompt_id):
            await ctx.send(embed=discord.Embed(
                title="Error", description=f"Prompt `#{prompt_id}` is not banned.",
                colour=discord.Colour.red()
            ))
            return

        await connector.unban_prompt(ctx.guild.id, prompt_id)
        await ctx.send(embed=discord.Embed(
            title="Success", description=f"Prompt `#{prompt_id}` unbanned for this server.",
            colour=discord.Colour.green()
        ))

    @tod.group(name="add", invoke_without_command=True)
    async def tod_add(self, ctx: commands.Context) -> None:
        """Shows add-related subcommands."""
        await ctx.send_help(ctx.command)

    @tod_add.command(name="truth")
    @commands.has_permissions(manage_guild=True)
    async def add_truth(self, ctx: commands.Context, *, prompt: str) -> None:
        """Adds a custom truth for this server."""
        new_id = await self.bot.connector.add_prompt(ctx.guild.id, "truth", prompt, added_by=ctx.author.id)
        await ctx.send(embed=discord.Embed(
            title="Success", description=f"Truth added with ID `#{new_id}`.",
            colour=discord.Colour.green()
        ))

    @tod_add.command(name="dare")
    @commands.has_permissions(manage_guild=True)
    async def add_dare(self, ctx: commands.Context, *, prompt: str) -> None:
        """Adds a custom dare for this server."""
        new_id = await self.bot.connector.add_prompt(ctx.guild.id, "dare", prompt, added_by=ctx.author.id)
        await ctx.send(embed=discord.Embed(
            title="Success", description=f"Dare added with ID `#{new_id}`.",
            colour=discord.Colour.green()
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(TOD(bot))