"""Miscellaneous commands: /wiki and /chatcode."""
import codecs
import struct
import urllib.parse

import discord
from bs4 import BeautifulSoup
from discord import app_commands
from discord.app_commands import Choice

from gw2bot.utils.db import prepare_search

from .base import GW2Cog


def generate_chat_code(item_id, count, skin_id, upgrades):
    """An item chat link (https://wiki.guildwars2.com/wiki/Chat_link_format)."""

    def little_endian(_id):
        return [int(x) for x in struct.pack("<i", _id)]

    def upgrade_flag():
        flag = 0
        if skin_id:
            flag |= 0x80
        if len(upgrades) >= 1:
            flag |= 0x40
        if len(upgrades) >= 2:
            flag |= 0x20
        return flag

    link = [2, count]
    link.extend(little_endian(item_id))
    link = link[:5]
    link.append(upgrade_flag())
    for x in filter(None, (skin_id, *upgrades)):
        link.extend(little_endian(x))
    output = codecs.encode(bytes(link), 'base64').decode('utf-8')
    return "[&{}]".format(output.strip())


class Misc(GW2Cog):

    @app_commands.command()
    @app_commands.describe(
        language="The language of the wiki to search on. Optional. "
        "Defaults to English.",
        search_text="The text to search the wiki for. Example: Lion's Arch")
    @app_commands.choices(language=[
        Choice(name=p.title(), value=p) for p in ["en", "fr", "es", "de"]
    ])
    async def wiki(
            self,
            interaction: discord.Interaction,
            search_text: str,  # TODO autocomplete
            language: str = "en"):
        """Search the Guild wars 2 wiki"""
        if len(search_text) > 300:
            return await interaction.response.send_message("Search too long",
                                                           ephemeral=True)
        await interaction.response.defer()
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
        url = search_url[language].format(wiki[language],
                                          urllib.parse.quote(search_text))
        headers = {"User-Agent": "TybaltBot/v2"}
        # Overzealous filtering on the wiki's side lead to the bot's IP being blocked.
        # Seems to be a common issue, based on https://wiki.guildwars2.com/wiki/Guild_Wars_2_Wiki:Reporting_wiki_bugs#Forbidden_403
        # And based on the information within, the wiki had added an exemption for requests with this user-string header
        # It is just a little dirty, but, it doesn't really change anything in the end.
        # The only thing being checked is this user-string, and
        # given the lack of any other verification, I don't think it's anything too bad.
        # That being said, if anyone takes an issue with this, I will contact the wiki
        # and get an exemption for GW2bot too.
        async with self.bot.session.get(url, headers=headers) as r:
            if r.history:  # Redirected
                embed = await self.search_results_embed(interaction,
                                                        "Wiki",
                                                        exact_match=r)
                return await interaction.followup.send(embed=embed)
            else:
                results = await r.text()
                soup = BeautifulSoup(results, 'html.parser')
                posts = soup.find_all(
                    "div", {"class": "mw-search-result-heading"})[:5]
                if not posts:
                    return await interaction.followup.send(
                        "No results for your search")
        embed = await self.search_results_embed(interaction,
                                                "Wiki",
                                                posts,
                                                base_url=wiki[language])
        await interaction.followup.send(embed=embed)

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
        "Example: +1 Agony Infusion",
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

        async def resolve(value, autocomplete, kind):
            """An id: picked from the autocomplete, or the first match for
            a typed name."""
            if not value:
                return None
            if value.isdigit():
                return int(value)
            choices = await autocomplete(interaction, value)
            if not choices:
                raise LookupError(f"Could not find any {kind} named {value}")
            return int(choices[0].value)

        try:
            item = await resolve(item, self.chatcode_item_autocomplete,
                                 "items")
            skin = await resolve(skin, self.chatcode_skin_autocomplete,
                                 "skins")
            upgrade_1 = await resolve(upgrade_1,
                                      self.chatcode_upgrade_autocomplete,
                                      "upgrades")
            upgrade_2 = await resolve(upgrade_2,
                                      self.chatcode_upgrade_autocomplete,
                                      "upgrades")
        except LookupError as e:
            return await interaction.response.send_message(str(e),
                                                           ephemeral=True)
        upgrades = []
        if upgrade_1:
            upgrades.append(upgrade_1)
        if upgrade_2:
            upgrades.append(upgrade_2)
        chat_code = generate_chat_code(item, quantity, skin, upgrades)
        output = "Here's your chatcode. No refunds. ```\n{}```".format(
            chat_code)
        await interaction.response.send_message(output, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Misc(bot))
