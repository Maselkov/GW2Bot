import asyncio

from discord.ext import commands


class GuildManageMixin:
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.group(name="server")
    async def guild_manage(self, ctx):
        """Commands for server management"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @guild_manage.command(name="forceaccountnames")
    @commands.has_permissions(manage_nicknames=True)
    async def server_force_account_names(self, ctx, on_off: bool):
        """Automatically change nicknames to in-game names"""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        guild = ctx.guild
        doc = await self.bot.database.get_guild(guild, self)
        if doc and on_off and doc.get("forced_account_names"):
            return await ctx.send("Forced account names are already enabled")
        if not on_off:
            await self.bot.database.set_guild(
                guild, {"force_account_names": False}, self)
            return await ctx.send("Forced account names disabled")
        if not ctx.guild.me.guild_permissions.manage_nicknames:
            return await ctx.send("I need the manage nicknames permissions "
                                  "for this feature")
        message = await ctx.send(
            "Enabling this option will change all members' nicknames with "
            "registered keys to their in game account names. This will wipe "
            "their existing nicknames.\nTo proceed, type `I agree`")
        try:
            answer = await self.bot.wait_for(
                "message", timeout=30, check=check)
        except asyncio.TimeoutError:
            return await message.edit(content="No response in time")
        if answer.content.lower() != "i agree":
            return await ctx.send("Aborting")
        await self.bot.database.set_guild(guild, {"force_account_names": True},
                                          self)
        await self.force_guild_account_names(guild)
        await ctx.send("Automatic account names enabled. To disable, use "
                       "`$server forceaccountnames off`\nPlease note that the "
                       "bot cannot change nicknames for roles above the bot.")

    async def force_guild_account_names(self, guild):
        for member in guild.members:
            try:
                key = await self.fetch_key(member)
                name = key["account_name"]
                if not member.nick == name:
                    await member.edit(
                        nick=name, reason="Force account names - $server")
            except:
                pass
