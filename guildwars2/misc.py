import random

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
