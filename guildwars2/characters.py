import datetime

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APINotFound


class CharactersMixin:
    @commands.group()
    async def character(self, ctx):
        """Character related commands"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @character.command(name="info")
    @commands.cooldown(1, 5, BucketType.user)
    async def character_info(self, ctx, *, character: str):
        """Info about the given character
        You must be the owner of the character.

        Required permissions: characters
        """

        def format_age(age):
            hours, remainder = divmod(int(age), 3600)
            minutes, seconds = divmod(remainder, 60)
            days, hours = divmod(hours, 24)
            if days:
                fmt = '{d} days, {h} hours, {m} minutes, and {s} seconds'
            else:
                fmt = '{h} hours, {m} minutes, and {s} seconds'
            return fmt.format(d=days, h=hours, m=minutes, s=seconds)

        await ctx.trigger_typing()
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        try:
            results = await self.call_api(endpoint, ctx.author, ["characters"])
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        age = format_age(results["age"])
        created = results["created"].split("T", 1)[0]
        deaths = results["deaths"]
        deathsperhour = round(deaths / (results["age"] / 3600), 1)
        if "title" in results:
            title = await self.get_title(results["title"])
        else:
            title = None
        gender = results["gender"]
        profession = results["profession"].lower()
        race = results["race"].lower()
        guild = results["guild"]
        color = self.gamedata["professions"][profession]["color"]
        color = int(color, 0)
        icon = self.gamedata["professions"][profession]["icon"]
        data = discord.Embed(description=title, colour=color)
        data.set_thumbnail(url=icon)
        data.add_field(name="Created at", value=created)
        data.add_field(name="Played for", value=age)
        if guild is not None:
            endpoint = "guild/{0}".format(results["guild"])
            try:
                guild = await self.call_api(endpoint)
            except APIError as e:
                return await self.error_handler(ctx, e)
            gname = guild["name"]
            gtag = guild["tag"]
            data.add_field(name="Guild", value="[{}] {}".format(gtag, gname))
        data.add_field(name="Deaths", value=deaths)
        data.add_field(
            name="Deaths per hour", value=str(deathsperhour), inline=False)

        craft_list = self.get_crafting(results)
        if craft_list:
            data.add_field(name="Crafting", value="\n".join(craft_list))

        data.set_author(name=character)
        data.set_footer(text="A {} {} {}".format(gender.lower(), race,
                                                 profession))
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @character.command(name="list")
    @commands.cooldown(1, 15, BucketType.user)
    async def character_list(self, ctx):
        """Lists all your characters

        Required permissions: characters
        """
        user = ctx.author
        scopes = ["characters"]
        endpoint = "characters?page=0"
        await ctx.trigger_typing()
        try:
            results = await self.call_api(endpoint, user, scopes)
        except APIError as e:
            return await self.error_handler(ctx, e)
        output = "{.mention}, your characters: ```"
        for x in results:
            output += "\n" + x["name"] + " (" + x["profession"] + ")"
        output += "```"
        await ctx.send(output.format(user))

    @character.command(name="gear")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_gear(self, ctx, *, character: str):
        """Displays the gear of given character
        You must be the owner of the character.

        Required permissions: characters
        """

        def handle_duplicates(upgrades):
            formatted_list = []
            for x in upgrades:
                if upgrades.count(x) != 1:
                    formatted_list.append(x + " x" + str(upgrades.count(x)))
                    upgrades[:] = [i for i in upgrades if i != x]
                else:
                    formatted_list.append(x)
            return formatted_list

        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        eq = results["equipment"]
        gear = {}
        pieces = [
            "Helm", "Shoulders", "Coat", "Gloves", "Leggings", "Boots",
            "Ring1", "Ring2", "Amulet", "Accessory1", "Accessory2", "Backpack",
            "WeaponA1", "WeaponA2", "WeaponB1", "WeaponB2"
        ]
        for piece in pieces:
            gear[piece] = {
                "id": None,
                "upgrades": [],
                "infusions": [],
                "stat": None,
                "name": None
            }
        for item in eq:
            for piece in pieces:
                if item["slot"] == piece:
                    gear[piece]["id"] = item["id"]
                    c = await self.fetch_item(item["id"])
                    gear[piece]["name"] = c["name"]
                    if "upgrades" in item:
                        for u in item["upgrades"]:
                            upgrade = await self.db.items.find_one({"_id": u})
                            gear[piece]["upgrades"].append(upgrade["name"])
                    if "infusions" in item:
                        for u in item["infusions"]:
                            infusion = await self.db.items.find_one({"_id": u})
                            gear[piece]["infusions"].append(infusion["name"])
                    if "stats" in item:
                        gear[piece]["stat"] = await self.fetch_statname(
                            item["stats"]["id"])
                    else:
                        thing = await self.db.items.find_one({
                            "_id": item["id"]
                        })
                        try:
                            statid = thing["details"]["infix_upgrade"]["id"]
                            gear[piece]["stat"] = await self.fetch_statname(
                                statid)
                        except:
                            gear[piece]["stat"] = ""
        profession = results["profession"].lower()
        level = results["level"]
        color = self.gamedata["professions"][profession]["color"]
        icon = self.gamedata["professions"][profession]["icon"]
        color = int(color, 0)
        data = discord.Embed(description="Gear", colour=color)
        for piece in pieces:
            if gear[piece]["id"] is not None:
                statname = gear[piece]["stat"]
                itemname = gear[piece]["name"]
                upgrade = handle_duplicates(gear[piece]["upgrades"])
                infusion = handle_duplicates(gear[piece]["infusions"])
                msg = "\n".join(upgrade + infusion)
                if not msg:
                    msg = u'\u200b'
                data.add_field(
                    name="{} {} [{}]".format(statname, itemname, piece),
                    value=msg,
                    inline=False)
        data.set_author(name=character)
        data.set_footer(
            text="A level {} {} ".format(level, profession), icon_url=icon)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden as e:
            await ctx.send("Need permission to embed links")

    @character.command(name="birthdays")
    async def character_birthdays(self, ctx):
        """Lists days until the next birthday for each of your characters.

        Required permissions: characters
        """
        user = ctx.message.author
        endpoint = "characters?page=0"
        await ctx.trigger_typing()
        try:
            results = await self.call_api(endpoint, user, ["characters"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        charlist = []
        for character in results:
            created = character["created"].split("T", 1)[0]
            dt = datetime.datetime.strptime(created, "%Y-%m-%d")
            age = datetime.datetime.utcnow() - dt
            days = age.days
            years = days / 365
            floor = int(days / 365)
            daystill = 365 - (days -
                              (365 * floor))  # finds days till next birthday
            charlist.append(character["name"] + " " + str(floor + 1) + " " +
                            str(daystill))
        sortedlist = sorted(charlist, key=lambda v: int(v.rsplit(' ', 1)[1]))
        output = "{.mention}, days until each of your characters birthdays:```"
        for character in sortedlist:
            name = character.rsplit(' ', 2)[0]
            days = character.rsplit(' ', 1)[1]
            years = character.rsplit(' ', 2)[1]
            if years == "1":
                suffix = 'st'
            elif years == "2":
                suffix = 'nd'
            elif years == "3":
                suffix = 'rd'
            else:
                suffix = 'th'
            output += "\n{} {} days until {}{} birthday".format(
                name, days, years, suffix)
            if len(output) > 1900 and '*' not in output:
                output += '*'
        output += "```"
        if '*' not in output:
            await ctx.send(output.format(user))
        else:
            first, second = output.split('*')
            first += "```"
            second = "```" + second
            await ctx.send(first.format(user))
            await ctx.send(second)

    @character.command(name="build", aliases=["pvebuild"])
    @commands.cooldown(1, 10, BucketType.user)
    async def character_build(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = await self.build_embed(results, "pve")
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @character.command(name="pvpbuild")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_pvpbuild(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = await self.build_embed(results, "pvp")
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @character.command(name="wvwbuild")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_wvwbuild(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = await self.build_embed(results, "wvw")
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def build_embed(self, results, mode):
        profession = results["profession"].lower()
        level = results["level"]
        color = self.gamedata["professions"][profession]["color"]
        icon = self.gamedata["professions"][profession]["icon"]
        color = int(color, 0)
        specializations = results["specializations"][mode]
        embed = discord.Embed(
            title="{} build".format(mode.upper()), color=color)
        embed.set_author(name=results["name"])
        for spec in specializations:
            if spec is None:
                continue
            spec_doc = await self.db.specializations.find_one({
                "_id": spec["id"]
            })
            spec_name = spec_doc["name"]
            traits = []
            for trait in spec["traits"]:
                if trait is None:
                    continue
                trait_doc = await self.db.traits.find_one({"_id": trait})
                tier = trait_doc["tier"] - 1
                trait_index = spec_doc["major_traits"].index(trait)
                trait_index = 1 + trait_index - tier * 3
                traits.append("{} ({})".format(trait_doc["name"], trait_index))
            if traits:
                embed.add_field(
                    name=spec_name, value="\n".join(traits), inline=False)
            embed.set_footer(
                text="A level {} {} ".format(level, profession), icon_url=icon)
        return embed

    @character.command(name="togglepublic")
    @commands.cooldown(1, 1, BucketType.user)
    async def character_togglepublic(self, ctx, *, character_or_all: str):
        """Toggle your character's (or all of them) status to public

        Public characters can have their gear and build checked by anyone.
        The rest is still private.

        Required permissions: characters
        """
        character = character_or_all.title()
        user = ctx.author
        await ctx.trigger_typing()
        try:
            key = await self.fetch_key(user, ["characters"])
            results = await self.call_api("characters", key=key["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        if character not in results and character != "All":
            return await ctx.send("Invalid character name")
        characters = [character] if character != "All" else results
        output = []
        for char in characters:
            doc = await self.db.characters.find_one({"name": char})
            if doc:
                await self.db.characters.delete_one({"name": char})
                output.append(char + " is now private")
            else:
                await self.db.characters.insert_one({
                    "name":
                    char,
                    "owner":
                    user.id,
                    "owner_acc_name":
                    key["account_name"]
                })
                output.append(char + " is now public")
        await ctx.send("Character status successfully changed. Anyone can "
                       "check public characters gear and build - the rest is "
                       "still private. To make character private "
                       "again, type the same command.")
        if character == "All":
            await user.send("\n".join(output))

    @character.command(name="crafting")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_crafting(self, ctx):
        """Displays your characters and their crafting level"""
        endpoint = "characters?page=0"
        await ctx.trigger_typing()
        try:
            doc = await self.fetch_key(ctx.author, ["characters"])
            characters = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='Crafting overview', colour=self.embed_color)
        data.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        counter = 0
        for character in characters:
            if counter == 25:
                break
            craft_list = self.get_crafting(character)
            if craft_list:
                data.add_field(
                    name=character["name"], value="\n".join(craft_list))
                counter += 1
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    async def get_character(self, ctx, character):
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        try:
            results = await self.call_api(endpoint, ctx.author,
                                          ["characters", "builds"])
        except APINotFound:
            results = await self.get_public_character(character)
            if not results:
                raise APINotFound
        return results

    async def get_public_character(self, character):
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        doc = await self.db.characters.find_one({"name": character})
        if doc:
            user = await self.bot.get_user_info(doc["owner"])
            try:
                return await self.call_api(endpoint, user)
            except:
                return None
        return None

    def get_crafting(self, character):
        craft_list = []
        for crafting in character["crafting"]:
            rating = crafting["rating"]
            discipline = crafting["discipline"]
            craft_list.append("Level {} {}".format(rating, discipline))
        return craft_list
