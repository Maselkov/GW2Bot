import asyncio

from discord_slash import cog_ext
from discord_slash.model import ButtonStyle
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_button,
                                                   wait_for_component)


class GuildManageMixin:
    @cog_ext.cog_subcommand(base="server",
                            name="forceaccountnames",
                            base_description="Server management commands")
    async def server_force_account_names(self, ctx, enabled: bool):
        """Automatically change nicknames to in-game names"""
        guild = ctx.guild
        doc = await self.bot.database.get(guild, self)
        if doc and enabled and doc.get("forced_account_names"):
            return await ctx.send("Forced account names are already enabled")
        if not enabled:
            await self.bot.database.set(guild, {"force_account_names": False},
                                        self)
            return await ctx.send("Forced account names disabled")
        if not ctx.guild.me.guild_permissions.manage_nicknames:
            return await ctx.send("I need the manage nicknames permissions "
                                  "for this feature")

        button = create_button(style=ButtonStyle.green,
                               emoji="✅",
                               label="Confirm")
        components = [create_actionrow(button)]
        await ctx.send(
            "Enabling this option will change all members' nicknames with "
            "registered keys to their in game account names. This will wipe "
            "their existing nicknames, if they don't include their account "
            "name.\nTo proceed, click on the button below",
            components=components)
        try:
            ans = await wait_for_component(
                self.bot,
                components=components,
                timeout=120,
                check=lambda c: c.author == ctx.author)
        except asyncio.TimeoutError:
            return await ctx.message.edit(content="Timed out", components=None)
        await self.bot.database.set(guild, {"force_account_names": True}, self)
        await self.force_guild_account_names(guild)
        await ans.edit_origin(
            content="Automatic account names enabled. To disable, use "
            "`/server forceaccountnames false`\nPlease note that the "
            "bot cannot change nicknames for roles above the bot.",
            components=None)

    async def force_guild_account_names(self, guild):
        for member in guild.members:
            try:
                key = await self.fetch_key(member)
                name = key["account_name"]
                if name.lower() not in member.display_name.lower():
                    await member.edit(nick=name,
                                      reason="Force account names - $server")
            except Exception:
                pass
