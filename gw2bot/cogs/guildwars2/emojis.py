from discord.ext import commands


class EmojiMixin:
    @commands.group(name="emojis", case_insensitive=True)
    @commands.guild_only()
    @commands.is_owner()
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
