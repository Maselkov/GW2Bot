import asyncio
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APIInactiveError


class KeyMixin:
#### For the "KEY" group command
    @commands.group(case_insensitive=True, name='key')
    async def key(self, ctx):
        """Commands related to API keys"""
        try:
            if not ctx.invoked_subcommand and len(ctx.message.content) > 74:
                await ctx.send(f"Perhaps you meant {ctx.prefix}key add?")
                await ctx.message.delete()
        except:
            pass
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command)

  ### For the key "ADD" command
    @key.command(name='add', usage='<API key>')
    @commands.cooldown(1, 2, BucketType.user)
    async def key_add(self, ctx, key):
        """Adds a key to your account.
        
        This adds a key and associates it with your discord account.
        
        To generate an API key, go to https://account.arena.net, and log in.
        In the "Applications" tab, generate a new key with all the permissions you want.
        Then input it using $key add <key>

        Required permission: account"""
        guild = ctx.guild
        user = ctx.author
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            await ctx.message.delete()
            output = "Your message was removed for privacy."
        elif guild is None:
            output = ""
        else:
            output = ("I would've removed your message as well, but I don't "
                      "have the neccesary permissions.")
        if key.startswith('<') and key.endswith('>'):
            return await ctx.send(
                f"{user.mention}, please don't use `<` and `>` in the actual key. "
                f"It's only for the help message.\n{output}")
        doc = await self.bot.database.get(user, self)
        try:
            endpoints = ['tokeninfo', 'account']
            token, acc = await self.call_multiple(endpoints, key=key)
        except APIInactiveError:
            return await ctx.send(f"{user.mention}, the API is currently down. "
                                  f"Try again later.\n{output}")
        except APIError:
            return await ctx.send(f"{user.mention}, invalid key.\n{output}")
        key_doc = {
            'key': key,
            'account_name': acc['name'],
            'name': token['name'],
            'permissions': token['permissions']
        }
        # at this point we know the key is valid
        keys = doc.get('keys', [])
        key = doc.get('key', {})
        if not keys and key:
            # user already had a key but it isn't in keys
            # (existing user) so add it
            keys.append(key)
        if key_doc['key'] in [k['key'] for k in keys]:
            return await ctx.send(
                f"{user.mention}, this key is already associated with your account.\n{output}")
        if len(keys) >= 12:
            return await ctx.send(
                f"{user.mention}, you've reached the maximum limit of "
                "12 API keys, please remove one before adding "
                f"another.\n{output}")
        keys.append(key_doc)
        await self.bot.database.set_user(user, {
            'key': key_doc,
            'keys': keys
        }, self)
        if len(keys) > 1:
            await ctx.send(f"{user.mention}, your key was verified and "
                           "added to your account.\nYou can swap between "
                           f"your keys at any time using `{ctx.prefix}key switch`.\n{output}")
        else:
            await ctx.send(f"{user.mention}, your key was verified and "
                           f"associated with your account.\n{output}")
        all_permissions = ('account', 'builds', 'characters', 'guilds',
                           'inventories', 'progression', 'pvp', 'tradingpost',
                           'unlocks', 'wallet')
        missing = [
            x for x in all_permissions if x not in key_doc['permissions']
        ]
        if missing:
            msg = ("Please note that your API key doesn't have the "
                   f"following permissions checked: ```{', '.join(missing)}```\nSome commands "
                   "will not work. Consider adding a new key with "
                   "those permissions checked.")
            try:
                await user.send(msg)
            except Exception as e:
                pass
        try:
            if guild:
                await self.worldsync_on_member_join(user)
                await self.guildsync_on_member_join(user)
                return
            for guild in self.bot.guilds:
                if len(guild.members) > 3000:
                    continue
                if user not in guild.members:
                    continue
                doc = await self.bot.database.get(guild, self)
                worldsync = doc.get('worldsync', {})
                worldsync_enabled = worldsync.get('enabled', False)
                if worldsync_enabled:
                    member = guild.get_member(user.id)
                    await self.worldsync_on_member_join(member)
                guildsync = doc.get('sync', {})
                if guildsync.get('on', False) and guildsync.get(
                        'setupdone', False):
                    member = guild.get_member(user.id)
                    await self.guildsync_on_member_join(member)
        except:
            pass

  ### For the key "INFO" command
    @key.command(name='info')
    @commands.cooldown(1, 5, BucketType.user)
    async def key_info(self, ctx):
        """Info about your active api key."""
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get('keys', [])
        key = doc.get('key', {})
        if not keys and not key:
            return await ctx.send(
                f"You don't have a key added. You can add one with {ctx.prefix}key add.")
        embed = await self.display_keys(
            ctx,
            doc,
            display_active=True,
            show_tokens=True,
            reveal_tokens=True)
        try:
            await ctx.author.send(embed=embed)
        except discord.HTTPException:
            if ctx.guild:
                await ctx.send("I cannot send a message to you.")

  ### For the key "REMOVE" command
    @key.command(name='remove')
    @commands.cooldown(1, 1, BucketType.user)
    async def key_remove(self, ctx):
        """Removes a key from your account."""
        if ctx.author.id in self.waiting_for:
            return await ctx.send(
                "I'm already waiting for a response from you for "
                "another key command.")
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get('keys', [])
        key = doc.get('key', {})
        if not keys and not key:
            return await ctx.send(
                f"You don't have a key added. You can add one with {ctx.prefix}key add.")
        if key and not keys:
            keys = []
            key = {}
        else:
            embed = await self.display_keys(ctx, doc)
            try:
                message = await ctx.author.send(
                    "Simply type the number of "
                    "the key you wish to delete, or respond with "
                    "`all` to remove all keys",
                    embed=embed)
            except discord.Forbidden:
                await ctx.send("You're blocking my DMs.")
                return
            if ctx.guild:
                await ctx.send("Check your DMs.")

            def check(m):
                return m.author == ctx.author and m.channel == message.channel

            try:
                self.waiting_for.append(ctx.author.id)
                answer = await self.bot.wait_for(
                    'message', timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time.")
                return
            finally:
                self.waiting_for.remove(ctx.author.id)
            try:
                num = int(answer.content) - 1
                if keys[num] == key:
                    key = {}
                    await ctx.author.send(
                        "This was your active key, so you won't be able to use "
                        "commands that require a key unless you set a "
                        f"new key with `{ctx.prefix}key switch`.")
                del keys[num]
            except (ValueError, IndexError):
                if 'all' in answer.content.lower():
                    keys = []
                    key = {}
                else:
                    return await message.edit(
                        content="That's not a number in the list.")
        await ctx.author.send(f"{ctx.author.mention}, your key has been removed.\n")
        await self.bot.database.set_user(ctx.author, {
            'key': key,
            'keys': keys
        }, self)

  ### For the key "SWITCH" command
    @key.command(name='switch', usage='<choice>')
    @commands.cooldown(1, 5, BucketType.user)
    async def key_switch(self, ctx, choice: int = 0):
        """Swaps between your keys.

        Can be used with no choice to display a list of all your keys to select from, or with a number to immediately swap to a selected key."""
        if ctx.author.id in self.waiting_for:
            return await ctx.send(
                "I'm already waiting for a response from you "
                "for another key command.")
        doc = await self.bot.database.get(ctx.author, self)
        keys = doc.get('keys', [])
        key = doc.get('key', {})
        if not keys:
            return await ctx.send(
                f"You need to add additional API keys first using `{ctx.prefix}key "
                "add` first.")
        destination = ctx.channel
        if not choice:
            destination = ctx.author
            embed = await self.display_keys(ctx, doc)
            try:
                message = await ctx.author.send(
                    "Type the number of the key you want to switch to.",
                    embed=embed)
            except discord.Forbidden:
                return await ctx.send("You're blocking my DMs.")
            if ctx.guild:
                await ctx.send("Check your DMs.")

            def check(m):
                return m.author == ctx.author and m.channel == message.channel

            try:
                self.waiting_for.append(ctx.author.id)
                answer = await self.bot.wait_for(
                    'message', timeout=120, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time.")
                return
            finally:
                self.waiting_for.remove(ctx.author.id)
            choice = answer.content
        try:
            num = int(choice) - 1
            key = keys[num]
            await self.bot.database.set(ctx.author, {'key': key}, self)
            msg = "Swapped to the selected key."
            if key['name']:
                msg += f" Name: `{key['name']}`"
            await destination.send(msg)
        except:
            await destination.send(
                content="You don't have a key with this ID, remember you can "
                "check your list of keys by using this command without "
                "a number.")
            return

    ## Displays keys
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
                token = key['key']
                if not reveal_tokens:
                    token = token[:7] + re.sub('[a-zA-Z0-9]', '\*', token[8:])
                lines.append(token)
            return '\n'.join(lines)

        keys = doc.get('keys', [])
        embed = discord.Embed(
            title="Your keys:", color=await self.get_embed_color(ctx))
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar_url)
        if display_active:
            active_key = doc.get('key', {})
            if active_key:
                name = f"**Active key**: {active_key['account_name']}"
                token_name = active_key['name']
                if token_name:
                    name += ' - ' + token_name
                embed.add_field(name=name, value=get_value(active_key))
        for counter, key in enumerate(keys, start=1):
            name = f"**{counter}**: {key['account_name']}"
            token_name = key['name']
            if token_name:
                name += ' - ' + token_name
            embed.add_field(name=name, value=get_value(key), inline=False)
        if show_tokens and not reveal_tokens:
            embed.set_footer(
                text=f"Use {ctx.prefix}key info to see a list of your API keys",
                icon_url=self.bot.user.avatar_url)
        else:
            embed.set_footer(
                text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        return embed
