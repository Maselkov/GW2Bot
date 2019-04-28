from discord.ext import commands


class EmojiMixin:
    async def prepare_emojis(self):
        doc = await self.bot.database.get_cog_config(self)
        self.emojis = doc.get("emojis", {})

    def get_emoji(self, ctx, emoji, *, fallback=False, fallback_fmt="{}"):
        if ctx and ctx.channel.permissions_for(ctx.me).external_emojis:
            emoji_id = self.emojis.get(emoji.lower())
            if emoji_id:
                emoji_obj = self.bot.get_emoji(emoji_id)
                if emoji_obj:
                    return str(emoji_obj)
        if fallback:
            return fallback_fmt.format(emoji)
        return ""

    @commands.group(name="emojis", case_insensitive=True)
    @commands.guild_only()
    @commands.is_owner()
    async def emojis_management(self, ctx):
        """Commands related to emoji management"""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help()

    @emojis_management.command(name="register")
    async def emojis_register(self, ctx):
        """Register emojis present in the current server"""
        registered = []
        for emoji in ctx.guild.emojis:
            name = emoji.name
            await self.bot.database.set_cog_config(
                self, {"emojis." + name: emoji.id})
            registered.append(emoji.name)
        if not registered:
            return await ctx.send("No emojis were registered")
        await ctx.send("Registered {} emojis:\n```{}```".format(
            len(registered), ", ".join(registered)))
        await self.prepare_emojis()
