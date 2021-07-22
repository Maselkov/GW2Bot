import datetime
import re
from collections import OrderedDict, defaultdict
from itertools import chain

import discord
import pymongo
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APINotFound
from .utils.chat import embed_list_lines


class AccountMixin:
    @commands.command()
    @commands.cooldown(1, 10, BucketType.user)
    async def account(self, ctx):
        """General information about your account

        Required permissions: account
        """
        user = ctx.author
        await ctx.trigger_typing()
        try:
            doc = await self.fetch_key(user, ["account"])
            results = await self.call_api("account", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        accountname = doc["account_name"]
        created = results["created"].split("T", 1)[0]
        hascommander = "Yes" if results["commander"] else "No"
        data = discord.Embed(colour=await self.get_embed_color(ctx))
        data.add_field(name="Created account on", value=created)
        # Add world name to account info
        wid = results["world"]
        world = await self.get_world_name(wid)
        data.add_field(name="WvW Server", value=world)
        if "progression" in doc["permissions"]:
            try:
                endpoints = ["account/achievements", "account"]
                achievements, account = await self.call_multiple(
                    endpoints, ctx.author, ["progression"])
            except APIError as e:
                return await self.error_handler(ctx, e)
            possible_ap = await self.total_possible_ap()
            user_ap = await self.calculate_user_ap(achievements, account)
            data.add_field(name="Achievement Points",
                           value="{} earned out of {} possible".format(
                               user_ap, possible_ap),
                           inline=False)
        data.add_field(name="Commander tag", value=hascommander, inline=False)
        if "fractal_level" in results:
            fractallevel = results["fractal_level"]
            data.add_field(name="Fractal level", value=fractallevel)
        if "wvw_rank" in results:
            wvwrank = results["wvw_rank"]
            data.add_field(name="WvW rank", value=wvwrank)
        if "pvp" in doc["permissions"]:
            try:
                pvp = await self.call_api("pvp/stats", user)
            except APIError as e:
                return await self.error_handler(ctx, e)
            pvprank = pvp["pvp_rank"] + pvp["pvp_rank_rollovers"]
            data.add_field(name="PVP rank", value=pvprank)
        if "characters" in doc["permissions"]:
            try:
                characters = await self.get_all_characters(user)
                total_played = 0
                for character in characters:
                    total_played += character.age
                data.add_field(name="Total time played",
                               value=self.format_age(total_played),
                               inline=False)
            except APIError as e:
                return await self.error_handler(ctx, e)
        if "access" in results:
            access = results["access"]
            if len(access) > 1:
                to_delete = ["PlayForFree", "GuildWars2"]
                for d in to_delete:
                    if d in access:
                        access.remove(d)

            def format_name(name):
                return " ".join(re.findall(r'[A-Z\d][^A-Z\d]*', name))

            access = "\n".join([format_name(e) for e in access])
            data.add_field(name="Expansion access", value=access)
        data.set_author(name=accountname, icon_url=user.avatar_url)
        data.set_footer(text=self.bot.user.name,
                        icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @commands.command(aliases=["ld"])
    @commands.cooldown(1, 10, BucketType.user)
    async def li(self, ctx):
        """Shows how many Legendary Insights and Divinations you have earned

        Required permissions: inventories, characters
        """
        user = ctx.author
        scopes = ["inventories", "characters"]
        if not self.can_embed_links(ctx):
            return await ctx.send("Need permission to embed links")
        await ctx.trigger_typing()

        trophies = self.gamedata["raid_trophies"]
        ids = []
        for trophy in trophies:
            for items in trophy["items"]:
                ids += items["items"]
        try:
            doc = await self.fetch_key(user, scopes)
            search_results = await self.find_items_in_account(ctx,
                                                              ids,
                                                              doc=doc)
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = discord.Embed(color=0x4C139D)
        total = 0
        crafted_total = 0
        for trophy in trophies:
            trophy_total = 0
            breakdown = []
            for group in trophy["items"]:
                if "reduced_worth" in group:
                    upgraded_sum = 0
                    if "upgrades_to" in group:
                        upgrade_dict = next(
                            item for item in trophy["items"]
                            if item.get("name") == group["upgrades_to"])
                        for item in upgrade_dict["items"]:
                            upgraded_sum += sum(search_results[item].values())
                    amount = 0
                    for item in group["items"]:
                        amount += sum(search_results[item].values())
                    reduced_amount = group["reduced_amount"]
                    reduced_amount = max(reduced_amount - upgraded_sum, 0)
                    sum_set = min(
                        amount, reduced_amount) * group["reduced_worth"] + max(
                            amount - reduced_amount, 0) * group["worth"]
                    if sum_set:
                        trophy_total += sum_set
                        breakdown.append(
                            f"{amount} {group['name']} - **{sum_set}**")
                        if group["crafted"]:
                            crafted_total += sum_set
                    continue
                for item in group["items"]:
                    amount = sum(search_results[item].values())
                    sum_item = amount * group["worth"]
                    if sum_item:
                        trophy_total += sum_item
                        if group["crafted"]:
                            crafted_total += sum_item
                        item_doc = await self.fetch_item(item)
                        line = f"{item_doc['name']} - **{sum_item}**"
                        if group["worth"] != 1:
                            line = f"{amount} " + line
                        breakdown.append(line)
            if trophy_total:
                name = f"{trophy_total} Legendary {trophy['name']} earned"
                embed.add_field(name=name,
                                value="\n".join(breakdown),
                                inline=False)
                total += trophy_total
        trophy_names = [trophy["name"] for trophy in trophies]
        embed.title = "{} Legendary {} and {} earned".format(
            total, ', '.join(trophy_names[:-1]), trophy_names[-1])
        embed.description = "{} on hand, {} used in crafting".format(
            total - crafted_total, crafted_total)
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        embed.set_thumbnail(
            url="https://api.gw2bot.info/resources/icons/lild.png")
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
        await ctx.send(
            "{.mention}, here are your Legendary Insights and Divinations".
            format(user),
            embed=embed)

    @commands.command()
    @commands.cooldown(1, 15, BucketType.user)
    async def kp(self, ctx):
        """Shows completed raids and fractals

        Required permissions: progression
        """
        user = ctx.author
        scopes = ["progression"]
        if not self.can_embed_links(ctx):
            return await ctx.send("Need permission to embed links")
        await ctx.trigger_typing()
        areas = self.gamedata["killproofs"]["areas"]
        # Create a list of lists of all achievement ids we need to check.
        achievement_ids = [
            [x["id"]] if x["type"] == "single_achievement"
            or x["type"] == "progressed_achievement" else x["ids"]
            for x in chain.from_iterable(
                [area["encounters"] for area in areas])
        ]
        # Flatten it.
        achievement_ids = [
            str(x) for x in chain.from_iterable(achievement_ids)
        ]

        try:
            doc = await self.fetch_key(user, scopes)
            endpoint = "account/achievements?ids=" + ",".join(achievement_ids)
            results = await self.call_api(endpoint, key=doc["key"])
        except APINotFound:
            # Not Found is returned by the API when none of the searched
            # achievements have been completed yet.
            results = []
        except APIError as e:
            return await self.error_handler(ctx, e)

        def is_completed(encounter):
            # One achievement has to be completed
            if encounter["type"] == "single_achievement":
                _id = encounter["id"]
                for achievement in results:
                    if achievement["id"] == _id and achievement["done"]:
                        return "+✔"
                # The achievement is not in the list or isn't done
                return "-✖"
            # All achievements have to be completed
            if encounter["type"] == "all_achievements":
                for _id in encounter["ids"]:
                    # The results do not contain achievements with no progress
                    if not any(a["id"] == _id and a["done"] for a in results):
                        return "-✖"
                return "+✔"
            # Progress toward one achievement has to be reached
            if encounter["type"] == "progressed_achievement":
                _id = encounter["id"]
                _progress = encounter["progress"]
                for achievement in results:
                    if achievement["id"] == _id and achievement[
                            "current"] >= _progress:
                        return "+✔"
                # The achievement is not in the list or player hasn't progressed far enough
                return "-✖"

        embed = discord.Embed(title="Kill Proof",
                              color=await self.get_embed_color(ctx))
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        for area in areas:
            value = ["```diff"]
            encounters = area["encounters"]
            for encounter in encounters:
                value.append(is_completed(encounter) + encounter["name"])
            value.append("```")
            embed.add_field(name=area["name"], value="\n".join(value))

        embed.description = ("Achievements were checked to find "
                             "completed encounters.")
        embed.set_footer(text="Green (+) means completed. Red (-) means not. "
                         "CM stands for Challenge Mode.")

        await ctx.send("{.mention}, here is your kill proof.".format(user),
                       embed=embed)

    @commands.command()
    @commands.cooldown(1, 10, BucketType.user)
    async def bosses(self, ctx):
        """Shows your raid progression for the week

        Required permissions: progression
        """
        user = ctx.author
        scopes = ["progression"]
        endpoints = ["account/raids", "account"]
        try:
            doc = await self.fetch_key(user, scopes)
            schema = datetime.datetime(2019, 2, 21)
            results, account = await self.call_multiple(endpoints,
                                                        key=doc["key"],
                                                        schema_version=schema)
        except APIError as e:
            return await self.error_handler(ctx, e)
        last_modified = datetime.datetime.strptime(account["last_modified"],
                                                   "%Y-%m-%dT%H:%M:%Sz")
        raids = await self.get_raids()
        embed = await self.boss_embed(ctx, raids, results, doc["account_name"],
                                      last_modified)
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        if not self.can_embed_links(ctx):
            return await ctx.send("Need permission to embed links")
        await ctx.send("{.mention}, here are your raid bosses:".format(user),
                       embed=embed)

    @commands.command(aliases=["find"])
    @commands.cooldown(1, 5, BucketType.user)
    async def search(self, ctx, *, item):
        """Find items on your account
        Required permissions: inventories, characters
        """
        if not self.can_embed_links(ctx):
            return await ctx.send("Need permission to embed links")
        user = ctx.author
        try:
            doc = await self.fetch_key(user, ["inventories", "characters"])
        except APIError as e:
            await self.error_handler(ctx, e)
        choice = await self.itemname_to_id(ctx,
                                           item,
                                           user,
                                           group_duplicates=True)
        if not choice:
            ctx.command.reset_cooldown(ctx)
            return
        await ctx.trigger_typing()
        try:
            search_results = await self.find_items_in_account(ctx,
                                                              choice["ids"],
                                                              flatten=True,
                                                              search=True)
        except APIError as e:
            return await self.error_handler(ctx, e)
        seq = [k for k, v in search_results.items() if v]
        if not seq:
            return await ctx.send("Sorry, not found on your account. "
                                  "Make sure you've selected the "
                                  "correct item.")
        longest = len(max(seq, key=len))
        if longest < 8:
            longest = 8
        if 'is_upgrade' in choice and choice['is_upgrade']:
            output = [
                "LOCATION{}INV / GEAR".format(" " * (longest - 5)),
                "--------{}|-----".format("-" * (longest - 6))
            ]
            align = 110
        else:
            output = [
                "LOCATION{}COUNT".format(" " * (longest - 5)),
                "--------{}|-----".format("-" * (longest - 6))
            ]
            align = 80
        total = 0
        storage_counts = OrderedDict(
            sorted(search_results.items(), key=lambda kv: kv[1], reverse=True))
        characters = await self.get_all_characters(user)
        char_names = []
        for character in characters:
            char_names.append(character.name)
        for k, v in storage_counts.items():
            if v:
                if 'is_upgrade' in choice and choice['is_upgrade']:
                    total += v[0]
                    total += v[1]
                    if k in char_names:
                        slotted_upg = v[1]
                        if slotted_upg == 0:
                            inf = ""
                        else:
                            inf = "/ {} ".format(slotted_upg)
                        output.append("{} {} | {} {}".format(
                            k.upper(), " " * (longest - len(k)), v[0], inf))
                    else:
                        output.append("{} {} | {}".format(
                            k.upper(), " " * (longest - len(k)), v[0]))
                else:
                    total += v[0]
                    total += v[1]
                    output.append("{} {} | {}".format(k.upper(),
                                                      " " * (longest - len(k)),
                                                      v[0] + v[1]))
        output.append("--------{}------".format("-" * (longest - 5)))
        output.append("TOTAL:{}{}".format(" " * (longest - 2), total))
        message = ("{.mention}, here are your search results".format(user))

        color = int(self.gamedata["items"]["rarity_colors"][choice["rarity"]],
                    16)
        item_doc = await self.fetch_item(choice["ids"][0])
        icon_url = item_doc["icon"]
        data = discord.Embed(
            description="Search results".format(item_doc["name"]) +
            " " * align + u'\u200b',
            color=color)
        value = "\n".join(output)

        if len(value) > 1014:
            value = ""
            values = []
            for line in output:
                if len(value) + len(line) > 1013:
                    values.append(value)
                    value = ""
                value += line + "\n"
            if value:
                values.append(value)
            data.add_field(name=choice["name"],
                           value="```ml\n{}```".format(values[0]),
                           inline=False)
            for v in values[1:]:
                data.add_field(
                    name=u'\u200b',  # Zero width space
                    value="```ml\n{}```".format(v),
                    inline=False)
        else:
            data.add_field(name=choice["name"],
                           value="```ml\n{}\n```".format(value))
        data.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        if 'is_upgrade' in choice and choice['is_upgrade']:
            data.set_footer(text="Amount in inventory / Amount in gear",
                            icon_url=self.bot.user.avatar_url)
        else:
            data.set_footer(text=self.bot.user.name,
                            icon_url=self.bot.user.avatar_url)
        data.set_thumbnail(url=icon_url)
        await ctx.send(message, embed=data)

    @commands.command()
    @commands.cooldown(1, 10, BucketType.user)
    async def cats(self, ctx):
        """Displays the cats you haven't unlocked yet

        Required permissions: progression"""
        user = ctx.message.author
        endpoint = "account/home/cats"
        try:
            doc = await self.fetch_key(user, ["progression"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        owned_cats = [cat["id"] for cat in results]
        lines = []
        for cat in self.gamedata["cats"]:
            if cat["id"] not in owned_cats:
                lines.append(cat["guide"])
        if not lines:
            return await ctx.send("You have collected all the "
                                  "cats! Congratulations! :cat2:")
        embed = discord.Embed(color=await self.get_embed_color(ctx))
        embed = embed_list_lines(embed, lines,
                                 "Cats you haven't collected yet")
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
        await ctx.send("{.mention}, here are your cats:".format(user),
                       embed=embed)

    @commands.command()
    @commands.cooldown(1, 10, BucketType.user)
    async def nodes(self, ctx):
        """Displays the nodes you haven't unlocked.

        Required permissions: progression"""
        user = ctx.message.author
        endpoint = "account/home/nodes"
        try:
            doc = await self.fetch_key(user, ["progression"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        owned_nodes = results
        lines = []
        for nodes in self.gamedata["nodes"]:
            if nodes["id"] not in owned_nodes:
                lines.append(nodes["guide"])
        if not lines:
            return await ctx.send(
                "You've collected all home instance nodes! Congratulations!")
        embed = discord.Embed(color=await self.get_embed_color(ctx))
        embed = embed_list_lines(embed, lines,
                                 "Nodes you haven't collected yet:")
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
        await ctx.send("{.mention}, here are your nodes:".format(user),
                       embed=embed)

    async def boss_embed(self, ctx, raids, results, account_name,
                         last_modified):
        boss_to_id = defaultdict(list)
        for boss_id, boss in self.gamedata["bosses"].items():
            if "api_name" in boss:
                boss_to_id[boss["api_name"]].append(int(boss_id))

        def is_killed(boss):
            return ":white_check_mark:" if boss["id"] in results else ":x:"

        def readable_id(_id):
            _id = _id.split("_")
            dont_capitalize = ("of", "the", "in")
            title = " ".join([
                x.capitalize() if x not in dont_capitalize else x for x in _id
            ])
            return title[0].upper() + title[1:]

        monday = last_modified - datetime.timedelta(
            days=last_modified.weekday())
        if not last_modified.weekday():
            if last_modified < last_modified.replace(
                    hour=7, minute=30, second=0, microsecond=0):
                monday = last_modified - datetime.timedelta(weeks=1)
        reset_time = datetime.datetime(monday.year,
                                       monday.month,
                                       monday.day,
                                       hour=7,
                                       minute=30)
        next_reset_time = reset_time + datetime.timedelta(weeks=1)

        async def get_dps_reports(boss_id):
            boss_id = boss_to_id[boss_id]
            cursor = self.db.encounters.find({
                "boss_id": {
                    "$in": boss_id
                },
                "players": account_name,
                "date": {
                    "$gte": reset_time,
                    "$lt": next_reset_time
                },
                "success": boss["id"] in results
            }).sort("date", pymongo.DESCENDING).limit(5)
            return await cursor.to_list(None)

        not_completed = []
        embed = discord.Embed(title="Bosses",
                              color=await self.get_embed_color(ctx))
        wings = [wing for raid in raids for wing in raid["wings"]]
        cotm = self.get_emoji(ctx, "call_of_the_mists")
        start_date = datetime.date(year=2019, month=1, day=21)
        seconds = int(
            (datetime.datetime.utcnow().date() - start_date).total_seconds())
        weeks = seconds // (60 * 60 * 24 * 7 * 2)
        cotm_index = weeks % (len(wings) - 1)
        for index, wing in enumerate(wings):
            wing_done = True
            value = []
            for boss in wing["events"]:
                if boss["id"] not in results:
                    wing_done = False
                    not_completed.append(boss)
                reports = await get_dps_reports(boss["id"])
                if reports:
                    boss_name = (f"[{readable_id(boss['id'])}]"
                                 f"({reports[0]['permalink']})")
                    if len(reports) > 1:
                        links = []
                        for i, report in enumerate(reports[1:], 2):
                            links.append(f"[{i}]({report['permalink']})")
                        boss_name += f" ({', '.join(links)})"
                else:
                    boss_name = readable_id(boss["id"])
                value.append("> " + is_killed(boss) + boss_name)
            cotm_active = index in (len(wings) - 1, cotm_index)
            name = cotm if cotm_active else ""
            name += readable_id(wing["id"])
            if wing_done:
                name += " :white_check_mark:"
            else:
                name += " :x:"
            embed.add_field(name=f"**{name}**", value="\n".join(value))
        if len(not_completed) == 0:
            description = "Everything completed this week :star:"
        else:
            bosses = list(filter(lambda b: b["type"] == "Boss", not_completed))
            events = list(
                filter(lambda b: b["type"] == "Checkpoint", not_completed))
            if bosses:
                suffix = ""
                if len(bosses) > 1:
                    suffix = "es"
                bosses = "{} boss{}".format(len(bosses), suffix)
            if events:
                suffix = ""
                if len(events) > 1:
                    suffix = "s"
                events = "{} event{}".format(len(events), suffix)
            description = (", ".join(filter(None, [bosses, events])) +
                           " not completed this week")
        if datetime.datetime.utcnow() > next_reset_time:
            description = description.replace("this", "that")
            description += ("\n❗Warning❗\n Data outdated for this week. Log "
                            "into GW2 in order to update.")
        embed.description = description
        embed.set_footer(text=f"Logs uploaded via {ctx.prefix}evtc will "
                         "appear here with links - they don't have to be "
                         "uploaded by you",
                         icon_url=self.bot.user.avatar_url)
        return embed

    async def find_items_in_account(self,
                                    ctx,
                                    item_ids,
                                    *,
                                    doc=None,
                                    flatten=False,
                                    search=False):
        user = ctx.author
        if not doc:
            doc = await self.fetch_key(user, ["inventories", "characters"])
        endpoints = [
            "account/bank", "account/inventory", "account/materials",
            "characters?page=0&page_size=200"
        ]
        results = await self.call_multiple(
            endpoints,
            key=doc["key"],
            schema_string="2021-07-15T13:00:00.000Z")
        bank, shared, materials, characters = results
        spaces = {
            "bank": bank,
            "shared": shared,
            "material storage": materials
        }
        legendary_armory_item_ids = set()
        if search:
            counts = {
                item_id: defaultdict(lambda: [0, 0])
                for item_id in item_ids
            }
        else:
            counts = {item_id: defaultdict(int) for item_id in item_ids}

        def amounts_in_space(space, name, geared):
            space_name = name
            for s in space:
                if geared and s["location"].endswith("LegendaryArmory"):
                    if s["id"] in legendary_armory_item_ids:
                        continue
                    legendary_armory_item_ids.add(s["id"])
                    space_name = "legendary armory"
                for item_id in item_ids:
                    amt = get_amount(s, item_id)
                    if amt:
                        if search:
                            if geared:
                                # Tuple of (inventory, geared)
                                counts[item_id][space_name][1] += amt
                            else:
                                counts[item_id][space_name][0] += amt
                        else:
                            counts[item_id][space_name] += amt

        def get_amount(slot, item_id):
            def count_upgrades(slots):
                return sum(1 for i in slots if i == item_id)

            if not slot:
                return 0
            if slot["id"] == item_id:
                if "count" in slot:
                    return slot["count"]
                return 1

            if "infusions" in slot:
                infusions_sum = count_upgrades(slot["infusions"])
                if infusions_sum:
                    return infusions_sum
            if "upgrades" in slot:
                upgrades_sum = count_upgrades(slot["upgrades"])
                if upgrades_sum:
                    return upgrades_sum
            return 0

        for name, space in spaces.items():
            amounts_in_space(space, name, False)
        for character in characters:
            amounts_in_space(character["bags"], character["name"], False)
            bags = [
                bag["inventory"] for bag in filter(None, character["bags"])
            ]
            for bag in bags:
                amounts_in_space(bag, character["name"], False)
            for tab in character["equipment_tabs"]:
                amounts_in_space(tab["equipment"], character["name"], True)
        try:
            if "tradingpost" in doc["permissions"]:
                result = await self.call_api("commerce/delivery",
                                             key=doc["key"])
                delivery = result.get("items", [])
                amounts_in_space(delivery, "TP delivery", False)
        except APIError:
            pass
        if flatten:
            if search:
                flattened = defaultdict(lambda: [])
            else:
                flattened = defaultdict(int)
            for count_dict in counts.values():
                for k, v in count_dict.items():
                    flattened[k] += v
            return flattened
        return counts
