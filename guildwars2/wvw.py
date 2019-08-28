import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APIKeyError

class WvwMixin:
#### For the "WVW" group command
    @commands.group(case_insensitive=True, name='wvw')
    async def wvw(self, ctx):
        """Commands related to WvW"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

  ### For the wvw "INFO" command
    @wvw.command(name='info', usage='<world name>')
    @commands.cooldown(1, 10, BucketType.user)
    async def wvw_info(self, ctx, *, world: str = None):
        """Info about a world.
        
        Defaults to your world."""
        user = ctx.author
        if not world:
            try:
                endpoint = 'account'
                results = await self.call_api(endpoint, user)
                wid = results['world']
            except APIKeyError as e:
                return await ctx.send(
                    "No world name or key associated with your account.")
            except APIError as e:
                return await self.error_handler(ctx, e)
        else:
            wid = await self.get_world_id(world)
        if not wid:
            await ctx.send("Invalid world name.")
            return
        try:
            endpoints = [
                f"wvw/matches?world={wid}",
                f"worlds?id={wid}"
            ]
            matches, worldinfo = await self.call_multiple(endpoints)
        except APIError as e:
            return await self.error_handler(ctx, e)
        for key, value in matches['all_worlds'].items():
            if wid in value:
                worldcolor = key
        if not worldcolor:
            await ctx.send("Could not resolve world's color.")
            return
        if worldcolor == 'red':
            color = discord.Colour.red()
        elif worldcolor == 'green':
            color = discord.Colour.green()
        else:
            color = discord.Colour.blue()
        score = matches['scores'][worldcolor]
        ppt = 0
        victoryp = matches['victory_points'][worldcolor]
        for m in matches['maps']:
            for objective in m['objectives']:
                if objective['owner'].lower() == worldcolor:
                    ppt += objective['points_tick']
        population = worldinfo['population']
        if population == 'VeryHigh':
            population = 'Very high'
        kills = matches['kills'][worldcolor]
        deaths = matches['deaths'][worldcolor]
        kd = round((kills / deaths), 2)
        data = discord.Embed(description='Performance', colour=color)
        data.add_field(name='Score', value=score)
        data.add_field(name='Points per tick', value=ppt)
        data.add_field(name='Victory Points', value=victoryp)
        data.add_field(name='K/D ratio', value=str(kd), inline=False)
        data.add_field(name='Population', value=population, inline=False)
        data.set_author(name=worldinfo['name'])
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links.")

  ### For the wvw "POPULATIONTRACK" command
    @wvw.command(name='populationtrack', usage='<world name>')
    @commands.cooldown(1, 5, BucketType.user)
    async def wvw_population_track(self, ctx, *, world_name):
        """Receive a notification when a world is no longer full."""
        user = ctx.author
        wid = await self.get_world_id(world_name)
        if not wid:
            return await ctx.send("Invalid world name.")
        doc = await self.bot.database.get_user(user, self)
        if doc and wid in doc.get('poptrack', []):
            return await ctx.send("You're already tracking this world.")
        try:
            results = await self.call_api(f"worlds/{wid}")
        except APIError as e:
            return await self.error_handler(ctx, e)
        if results['population'] != 'Full':
            return await ctx.send("This world is currently not full.")
        try:
            await user.send(f"You will be notiifed when {world_name.title()} is no longer full.")
        except:
            return await ctx.send("Couldn't send a DM to you. Either you have "
                                  "me blocked, or disabled DMs in this "
                                  "server. Aborting.")
        await self.bot.database.set_user(
            user, {'poptrack': wid}, self, operator='$push')
        await ctx.send("Successfully set.")
        
  ### For the wvw "POPULATIONTRACK" command. These are for hidden aliases
    @wvw.command(name='population', usage='<world name>', aliases=['poptrack', 'populationnotification', 'populationnotif', 'popnotif', 'popnotification'], hidden=True)
    @commands.cooldown(1, 5, BucketType.user)
    async def wvw_population(self, ctx, *, world_name):
        """Receive a notification when a world is no longer full."""
        await ctx.invoke(self.wvw_population_track, world_name=world_name)
        
  ### For the wvw "WORLDS" command
    @wvw.command(name='worlds')
    @commands.cooldown(1, 20, BucketType.user)
    async def wvw_worlds(self, ctx):
        """List all worlds."""
        try:
            results = await self.call_api('worlds?ids=all')
        except APIError as e:
            return await self.error_handler(ctx, e)
        output = "Available worlds are: ```"
        for world in results:
            output += world['name'] + ", "
        output += "```"
        await ctx.send(output)
