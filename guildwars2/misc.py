import asyncio
import codecs
import struct

import discord
from bs4 import BeautifulSoup
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType


class MiscMixin:
    @cog_ext.cog_slash(options=[{
        "name": "search_text",
        "description": "The text to search the wiki for. Example: Lion's Arch",
        "type": SlashCommandOptionType.STRING,
        "required": True,
    }, {
        "name":
        "language",
        "description":
        "The language of the wiki to search on. Optional.",
        "type":
        SlashCommandOptionType.STRING,
        "choices": [{
            "value": "en",
            "name": "en"
        }, {
            "value": "de",
            "name": "de"
        }, {
            "value": "fr",
            "name": "fr"
        }, {
            "value": "es",
            "name": "se"
        }],
        "required":
        False,
    }])
    async def wiki(self, ctx, search_text, language="en"):
        """Search the Guild wars 2 wiki"""
        if len(search_text) > 300:
            return await ctx.send("Search too long", hidden=True)
        await ctx.defer()
        wiki = {
            "en": "https://wiki.guildwars2.com",
            "de": "https://wiki-de.guildwars2.com",
            "fr": "https://wiki-fr.guildwars2.com",
            "es": "https://wiki-es.guildwars2.com"
        }
        search_url = {
            "en": "{}/index.php?title=Special%3ASearch&search={}",
            "de": "{}/index.php?search={}&title=Spezial%3ASuche&",
            "fr": "{}/index.php?search={}&title=Spécial%3ARecherche",
            "es": "{}/index.php?title=Especial%3ABuscar&search={}"
        }
        url = (search_url[language].format(wiki[language], search_text))
        async with self.session.get(url) as r:
            if r.history:  # Redirected
                embed = await self.search_results_embed(ctx,
                                                        "Wiki",
                                                        exact_match=r)
                return await ctx.send(embed=embed)
            else:
                results = await r.text()
                soup = BeautifulSoup(results, 'html.parser')
                posts = soup.find_all(
                    "div", {"class": "mw-search-result-heading"})[:5]
                if not posts:
                    return await ctx.send("No results for your search")
        embed = await self.search_results_embed(ctx,
                                                "Wiki",
                                                posts,
                                                base_url=wiki[language])
        await ctx.send(embed=embed)

    async def search_results_embed(self,
                                   ctx,
                                   site,
                                   posts=None,
                                   *,
                                   base_url="",
                                   exact_match=None):
        if exact_match:
            soup = BeautifulSoup(await exact_match.text(), 'html.parser')
            embed = discord.Embed(title=soup.title.get_text(),
                                  color=await self.get_embed_color(ctx),
                                  url=str(exact_match.url))
            return embed
        embed = discord.Embed(title="{} search results".format(site),
                              description="Closest matches",
                              color=await self.get_embed_color(ctx))
        for post in posts:
            post = post.a
            url = base_url + post['href']
            url = url.replace(")", "\\)")
            embed.add_field(name=post["title"],
                            value="[Click here]({})".format(url),
                            inline=False)
        return embed

    @cog_ext.cog_slash(options=[{
        "name": "item",
        "description": "Base item name for the chat code. Example: Banana",
        "type": SlashCommandOptionType.STRING,
        "required": True,
    }, {
        "name": "quantity",
        "description": "Item quantity, ranging from 1 to 255.",
        "type": SlashCommandOptionType.INTEGER,
        "required": True,
    }, {
        "name": "skin",
        "description": "Skin name to apply on the item.",
        "type": SlashCommandOptionType.STRING,
        "required": False,
    }, {
        "name": "upgrade_1",
        "description":
        "Name of the upgrade in the first slot. Example: Mark of Penetration",
        "type": SlashCommandOptionType.STRING,
        "required": False,
    }, {
        "name":
        "upgrade_2",
        "description":
        "Name of the upgrade in the second slot. Example: Superior rune of "
        "Generosity",
        "type":
        SlashCommandOptionType.STRING,
        "required":
        False,
    }])
    async def chatcode(
        self,
        ctx,
        item,
        quantity,
        skin=None,
        upgrade_1=None,
        upgrade_2=None,
    ):
        """Generate a chat code"""
        if not 1 <= quantity <= 255:
            return await ctx.send(
                "Invalid quantity. Quantity can be a number between 1 and 255",
                hidden=True)
        item, answer = await self.itemname_to_id(ctx,
                                                 item,
                                                 prompt_user=True,
                                                 hidden=True)
        if not item:
            return
        item = item["_id"]
        if skin:
            skin, new_answer = await self.itemname_to_id(
                ctx,
                skin,
                database="skins",
                prompt_user=True,
                hidden=True,
                component_context=answer,
                placeholder="Select the skin you want...")
            if not skin:
                return
            if new_answer:
                answer = new_answer
        if skin is not None:
            skin = skin["_id"]
        upgrade_names = [x for x in [upgrade_1, upgrade_2] if x]
        upgrades = []
        for upgrade in upgrade_names:
            upgrade, new_answer = await self.itemname_to_id(
                ctx,
                upgrade,
                filters={"type": "UpgradeComponent"},
                prompt_user=True,
                hidden=True,
                placeholder="Select the upgrade you want...",
                component_context=answer)
            if not upgrade:
                return
            if new_answer:
                answer = new_answer
            upgrades.append(upgrade["_id"])

        chat_code = self.generate_chat_code(item, quantity, skin, upgrades)
        output = "Here's your chatcode. No refunds. ```\n{}```".format(
            chat_code)
        if answer:
            return await answer.edit_origin(components=None, content=output)
        await ctx.send(output, hidden=True)

    async def user_input(self, ctx, message=None, *, check=None, timeout=60):
        user = ctx.author
        if not check:

            def check(m):
                return m.author == ctx.author and isinstance(
                    m.channel, discord.abc.PrivateChannel)

        try:
            if message:
                await user.send(message)
            answer = await self.bot.wait_for("message",
                                             timeout=timeout,
                                             check=check)
            return answer
        except asyncio.TimeoutError:
            return None

    def generate_chat_code(self, item_id, count, skin_id, upgrades):
        def little_endian(_id):
            return [int(x) for x in struct.pack("<i", _id)]

        def upgrade_flag():
            skin = 0
            first = 0
            second = 0
            if skin_id:
                skin = 128
            if len(upgrades) == 1:
                first = 64
            if len(upgrades) == 2:
                second = 32
            return skin | first | second

        link = [2, count]
        link.extend(little_endian(item_id))
        link = link[:5]
        link.append(upgrade_flag())
        for x in filter(None, (skin_id, *upgrades)):
            link.extend(little_endian(x))
        link.append(0)
        output = codecs.encode(bytes(link), 'base64').decode('utf-8')
        return "[&{}]".format(output.strip())
