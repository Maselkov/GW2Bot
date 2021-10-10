import asyncio
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord_slash import cog_ext
from discord_slash.context import SlashContext
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_select,
                                                   create_select_option,
                                                   wait_for_component)

from .exceptions import APIError, APIInactiveError
from discord_slash.model import SlashCommandOptionType


class KeyMixin:
    @cog_ext.cog_subcommand(
        base="key",
        name="add",
        base_description="Key related commands",
        options=[{
            "name": "key",
            "description":
            "Generate at https://account.arena.net under Applications tab",
            "type": SlashCommandOptionType.STRING,
            "required": True,
        }])
    async def key_add(self, ctx: SlashContext, key):
        """Adds a key and associates it with your discord account"""
        doc = await self.bot.database.get(ctx.author, self)
        await ctx.defer(hidden=True)
        try:
            endpoints = ["tokeninfo", "account"]
            token, acc = await self.call_multiple(endpoints, key=key)
        except APIInactiveError:
            return await ctx.send("The API is currently down. "
                                  "Try again later. ")
        except APIError:
            return await ctx.send("The key is invalid.")
        key_doc = {
            "key": key,
            "account_name": acc["name"],
            "name": token["name"],
            "permissions": token["permissions"]
        }
        # at this point we know the key is valid
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and key:
            # user already had a key but it isn't in keys
            # (existing user) so add it
            keys.append(key)
        if key_doc["key"] in [k["key"] for k in keys]:
            return await ctx.send("You have already added this key before.")
        if len(keys) >= 15:
            return await ctx.send(
                "You've reached the maximum limit of "
                "15 API keys, please remove one before adding "
                "another")
        keys.append(key_doc)
        await self.bot.database.set(ctx.author, {
            "key": key_doc,
            "keys": keys
        }, self)
        if len(keys) > 1:
            output = ("Your key was verified and "
                      "added to your list of keys, you can swap between "
                      "them at any time using /key switch.")
        else:
            output = ("Your key was verified and "
                      "associated with your account.")
        all_permissions = ("account", "builds", "characters", "guilds",
                           "inventories", "progression", "pvp", "tradingpost",
                           "unlocks", "wallet")
        missing = [
            x for x in all_permissions if x not in key_doc["permissions"]
        ]
        if missing:
            output += ("\nPlease note that your API key doesn't have the "
                       "following permissions checked: "
                       f"```{', '.join(missing)}```\nSome commands "
                       "will not work. Consider adding a new key with "
                       "those permissions checked.")

        await ctx.send(output)
        try:
            if ctx.guild:
                await self.worldsync_on_member_join(ctx.author)
                await self.guildsync_on_member_join(ctx.author)
                return
            for guild in self.bot.guilds:
                try:
                    if len(guild.members) > 5000:
                        continue
                    if ctx.author not in guild.members:
                        continue
                    doc = await self.bot.database.get(guild, self)
                    worldsync = doc.get("worldsync", {})
                    worldsync_enabled = worldsync.get("enabled", False)
                    if worldsync_enabled:
                        member = guild.get_member(ctx.author.id)
                        await self.worldsync_on_member_join(member)
                    guildsync = doc.get("sync", {})
                    if guildsync.get("on", False) and guildsync.get(
                            "setupdone", False):
                        member = guild.get_member(ctx.author.id)
                        await self.guildsync_on_member_join(member)
                except Exception:
                    pass
        except Exception:
            pass

    async def key_dropdown(self, ctx, keys, placeholder, max_values=None):
        if not max_values:
            max_values = len(keys)
        options = []
        for i, key in enumerate(keys):
            options.append(
                create_select_option(key["account_name"],
                                     description=key["name"],
                                     value=i))
        select = create_select(min_values=1,
                               max_values=max_values,
                               options=options,
                               placeholder=placeholder)
        components = [create_actionrow(select)]
        msg = await ctx.send("** **", components=components, hidden=True)
        try:
            answer = await wait_for_component(self.bot,
                                              components=components,
                                              timeout=120)
            return answer
        except asyncio.TimeoutError:
            await msg.edit(content="No response in time.", components=None)
            return None

    @cog_ext.cog_subcommand(base="key",
                            name="remove",
                            base_description="Key related commands")
    async def key_remove(self, ctx: SlashContext):
        """Remove selected keys from the bot"""
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and not key:
            return await ctx.send(
                "You have no keys added, you can add one with /key add.")
        if not keys and key:
            keys.append(key)
        answer = await self.key_dropdown(ctx, keys,
                                         "Select the keys you want to remove")
        if not answer:
            return
        choices = [int(ans) for ans in answer.selected_options]
        for choice in choices:
            if keys[choice] == key:
                key = {}
            del keys[choice]
        await self.bot.database.set(ctx.author, {
            "key": key,
            "keys": keys
        }, self)
        await answer.edit_origin(content="Successfuly removed selected keys.",
                                 components=None)

    @cog_ext.cog_subcommand(base="key",
                            name="info",
                            base_description="Key related commands")
    async def key_info(self, ctx: SlashContext):
        """Information about your active api keys"""
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and not key:
            return await ctx.send(
                "You have no keys added, you can add one with /key add.",
                hidden=True)
        embed = await self.display_keys(ctx,
                                        doc,
                                        display_active=True,
                                        show_tokens=True,
                                        reveal_tokens=True)
        await ctx.send(embed=embed, hidden=True)

    @cog_ext.cog_subcommand(
        base="key",
        name="switch",
        base_description="Key related commands",
        options=[{
            "name": "index",
            "description":
            "Key index to switch to. Skip to get a list instead.",
            "type": SlashCommandOptionType.INTEGER,
            "required": False,
        }])
    async def key_switch(self, ctx, index: int = 0):
        """Swaps between multiple stored API keys."""
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys:
            return await ctx.send(
                "You need to add additional API keys first using /key "
                "add first.",
                hidden=True)
        answer = None
        if not index:
            answer = await self.key_dropdown(
                ctx,
                keys,
                "Select the key you want to switch to",
                max_values=1)
            if not answer:
                return
            index = int(answer.selected_options[0])
        try:
            key = keys[index]
        except IndexError:
            text = ("You don't have a key with this ID, remember you can "
                    "check your list of keys by using this command without "
                    "a number.")
            if answer:
                await answer.edit_origin(content=text, components=None)
            else:
                await ctx.send(text, hidden=True)
            await answer.edit_origin(content=text, components=None)
        await self.bot.database.set(ctx.author, {"key": key}, self)
        msg = "Swapped to selected key."
        if key["name"]:
            msg += " Name : `{}`".format(key["name"])
        await answer.edit_origin(content=msg, components=None)
        try:
            if ctx.guild:
                await self.worldsync_on_member_join(ctx.author)
            for guild in self.bot.guilds:
                try:
                    if len(guild.members) > 5000:
                        continue
                    if ctx.author not in guild.members:
                        continue
                    doc = await self.bot.database.get(guild, self)
                    worldsync = doc.get("worldsync", {})
                    worldsync_enabled = worldsync.get("enabled", False)
                    if worldsync_enabled:
                        member = guild.get_member(ctx.author.id)
                        await self.worldsync_on_member_join(member)
                except Exception:
                    pass
        except Exception:
            pass

    async def display_keys(self,
                           ctx,
                           doc,
                           *,
                           display_active=False,
                           display_permissions=True,
                           show_tokens=False,
                           reveal_tokens=False):
        def get_value(key):
            lines = []
            if display_permissions:
                lines.append("Permissions: " + ", ".join(key["permissions"]))
            if show_tokens:
                token = key["key"]
                if not reveal_tokens:
                    token = token[:7] + re.sub("[a-zA-Z0-9]", "\*", token[8:])
                else:
                    token = f"||{token}||"
                lines.append(token)
            return "\n".join(lines)

        keys = doc.get("keys", [])
        embed = discord.Embed(title="Your keys",
                              color=await self.get_embed_color(ctx))
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar_url)
        if display_active:
            active_key = doc.get("key", {})
            if active_key:
                name = "**Active key**: {}".format(active_key["account_name"])
                token_name = active_key["name"]
                if token_name:
                    name += " - " + token_name
                embed.add_field(name=name, value=get_value(active_key))
        for counter, key in enumerate(keys, start=1):
            name = "**{}**: {}".format(counter, key["account_name"])
            token_name = key["name"]
            if token_name:
                name += " - " + token_name
            embed.add_field(name=name, value=get_value(key), inline=False)
        if show_tokens and not reveal_tokens:
            embed.set_footer(text="Use {}key info to see full API keys".format(
                ctx.prefix),
                             icon_url=self.bot.user.avatar_url)
        else:
            embed.set_footer(text=self.bot.user.name,
                             icon_url=self.bot.user.avatar_url)
        return embed
