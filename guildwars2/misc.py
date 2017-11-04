import asyncio
import codecs
import random
import struct
from collections import OrderedDict

import discord
from bs4 import BeautifulSoup
from discord.ext import commands


class MiscMixin:
    @commands.command(aliases=["gw2wiki"])
    async def wiki(self, ctx, *, search):
        """Search the Guild wars 2 wiki"""
        if len(search) > 300:
            await ctx.send("Search too long")
            return
        wiki = "https://wiki.guildwars2.com"
        search = search.replace(" ", "+")
        url = ("{}/index.php?title=Special%3ASearch&"
               "Search&search={}".format(wiki, search))
        async with self.session.get(url) as r:
            if r.history:
                embed = await self.search_results_embed("Wiki", exact_match=r)
                try:
                    await ctx.send(embed=embed)
                except discord.Forbidden:
                    await ctx.send("Need permission to embed links")
                return
            else:
                results = await r.text()
                soup = BeautifulSoup(results, 'html.parser')
                posts = soup.find_all(
                    "div", {"class": "mw-search-result-heading"})[:5]
                if not posts:
                    await ctx.send("No results")
                    return
        embed = await self.search_results_embed("Wiki", posts, base_url=wiki)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @commands.command()
    async def dulfy(self, ctx, *, search):
        """Search dulfy.net"""
        if len(search) > 300:
            await ctx.send("Search too long")
            return
        search = search.replace(" ", "+")
        base_url = "https://dulfy.net/"
        url = base_url + "?s={}".format(search)
        message = await ctx.send(
            "Searching dulfy.net, this can take a while...")
        async with self.session.get(url) as r:
            results = await r.text()
            soup = BeautifulSoup(results, 'html.parser')
        posts = soup.find_all(class_="post-title")[:5]
        if not posts:
            return await message.edit(content="No results")
        embed = await self.search_results_embed("Dulfy", posts)
        try:
            await message.edit(content=None, embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def search_results_embed(self,
                                   site,
                                   posts=None,
                                   *,
                                   base_url="",
                                   exact_match=None):
        if exact_match:
            soup = BeautifulSoup(await exact_match.text(), 'html.parser')
            embed = discord.Embed(
                title=soup.title.get_text(),
                color=self.embed_color,
                url=str(exact_match.url))
            return embed
        embed = discord.Embed(
            title="{} search results".format(site),
            description="Closest matches",
            color=self.embed_color)
        for post in posts:
            post = post.a
            url = base_url + post['href']
            url = url.replace(")", "\\)")
            embed.add_field(
                name=post["title"],
                value="[Click here]({})".format(url),
                inline=False)
        return embed

    @commands.command(hidden=True)
    async def praisejoko(self, ctx):
        """To defy his Eminence is to defy life itself"""
        praise_art = (
            "```fix\nP R A I S E\nR J     O S\nA   O K   I\nI   O K   "
            "A\nS J     O R\nE S I A R P```")
        await ctx.send(random.choice([praise_art, "Praise joko " * 40]))

    @commands.command()
    async def chatcode(self, ctx):
        """Generate a chat code"""
        user = ctx.author
        try:
            msg = await user.send("First, type the name of the item")
            if ctx.guild:
                await ctx.send("I've DMed you.")
        except:
            await ctx.send("I couldn't DM you. Check your DM settings")
        response = await self.user_input(ctx)
        dest = msg.channel
        if response is None:
            return
        item = await self.itemname_to_id(dest, response.content, user)
        if not item:
            return
        item = item["_id"]
        response = await self.user_input(ctx,
                                         "Type the amount of the item (1-255)")
        if not response:
            return
        try:
            count = int(response.content)
            if not 1 <= count <= 255:
                raise ValueError
        except:
            return await ctx.send("Invalid value")
        response = await self.user_input(
            ctx, "Optionally, type name of a skin to apply to the "
            "item. Type `skip` to skip")
        if not response:
            return
        if response.content.lower() == "skip":
            skin = None
        else:
            skin = await self.itemname_to_id(
                dest, response.content, user, database="skins")
            if skin is not None:
                skin = skin["_id"]
        upgrades = OrderedDict((("first", None), ("second", None)))
        for k in upgrades:
            response = await self.user_input(
                ctx, "Optionally, type name of {} upgrade to apply to the "
                "item. Type `skip` to skip".format(k))
            if response.content.lower() == "skip":
                break
            if not response:
                return
            upgrade = await self.itemname_to_id(
                dest,
                response.content,
                user,
                filters={"type": "UpgradeComponent"})
            if upgrade is not None:
                if upgrade["_id"] == 24887:
                    await user.send("L-lewd...")
                upgrades[k] = upgrade["_id"]
            else:
                break

        chat_code = self.generate_chat_code(
            item, count, skin, upgrades["first"], upgrades["second"])
        output = "Here's your chatcode. No refunds. ```\n{}```".format(
            chat_code)
        await user.send(output)

    async def user_input(self, ctx, message=None, *, check=None, timeout=60):
        user = ctx.author
        if not check:

            def check(m):
                return m.author == ctx.author and isinstance(
                    m.channel, discord.abc.PrivateChannel)

        try:
            if message:
                await user.send(message)
            answer = await self.bot.wait_for(
                "message", timeout=timeout, check=check)
            return answer
        except asyncio.TimeoutError:
            return None

    def generate_chat_code(self, item_id, count, skin_id, first_upgrade_id,
                           second_upgrade_id):
        def little_endian(_id):
            return [int(x) for x in struct.pack("<i", _id)]

        def upgrade_flag():
            skin = 0
            first = 0
            second = 0
            if skin_id:
                skin = 128
            if first_upgrade_id:
                first = 64
            if second_upgrade_id:
                second = 32
            return skin | first | second

        link = [2, count]
        link.extend(little_endian(item_id))
        link = link[:5]
        link.append(upgrade_flag())
        for x in filter(None, (skin_id, first_upgrade_id, second_upgrade_id)):
            link.extend(little_endian(x))
        link.append(0)
        output = codecs.encode(bytes(link), 'base64').decode('utf-8')
        return "[&{}]".format(output.strip())
