import asyncio

from discord_slash import cog_ext
from discord_slash.model import ButtonStyle, SlashCommandOptionType
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_button,
                                                   wait_for_component)


class GuildManageMixin:
    @cog_ext.cog_subcommand(base="server",
                            name="force_account_names",
                            base_description="Server management commands")
    async def server_force_account_names(self, ctx, enabled: bool):
        """Automatically change nicknames to in-game names"""
        guild = ctx.guild
        if not ctx.guild:
            return await ctx.send("This command can only be used in servers.",
                                  hidden=True)
        if not ctx.author.guild_permissions.manage_nicknames:
            return await ctx.send("You need the manage nicknames permission "
                                  "to enable this feature.")
        doc = await self.bot.database.get(guild, self)
        if doc and enabled and doc.get("forced_account_names"):
            return await ctx.send("Forced account names are already enabled")
        if not enabled:
            await self.bot.database.set(guild, {"force_account_names": False},
                                        self)
            return await ctx.send("Forced account names disabled")
        if not ctx.guild.me.guild_permissions.manage_nicknames:
            return await ctx.send("I need the manage nicknames permission "
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

    @cog_ext.cog_subcommand(
        base="server",
        name="preview_chat_links",
        base_description="Server management commands",
        options=[{
            "name": "enabled",
            "description": "Enable or disable automatic chat link preview",
            "type": SlashCommandOptionType.BOOLEAN,
            "required": True,
        }])
    async def previewchatlinks(self, ctx, *, enabled):
        """Enable or disable automatic GW2 chat link preview"""
        if not ctx.guild:
            return await ctx.send("This command can only be used in a server.",
                                  hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(
                "You need the manage server permission to use this command.",
                hidden=True)
        doc = await self.bot.database.get(ctx.guild, self)
        disabled = doc.get("link_preview_disabled", False)
        if disabled and not enabled:
            return await ctx.send("Chat link preview is aleady disabled.",
                                  hidden=True)
        if not disabled and enabled:
            return await ctx.send("Chat link preview is aleady enabled.",
                                  hidden=True)
        if not disabled and not enabled:
            self.chatcode_preview_opted_out_guilds.add(ctx.guild.id)
            return await ctx.send("Chat link preview is now disabled.",
                                  hidden=True)
        if disabled and enabled:
            await self.bot.database.set_guild(
                ctx.guild, {"link_preview_disabled": not enabled}, self)
            await self.bot.database.set_guild(
                ctx.guild, {"link_preview_disabled": not enabled}, self)
            try:
                self.chatcode_preview_opted_out_guilds.remove(ctx.guild.id)
            except KeyError:
                pass
            return await ctx.send("Chat link preview is now enabled.",
                                  hidden=True)

    @cog_ext.cog_subcommand(base="server",
                            name="sync",
                            base_description="Server management commands")
    async def sync_now(self, ctx):
        """Force a sync for any Guildsyncs and Worldsyncs you have"""
        if not ctx.guild:
            return await ctx.send("This command can only be used in a server.",
                                  hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(
                "You need the manage server permission to use this command.",
                hidden=True)
        await ctx.send("Syncs scheduled!")
        await self.guildsync_now(ctx)
        await self.worldsync_now(ctx)

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
