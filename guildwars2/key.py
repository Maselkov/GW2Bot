import discord
import asyncio

from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APIInactiveError


class KeyMixin:

    waitingfor = []

    @commands.group()
    async def key(self, ctx):
        """Commands related to API keys"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
            return

    @key.command(name="add")
    @commands.cooldown(1, 2, BucketType.user)
    async def key_add(self, ctx, key):
        """Adds a key and associates it with your discord account

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
            output = "Your message was removed for privacy."
        elif guild is None:
            output = ""
        else:
            output = ("I would've removed your message as well, but I don't "
                      "have the neccesary permissions.")
        doc = await self.bot.database.get_user(user, self)
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
        newkeydoc = {
            "key": key,
            "_id": user.id,
            "account_name": acc["name"],
            "name": name,
            "permissions": token["permissions"]
        }
        #at this point we know the key is valid
        try:
            keys = doc["keys"]
            #check if key is already in keys list
            if newkeydoc not in keys:
                if len(keys) < 8:
                    keys.append(newkeydoc)
                else:
                    await ctx.send("You've reached the maximum limit of 8 API keys," 
                        "please remove one before adding another. {0}".format(output))
                    return
            else:
                await ctx.send("You have already added this key before. {0}".format(output))
                return
        except:
            #keys list doesn't exist - this is either the first key the user has added or 
            #they existed before this functionality
            try:
                currentkey = await self.fetch_key(user)
                #will raise an exception if the user has no key
                #if not we should append both keys to the keys list
                keys = []
                keys.append(currentkey)
                keys.append(newkeydoc)
            except:
                #user doesn't have an active key either so this is their first key
                keys = []
                keys.append(newkeydoc)
        finally:
            await self.bot.database.set_user(user, {"key": newkeydoc, "keys": keys}, self)
        await ctx.send("{.mention}, your key was verified and "
                       "associated with your account. {}".format(user, output))
        all_permissions = ("account", "builds", "characters", "guilds",
                           "inventories", "progression", "pvp", "tradingpost",
                           "unlocks", "wallet")
        missing = [x for x in all_permissions if x not in newkeydoc["permissions"]]
        if missing:
            msg = ("Please note that your API key doesn't have the "
                   "following permissions checked: ```{}```\nSome commands "
                   "will not work. Consider adding a new key with "
                   "those permissions checked.".format(", ".join(missing)))
            try:
                await user.send(msg)
            except:
                pass

    @key.command(name="remove")
    @commands.cooldown(1, 1, BucketType.user)
    async def key_remove(self, ctx):
        """Removes a key from the bot

        Requires a key
        """
        if ctx.author.id in KeyMixin.waitingfor:
            await ctx.send("I'm already waiting for a response from you for another key command.")
            return
        doc = await self.bot.database.get_user(ctx.author, self)
        try:
            keys = doc["keys"]
        except KeyError:
            #no keys
            keys = []
            try:
                key = doc["key"]
                key = {}
            except KeyError:
                return await ctx.send("You have no keys added, you can add one with {0}key add.".format(ctx.prefix))
        else:
            key = doc["key"]
        if doc["keys"] == [] and doc["key"] == {}:
            return await ctx.send("You have no keys added, you can add one with {0}key add.".format(ctx.prefix))
        if len(keys) > 0:
            if ctx.guild is not None:
                await ctx.send("Check your PMs.")        
            output = "Type the number of the key you wish to delete, or respond with all to remove all keys.\n```"
            for count, key in enumerate(keys, 1):
                output += str(count) + ": " + key["name"] + " Account: " + key["account_name"] + " Key: " + key["key"] +"\n"
            output += "```"
            message = await ctx.author.send(output)
            def check(m):
                return m.author == ctx.author and m.channel == message.channel
            try:
                KeyMixin.waitingfor.append(ctx.author.id)
                answer = await self.bot.wait_for("message", timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time.")
                return
            finally:
                KeyMixin.waitingfor.remove(ctx.author.id)

            try:
                num = int(answer.content) - 1
                if keys[num]["key"] == doc["key"]["key"]:
                    key = {}
                    await ctx.author.send("This was your active key, you won't be able to use "
                        "commands that require a key unless you set a new key with +key active.")
                del keys[num]
            except:
                if 'all' in answer.content.lower():
                    keys = []
                    key = {}
                else:
                    await message.edit(content="That's not a number in the list.")
                    return
        await self.bot.database.set_user(ctx.author, {"key": key, "keys": keys}, self)
        await ctx.author.send("{.mention}, successfuly removed your key/keys. "
                       "You may input a new one.".format(ctx.author))

    @key.command(name="info")
    @commands.cooldown(1, 5, BucketType.user)
    async def key_info(self, ctx):
        """Information about your active api key
        """
        doc = await self.bot.database.get_user(ctx.author, self)
        try:
            key = await self.fetch_key(ctx.author)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(colour=self.embed_color)
        if key["name"]:
            data.add_field(name="Key name", value=key["name"])
        data.add_field(name="Permissions", value=', '.join(key["permissions"]))
        data.set_author(name=key["account_name"])
        msg = "Your active key is:```fix\n{}```".format(key["key"])
        if isinstance(ctx.channel, discord.DMChannel):
            msg += "\nthis information will only ever be DMed to you"
        try:
            keys = doc["keys"]
            output = "List of all your keys.\n```"
            for key in keys:
                output += key["name"] + " - Account: " + key["account_name"] + " Key: " + key["key"] +"\n"
            output += "```"
            await ctx.author.send(output)
        except:
            pass
        try:
            await ctx.author.send(msg)
        except:
            pass
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")


    @key.command(name="active", usage="<choice>")
    @commands.cooldown(1, 5, BucketType.user)
    async def key_active(self, ctx, choice: int = 0):
        """Swaps between multiple stored API keys.

        Can be used with no parameter to display a list of all your keys to select from,
        or with a number to immediately swap to a selected key e.g $key active 3"""
        if ctx.author.id in KeyMixin.waitingfor:
            await ctx.send("I'm already waiting for a response from you for another key command.")
            return
        doc = await self.bot.database.get_user(ctx.author, self)
        try:
            keys = doc["keys"]
        except KeyError:
            try:
                key = doc["key"]
                if key != {}:
                    await ctx.send("You only have one key added at the moment, add extras with {0}key add first.".format(ctx.prefix))
                    return
            except KeyError:
                await ctx.send("You need to add an API keys first using {0}key add first.".format(ctx.prefix))
                return
        if len(keys) < 2 and keys != []:
            return await ctx.send("You only have one key added at the moment, add extras with {0}key add first.".format(ctx.prefix))
        if doc["keys"] == [] and doc["key"] == {}:
            return await ctx.send("You have no keys added, you can add one with {0}key add.".format(ctx.prefix))
        destination = ctx.channel
        if choice == 0:
            if ctx.guild is not None:
                await ctx.send("Check your PMs.")
            destination = ctx.author
            output = "Type the number of the key you wish to activate.\n```"
            for count, key in enumerate(keys, 1):
                output += str(count) + ": " + key["name"] + " Account: " + key["account_name"] + " Key: " + key["key"] +"\n"
            output += "```"
            message = await ctx.author.send(output)
            def check(m):
                return m.author == ctx.author and m.channel == message.channel
            try:
                KeyMixin.waitingfor.append(ctx.author.id)
                answer = await self.bot.wait_for("message", timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time.")
                return
            finally:
                KeyMixin.waitingfor.remove(ctx.author.id)
            choice = answer.content
        try:
            num = int(choice) - 1
            if keys[num]["key"] == doc["key"]["key"]:
                await destination.send("This is already your currently active key.")
                return
        except:
            await destination.send(content="You don't have a key with this ID, remember you can "
                "check your list of keys by using this command without a number.")
            return
        key = keys[num]
        await self.bot.database.set_user(ctx.author, {"key": key}, self)
        await destination.send("Successfully swapped to the selected key. Name: {0}".format(key["name"]))

