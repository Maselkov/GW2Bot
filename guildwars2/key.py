import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APIInactiveError


class KeyMixin:
    @commands.group()
    async def key(self, ctx):
        """Commands related to API keys"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
            return

    @key.command(name="add")
    @commands.cooldown(1, 2, BucketType.user)
    async def key_add(self, ctx, key):
        """Adds your key and associates it with your discord account

        To generate an API key, head to https://account.arena.net, and log in.
        In the "Applications" tab, generate a new key, with all permissions.
        Then input it using $key add <key>

        Required permissions: account
        """
        guild = ctx.guild
        user = ctx.author
        if guild is None:
            has_permissions = False
        else:
            has_permissions = ctx.channel.permissions_for(
                guild.me).manage_messages
        if has_permissions:
            await ctx.message.delete()
            output = "Your message was removed for privacy"
        elif guild is None:
            output = ""
        else:
            output = ("I would've removed your message as well, but I don't "
                      "have the neccesary permissions.")
        try:  # Raises an exception if no key is found
            await self.fetch_key(user)
            return await ctx.send(
                "{.mention}, you already have a key associated with your "
                "account. Remove your key first if you wish to "
                "change it. {}".format(user, output))
        except:
            pass
        try:
            endpoints = ["tokeninfo", "account"]
            token, acc = await self.call_multiple(endpoints, key=key)
        except APIInactiveError:
            return await ctx.send("{.mention}, the API is currently down. "
                                  "Try again later. {}".format(user, output))
        except APIError:
            return await ctx.send(
                "{.mention}, invalid key. {}".format(user, output))
        name = token["name"]
        doc = {
            "key": key,
            "_id": user.id,
            "account_name": acc["name"],
            "name": name,
            "permissions": token["permissions"]
        }
        await self.bot.database.set_user(user, {"key": doc}, self)
        await ctx.send("{.mention}, your key was verified and "
                       "associated with your account. {}".format(user, output))

    @key.command(name="remove")
    @commands.cooldown(1, 1, BucketType.user)
    async def key_remove(self, ctx):
        """Removes your key from the bot

        Requires a key
        """
        user = ctx.author
        try:
            await self.fetch_key(user)
        except:
            return await ctx.send(
                "{.mention}, no API key associated with your account. "
                "Add your key using `$key add` command.".format(user))
        await self.bot.database.set_user(user, {"key": {}}, self)
        await ctx.send("{.mention}, sucessfuly removed your key. "
                       "You may input a new one.".format(user))

    @key.command(name="info")
    @commands.cooldown(1, 5, BucketType.user)
    async def key_info(self, ctx):
        """Information about your api key
        """
        try:
            doc = await self.fetch_key(ctx.author)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(colour=self.embed_color)
        if doc["name"]:
            data.add_field(name="Key name", value=doc["name"])
        data.add_field(name="Permissions", value=', '.join(doc["permissions"]))
        data.set_author(name=doc["account_name"])
        msg = "Your key is:```fix\n{}```".format(doc["key"])
        if isinstance(ctx.channel, discord.DMChannel):
            msg += "\nthis information will only ever be DMed to you"
        try:
            await ctx.author.send(msg)
        except:
            pass
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")
