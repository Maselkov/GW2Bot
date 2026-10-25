"""Owner-only text commands, ported from Toothy's owner cog."""
import io
import json
import traceback

import discord
from discord.ext import commands


class Owner(commands.Cog):
    """Control the bot"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    @commands.command(name="reload")
    async def reload_extension(self, ctx, *, name: str):
        """Reloads an extension, e.g. >reload keys"""
        extension = "gw2bot.cogs." + name.strip()
        try:
            await self.bot.reload_extension(extension)
        except Exception:
            return await ctx.send("```py\n{}\n```".format(traceback.format_exc()))
        await ctx.send("Extension reloaded succesfully")

    @commands.command()
    async def sync(self, ctx, guild_only: bool = False):
        """Sync the slash command tree, globally or to TEST_GUILD only"""
        if guild_only:
            if not self.bot.test_guild:
                return await ctx.send("TEST_GUILD is not set")
            test_guild = discord.Object(id=self.bot.test_guild)
            self.bot.tree.copy_global_to(guild=test_guild)
            await self.bot.tree.sync(guild=test_guild)
        else:
            await self.bot.tree.sync()
            await self.bot.record_command_sync()
        await ctx.send("Synced")

    @commands.group(name="emojis", case_insensitive=True)
    @commands.guild_only()
    async def emojis_management(self, ctx):
        """Commands related to emoji management"""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command)

    @emojis_management.command(name="register")
    async def emojis_register(self, ctx):
        """Register emojis present in the current server"""
        registered = []
        for emoji in ctx.guild.emojis:
            name = emoji.name
            await self.bot.gw2_emojis.register(name, emoji.id)
            registered.append(emoji.name)
        if not registered:
            return await ctx.send("No emojis were registered")
        await ctx.send(
            "Registered {} emojis:\n```{}```".format(
                len(registered), ", ".join(registered)
            )
        )

    @commands.command(name="guildsync_repair")
    async def guildsync_repair(self, ctx, mode: str = "dry-run"):
        """Link guild sync ranks back to the roles they had before guild sync
        replaced them, from an attached JSON list of syncs and their old and
        replacement role ids. A dry run unless `>guildsync_repair apply`."""
        if not ctx.message.attachments:
            return await ctx.send("Attach the JSON file of roles to relink")
        apply = mode == "apply"
        entries = json.loads(await ctx.message.attachments[0].read())
        async with ctx.typing():
            counts, lines = await self.bot.get_cog("GuildSync").repair_replaced_roles(entries, apply=apply)
        summary = "\n".join(f"{outcome}: {count}" for outcome, count in sorted(counts.items()))
        report = discord.File(io.BytesIO("\n".join(lines).encode()), filename="guildsync-repair.txt")
        await ctx.send(f"{'Applied' if apply else 'Dry run, nothing changed'}:\n```\n{summary}\n```", file=report)


async def setup(bot):
    await bot.add_cog(Owner(bot))
