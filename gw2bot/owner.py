"""Owner-only text commands, ported from Toothy's owner cog."""
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
    async def reload_extension(self, ctx, *, name: str = "guildwars2"):
        """Reloads an extension (default: guildwars2)"""
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


async def setup(bot):
    await bot.add_cog(Owner(bot))
