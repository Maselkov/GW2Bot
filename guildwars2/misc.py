import codecs
import struct

import discord
from bs4 import BeautifulSoup
from cogs.guildwars2.utils.db import prepare_search
from discord import app_commands
from discord.app_commands import Choice


class MiscMixin:

    # Wiki has the bot's IP blacklisted, probably because the
    # requests looked robotic.
    # Disabled for now. Might try contacting webmaster at some point.
    # @cog_ext.cog_slash(options=[{
    #     "name": "search_text",
    #     "description": "The text to search the wiki for. Example: Lion's Arch",
    #     "type": SlashCommandOptionType.STRING,
    #     "required": True,
    # }, {
    #     "name":
    #     "language",
    #     "description":
    #     "The language of the wiki to search on. Optional.",
    #     "type":
    #     SlashCommandOptionType.STRING,
    #     "choices": [{
    #         "value": "en",
    #         "name": "en"
    #     }, {
    #         "value": "de",
    #         "name": "de"
    #     }, {
    #         "value": "fr",
    #         "name": "fr"
    #     }, {
    #         "value": "es",
    #         "name": "se"
    #     }],
    #     "required":
    #     False,
    # }])
    # async def wiki(self, ctx, search_text, language="en"):
    #     """Search the Guild wars 2 wiki"""
    #     if len(search_text) > 300:
    #         return await ctx.send("Search too long", ephemeral=True)
    #     await interaction.response.defer()
    #     wiki = {
    #         "en": "https://wiki.guildwars2.com",
    #         "de": "https://wiki-de.guildwars2.com",
    #         "fr": "https://wiki-fr.guildwars2.com",
    #         "es": "https://wiki-es.guildwars2.com"
    #     }
    #     search_url = {
    #         "en": "{}/index.php?title=Special%3ASearch&search={}",
    #         "de": "{}/index.php?search={}&title=Spezial%3ASuche&",
    #         "fr": "{}/index.php?search={}&title=Spécial%3ARecherche",
    #         "es": "{}/index.php?title=Especial%3ABuscar&search={}"
    #     }
    #     url = (search_url[language].format(wiki[language], search_text))
    #     async with self.session.get(url) as r:
    #         if r.history:  # Redirected
    #             embed = await self.search_results_embed(ctx,
    #                                                     "Wiki",
    #                                                     exact_match=r)
    #             return await ctx.send(embed=embed)
    #         else:
    #             results = await r.text()
    #             soup = BeautifulSoup(results, 'html.parser')
    #             posts = soup.find_all(
    #                 "div", {"class": "mw-search-result-heading"})[:5]
    #             if not posts:
    #                 return await ctx.send("No results for your search")
    #     embed = await self.search_results_embed(ctx,
    #                                             "Wiki",
    #                                             posts,
    #                                             base_url=wiki[language])
    #     await ctx.send(embed=embed)

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

    async def chatcode_item_autocomplete(self,
                                         interaction: discord.Interaction,
                                         current: str):
        if not current:
            return []
        query = prepare_search(current)
        query = {
            "name": query,
        }
        items = await self.db.items.find(query).to_list(25)
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    async def chatcode_skin_autocomplete(self,
                                         interaction: discord.Interaction,
                                         current: str):
        if not current:
            return []
        query = prepare_search(current)
        query = {
            "name": query,
        }
        items = await self.db.skins.find(query).to_list(25)
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    async def chatcode_upgrade_autocomplete(self,
                                            interaction: discord.Interaction,
                                            current: str):
        if not current:
            return []
        query = prepare_search(current)
        query = {"name": query, "type": "UpgradeComponent"}
        items = await self.db.items.find(query).to_list(25)
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    @app_commands.command()
    @app_commands.describe(
        item="Base item name for the chat code. Example: Banana",
        quantity="Item quantity, ranging from 1 to 255.",
        skin="Skin name to apply on the item.",
        upgrade_1="Name of the upgrade in the first slot. "
        "Example: Mark of Penetration",
        upgrade_2="Name of the upgrade in the second slot. "
        "Example: Superior rune of Generosity")
    @app_commands.autocomplete(item=chatcode_item_autocomplete,
                               skin=chatcode_skin_autocomplete,
                               upgrade_1=chatcode_upgrade_autocomplete,
                               upgrade_2=chatcode_upgrade_autocomplete)
    async def chatcode(
        self,
        interaction: discord.Interaction,
        item: str,
        quantity: int,
        skin: str = None,
        upgrade_1: str = None,
        upgrade_2: str = None,
    ):
        """Generate a chat code"""
        if not 1 <= quantity <= 255:
            return await interaction.response.send_message(
                "Invalid quantity. Quantity can be a number between 1 and 255",
                ephemeral=True)
        try:
            item = int(item)
            skin = int(skin) if skin else None
            upgrade_1 = int(upgrade_1) if upgrade_1 else None
            upgrade_2 = int(upgrade_2) if upgrade_2 else None
        except ValueError:
            return await interaction.response.send_message("Invalid value",
                                                           ephemeral=True)
        upgrades = []
        if upgrade_1:
            upgrades.append(upgrade_1)
        if upgrade_2:
            upgrades.append(upgrade_2)
        chat_code = self.generate_chat_code(item, quantity, skin, upgrades)
        output = "Here's your chatcode. No refunds. ```\n{}```".format(
            chat_code)
        await interaction.response.send_message(output, ephemeral=True)

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
