"""Chat link previews: posting a [&...] link shows what it is."""
import base64
import logging
import re
import struct

import discord
from discord.ext import commands

from gw2bot.builds import Build
from gw2bot.utils.wiki import page_url

from ..gamedata import CRAFTING
from ..i18n import N_, localized
from .base import GW2Cog
from .skills import skill_embed

CHATCODE_REGEX = re.compile(r"\[\&(?=[^\s\[\]]*\])(.*?)\]")
# By the link's first byte, from 1
LINK_TYPES = [
    N_("Coin"),
    N_("Item"),
    N_("NPC text string"),
    N_("Map link"),
    N_("PvP Game"),
    N_("Skill"),
    N_("Trait"),
    N_("User"),
    N_("Recipe"),
    N_("Wardrobe"),
    N_("Outfit"),
    N_("WvW objective"),
    N_("Build template"),
]
# Points of interest by the API's type: the name shown (and its emoji's)
POI_TYPES = {
    "landmark": N_("Point of Interest"),
    "waypoint": N_("Waypoint"),
    "vista": N_("Vista"),
    "unlock": N_("Unlock"),
}
TILESERVICE_BASE_URL = "https://tiles.guildwars2.com/"


class ChatLinks(GW2Cog):

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)
        # Servers that turned previews off (/server preview_chat_links)
        self.previews_disabled = set()

    async def cog_load(self):
        async for doc in self.bot.data.guilds.find({"link_preview_disabled": True}):
            self.previews_disabled.add(doc["_id"])

    def set_previews_enabled(self, guild_id, enabled):
        if enabled:
            self.previews_disabled.discard(guild_id)
        else:
            self.previews_disabled.add(guild_id)

    async def get_wiki_url(self, doc, lang):
        """The wiki page for a cached document's name, in `lang`'s wiki if
        it has one."""
        return await page_url(self.bot.session, localized(doc, lang), lang, english_name=doc["name"])

    @commands.Cog.listener("on_message")
    async def find_chatcodes(self, message: discord.Message):
        if message.guild:
            if message.guild.id in self.previews_disabled:
                return
        if not message.content:
            return
        if message.author.bot:
            return
        match = re.search(CHATCODE_REGEX, message.content)
        if not match:
            return
        chatcode = match.group()
        try:
            data = base64.b64decode(chatcode)
        except ValueError:
            return
        # Not a link the game makes
        if not data or not 1 <= data[0] <= len(LINK_TYPES):
            return
        link_type = LINK_TYPES[data[0] - 1]
        try:
            if message.guild:
                lang = await self.guild_lang(message.guild)
            else:
                lang = await self.user_lang(message.author.id)

            def t(text, **fields):
                return self.t(lang, text, **fields)

            embed = discord.Embed(title=t(link_type), color=self.embed_color)
            embed.set_author(
                name=message.author.display_name,
                icon_url=message.author.display_avatar.url,
            )
            if message.guild:
                embed.set_footer(
                    text=t(N_(
                        "Server admins can opt out of chat link "
                        'previewing by using the "/server preview_chat_links" command'
                    )),
                    icon_url=self.bot.user.display_avatar.url,
                )
            else:
                embed.set_footer(icon_url=self.bot.user.display_avatar.url)
            embed.description = t(N_("Chat link preview"))
            reference = None
            if message.guild:
                me = message.guild.me
            else:
                me = self.bot.user
            if message.channel.permissions_for(me).read_message_history:
                reference = message
            match link_type:
                case "Coin":
                    # Currently disabled
                    return
                case "Item":
                    quantity, item_id = struct.unpack("<BI", data[1:5] + b"\0")
                    item_doc = await self.fetch_item(item_id)
                    if not item_doc:
                        return
                    embed.title = localized(item_doc, lang)
                    embed.set_thumbnail(url=item_doc["icon"])
                    embed.color = int(
                        self.gamedata["items"]["rarity_colors"][item_doc["rarity"]], 16
                    )
                    suffix = ""
                    wiki_url = await self.get_wiki_url(item_doc, lang)
                    if wiki_url:
                        embed.url = wiki_url
                    if len(data) > 5:
                        bitfield = struct.unpack("<B", data[5:6])
                        bitfield = bitfield[0]
                        flags = []
                        # Wardrobe, upgrade 1, upgrade 2
                        for i in reversed(range(5, 8)):
                            flags.append(bool(bitfield >> i & 1))
                        if flags[2] and not flags[1]:  # Use first upgrade slut
                            flags[1] = True
                            flags[2] = False
                        offset = 0
                        if flags[0]:
                            skin_id = struct.unpack("<I", data[6:9] + b"\0")
                            skin_id = skin_id[0]
                            skin_doc = await self.db.skins.find_one({"_id": skin_id})
                            if not skin_doc:
                                name = t(N_("Unknown"))
                            else:
                                name = localized(skin_doc, lang)
                                embed.set_thumbnail(url=skin_doc["icon"])
                            embed.add_field(name=t(N_("Skin")), value=name)
                            offset += 4
                        upgrades = []
                        for upgrade in flags[1:]:
                            if not upgrade:
                                break
                            upgrade_id = struct.unpack(
                                "<I", data[6 + offset : 9 + offset] + b"\0"
                            )
                            upgrade_id = upgrade_id[0]
                            offset += 4
                            upgrade_doc = await self.db.items.find_one(
                                {"_id": upgrade_id}
                            )
                            if not upgrade_doc:
                                upgrades.append(t(N_("Unknown upgrade")))
                                continue
                            upgrades.append(localized(upgrade_doc, lang))
                            if not suffix:
                                suffix = localized(upgrade_doc, lang, "details.suffix") or ""
                        if upgrades:
                            field_name = N_("Upgrades") if len(upgrades) > 1 else N_("Upgrade")
                            embed.add_field(name=t(field_name), value="\n".join(upgrades))
                        if suffix:
                            embed.title = f"{embed.title} {suffix}"
                    if quantity > 1:
                        embed.title = f"{quantity} {embed.title}"
                    return await message.channel.send(
                        embed=embed, reference=reference, mention_author=False
                    )
                case "NPC text string":
                    # Currently disabled
                    return
                case "Map link":
                    data = struct.unpack("<I", data[1:])
                    poi_id = data[0]
                    poi_doc = await self.db.pois.find_one({"_id": poi_id})
                    # continent_id = poi_doc["continent_id"]
                    # floor = poi_doc["floor"]
                    # x, y = [int(i) for i in poi_doc["coord"]]
                    # tile_url = TILESERVICE_BASE_URL + f"{continent_id}/{floor}/3/{x}/{y}.jpg"
                    # async with self.session.get(tile_url) as r:
                    #     image = io.BytesIO(await r.read())
                    # image.seek(0)
                    # print(tile_url)
                    # file = discord.File(image, "tile.jpg")
                    # embed.set_image(url=f"attachment://{file.filename}")
                    # await message.channel.send(file=file)
                    # API SUCKS
                    # TODO More detail
                    poi_type = POI_TYPES.get(poi_doc["type"], poi_doc["type"].title())
                    emoji = self.get_emoji(message, poi_type)
                    embed.add_field(
                        name=emoji + t(poi_type), value=localized(poi_doc, lang) or t(N_("Unnamed"))
                    )
                    return await message.channel.send(
                        embed=embed, reference=reference, mention_author=False
                    )
                case "PvP Game":
                    # Can't do much here
                    return
                case "Skill":
                    data = struct.unpack("<I", data[1:])
                    skill_id = data[0]
                    skill_doc = await self.db.skills.find_one({"_id": skill_id})
                    if not skill_doc:
                        return
                    new_embed = await skill_embed(self, skill_doc, message, lang)
                    new_embed.set_footer(
                        text=embed.footer.text, icon_url=embed.footer.icon_url
                    )
                    return await message.channel.send(
                        embed=new_embed, reference=reference, mention_author=False
                    )
                case "Trait":
                    data = struct.unpack("<I", data[1:])
                    trait_id = data[0]
                    trait_doc = await self.db.traits.find_one({"_id": trait_id})
                    if not trait_doc:
                        return
                    new_embed = await skill_embed(self, trait_doc, message, lang)
                    new_embed.set_footer(
                        text=embed.footer.text, icon_url=embed.footer.icon_url
                    )
                    return await message.channel.send(
                        embed=new_embed, reference=reference, mention_author=False
                    )
                case "User":
                    # Can't do much
                    return
                case "Recipe":
                    data = struct.unpack("<I", data[1:])
                    recipe_id = data[0]
                    recipe_doc = await self.db.recipes.find_one({"_id": recipe_id})
                    if not recipe_doc:
                        return
                    output = await self.fetch_item(recipe_doc["output_item_id"])
                    if output:
                        embed.title = t(N_("Recipe: {count} {name}"), count=recipe_doc["output_item_count"],
                                        name=localized(output, lang))
                    emojis = message.channel.permissions_for(me).external_emojis
                    disciplines = recipe_doc.get("disciplines", [])
                    if emojis:
                        value = []
                        for disc in disciplines:
                            value.append(self.get_emoji(message, disc))
                        value = "".join(value)
                    else:
                        value = "\n".join(t(CRAFTING.get(disc, disc)) for disc in disciplines)
                    if value:
                        embed.add_field(name=t(N_("Crafting disciplines")), value=value)
                    ingredients = recipe_doc.get("ingredients", [])
                    value = []
                    for ingredient in ingredients:
                        item_doc = await self.fetch_item(ingredient["item_id"])
                        if item_doc:
                            value.append(f"{ingredient['count']} {localized(item_doc, lang)}")
                    value = "\n".join(value)
                    if value:
                        embed.add_field(name=t(N_("Ingredients")), value=value)
                    return await message.channel.send(
                        embed=embed, reference=reference, mention_author=False
                    )
                case "Wardrobe":
                    data = struct.unpack("<I", data[1:])
                    skin_id = data[0]
                    skin_doc = await self.db.skins.find_one({"_id": skin_id})
                    if not skin_doc:
                        return
                    embed.set_thumbnail(url=skin_doc["icon"])
                    embed.title = localized(skin_doc, lang)
                    return await message.channel.send(
                        embed=embed, reference=reference, mention_author=False
                    )
                case "Outfit":
                    data = struct.unpack("<I", data[1:])
                    outfit_id = data[0]
                    outfit_doc = await self.db.outfits.find_one({"_id": outfit_id})
                    if not outfit_doc:
                        return
                    embed.set_thumbnail(url=outfit_doc["icon"])
                    embed.title = localized(outfit_doc, lang)
                    return await message.channel.send(
                        embed=embed, reference=reference, mention_author=False
                    )
                case "WvW objective":
                    # TODO
                    return
                case "Build template":
                    build = await Build.from_code(self, chatcode)
                    file = await build.render()
                    embed.color = build.profession.color
                    embed.set_thumbnail(url=build.profession.icon)
                    embed.set_image(url=f"attachment://{file.filename}")
                    return await message.channel.send(
                        embed=embed,
                        reference=reference,
                        file=file,
                        mention_author=False,
                    )
        except Exception:
            self.log.exception("Exception previewing a chat link")
        finally:
            field_id = link_type.replace(" ", "_").lower()
            await self.bot.data.statistics.update_one(
                {"_id": "link_previews"}, {"$inc": {field_id: 1}}, upsert=True
            )


async def setup(bot):
    await bot.add_cog(ChatLinks(bot))
