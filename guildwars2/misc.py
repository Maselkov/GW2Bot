from bs4 import BeautifulSoup
from discord.ext import commands


class MiscMixin:
    @commands.command()
    async def gw2wiki(self, ctx, *search):
        """Search the guild wars 2 wiki
        Returns the first result, will not always be accurate.
        """
        search = "+".join(search)
        wiki = "http://wiki.guildwars2.com/"
        wiki_ = "http://wiki.guildwars2.com"
        search = search.replace(" ", "+")
        user = ctx.author
        url = ("{}index.php?title=Special%3ASearch&profile=default&fulltext="
               "Search&search={}".format(wiki, search))
        async with self.session.get(url) as r:
            results = await r.text()
            soup = BeautifulSoup(results, 'html.parser')
        try:
            div = soup.find("div", {"class": "mw-search-result-heading"})
            a = div.find('a')
            link = a['href']
            await ctx.send("{.mention}: {}{}".format(user, wiki_, link))
        except:
            await ctx.send("{.mention}, no results found".format(user))
