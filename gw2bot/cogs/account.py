"""Account commands: /account, /li, /kp, /bosses, /search, /cats and /nodes."""
import collections
import datetime
import re
from collections import OrderedDict, defaultdict
from itertools import chain

import discord
import pymongo
from discord import app_commands
from discord.app_commands import Choice

from gw2bot.utils.chat import embed_list_lines, format_age

from ..gw2api.errors import APIError, APINotFound
from ..i18n import N_, localized
from .achievements import account_ap, total_possible_ap
from .base import GW2Cog
from .wvw import WVW_ACCOUNT_SCHEMA, team_name

# Places items are found in, as find_items_in_account names them
PLACES = {
    "bank": N_("bank"),
    "shared": N_("shared"),
    "material storage": N_("material storage"),
    "legendary armory": N_("legendary armory"),
    "TP delivery": N_("TP delivery"),
}
# /li's raid trophies (gamedata.json raid_trophies), and their groups
TROPHY_TITLES = {"Insights": N_("{count} Legendary Insights earned")}
TROPHY_GROUPS = {"Refined Armor": N_("Refined Armor"), "Perfected Armor": N_("Perfected Armor")}

# /bosses: raid wings and encounters by the API's ids (/v2/raids). Others
# are shown from their ids ("spirit_vale" -> "Spirit Vale"), in English
RAID_NAMES = {
    "spirit_vale": N_("Spirit Vale"), "vale_guardian": N_("Vale Guardian"), "spirit_woods": N_("Spirit Woods"),
    "gorseval": N_("Gorseval"), "sabetha": N_("Sabetha"),
    "salvation_pass": N_("Salvation Pass"), "slothasor": N_("Slothasor"), "bandit_trio": N_("Bandit Trio"),
    "matthias": N_("Matthias"),
    "stronghold_of_the_faithful": N_("Stronghold of the Faithful"), "escort": N_("Escort"),
    "keep_construct": N_("Keep Construct"), "twisted_castle": N_("Twisted Castle"), "xera": N_("Xera"),
    "bastion_of_the_penitent": N_("Bastion of the Penitent"), "cairn": N_("Cairn"),
    "mursaat_overseer": N_("Mursaat Overseer"), "samarog": N_("Samarog"), "deimos": N_("Deimos"),
    "hall_of_chains": N_("Hall of Chains"), "soulless_horror": N_("Soulless Horror"),
    "river_of_souls": N_("River of Souls"), "statues_of_grenth": N_("Statues of Grenth"),
    "voice_in_the_void": N_("Voice in the Void"),
    "mythwright_gambit": N_("Mythwright Gambit"), "conjured_amalgamate": N_("Conjured Amalgamate"),
    "twin_largos": N_("Twin Largos"), "qadim": N_("Qadim"),
    "the_key_of_ahdashim": N_("The Key of Ahdashim"), "gate": N_("Gate"), "adina": N_("Adina"),
    "sabir": N_("Sabir"), "qadim_the_peerless": N_("Qadim the Peerless"),
    "mount_balrior": N_("Mount Balrior"), "camp": N_("Camp"), "greer": N_("Greer"), "decima": N_("Decima"),
    "ura": N_("Ura"),
}

CHARACTERS = "characters?page=0&page_size=200"
# First schema with characters' equipment and build tabs
CHARACTERS_SCHEMA = "2021-07-15T13:00:00.000Z"


class Account(GW2Cog):

    async def get_raids(self):
        """The cached /v2/raids wings."""
        config = await self.bot.data.config.get()
        return config["cache"].get("raids")

    @app_commands.command()
    async def account(self, interaction: discord.Interaction):
        """General information about your account

        Required permissions: account
        """
        lang = await self.lang(interaction)

        def t(text, **fields):
            return self.t(lang, text, **fields)

        await interaction.response.defer()
        user = interaction.user
        doc = await self.fetch_key(user, ["account"])
        results = await self.call_api("account",
                                      user,
                                      schema_string=WVW_ACCOUNT_SCHEMA)
        accountname = doc["account_name"]
        created = results["created"].split("T", 1)[0]
        hascommander = t(N_("Yes")) if results["commander"] else t(N_("No"))
        embed = discord.Embed(colour=await self.get_embed_color(interaction))
        embed.add_field(name=t(N_("Created account on")), value=created)
        wvw = results.get("wvw", {})
        if wvw.get("team_id"):
            embed.add_field(name=t(N_("WvW team")),
                            value=team_name(self.gamedata, wvw["team_id"]))
        if "progression" in doc["permissions"]:
            endpoints = ["account/achievements", "account"]
            achievements, account = await self.call_multiple(
                endpoints, user, ["progression"])
            possible_ap = await total_possible_ap(self.db.achievements)
            user_ap = await account_ap(self.db.achievements, achievements, account)
            embed.add_field(name=t(N_("Achievement Points")),
                            value=t(N_("{earned} earned out of {possible} possible"),
                                    earned=user_ap, possible=possible_ap),
                            inline=False)
        embed.add_field(name=t(N_("Commander tag")), value=hascommander, inline=False)
        if "fractal_level" in results:
            fractallevel = results["fractal_level"]
            embed.add_field(name=t(N_("Fractal level")), value=fractallevel)
        if "rank" in wvw:
            embed.add_field(name=t(N_("WvW rank")), value=wvw["rank"])
        if "pvp" in doc["permissions"]:
            pvp = await self.call_api("pvp/stats", user)
            pvprank = pvp["pvp_rank"] + pvp["pvp_rank_rollovers"]
            embed.add_field(name=t(N_("PVP rank")), value=pvprank)
        if "characters" in doc["permissions"]:
            characters = await self.call_api(CHARACTERS, user,
                                             schema_string=CHARACTERS_SCHEMA)
            total_played = 0
            for character in characters:
                total_played += character["age"]
            embed.add_field(name=t(N_("Total time played")),
                            value=format_age(total_played, translate=t),
                            inline=False)
        if "access" in results:
            access = results["access"]
            if len(access) > 1:
                to_delete = ["PlayForFree", "GuildWars2"]
                for d in to_delete:
                    if d in access:
                        access.remove(d)

                # Having PathOfFire access implies HeartOfThorns access.
                if "PathOfFire" in access and "HeartOfThorns" not in access:
                    access.append("HeartOfThorns")

            def format_name(name):
                return " ".join(re.findall(r'[A-Z\d][^A-Z\d]*', name))

            access = "\n".join([format_name(e) for e in access])
            if access:
                embed.add_field(name=t(N_("Expansion access")), value=access)
        embed.set_author(name=accountname, icon_url=user.display_avatar.url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def li(self, interaction: discord.Interaction):
        """Shows how many Legendary Insights you have earned"""
        lang = await self.lang(interaction)

        def t(text, **fields):
            return self.t(lang, text, **fields)

        await interaction.response.defer()
        user = interaction.user
        scopes = ["inventories", "characters", "wallet"]
        trophies = self.gamedata["raid_trophies"]
        ids = []
        for trophy in trophies:
            for items in trophy["items"]:
                ids += items["items"]
        doc = await self.fetch_key(user, scopes)
        search_results = await self.find_items_in_account(user, ids, doc=doc)
        wallet = await self.call_api("account/wallet", key=doc["key"])
        embed = discord.Embed(color=0x4C139D)
        total = 0
        crafted_total = 0
        for trophy in trophies:
            trophy_total = 0
            breakdown = []
            if trophy["wallet"]:
                for currency_result in wallet:
                    if currency_result["id"] == trophy["wallet"]:
                        trophy_total += currency_result["value"]
                        breakdown.append(
                            f"{t(N_('Wallet'))} - **{currency_result['value']}**")
                        break
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
                        group_name = t(TROPHY_GROUPS.get(group["name"], group["name"]))
                        breakdown.append(
                            f"{amount} {group_name} - **{sum_set}**")
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
                        name = localized(item_doc, lang) if item_doc else t(N_("Unknown item"))
                        line = f"{name} - **{sum_item}**"
                        if group["worth"] != 1:
                            line = f"{amount} " + line
                        breakdown.append(line)
            if trophy_total:
                title = TROPHY_TITLES.get(trophy["name"])
                name = (t(title, count=trophy_total) if title
                        else f"{trophy_total} Legendary {trophy['name']} earned")
                embed.add_field(name=name,
                                value="\n".join(breakdown),
                                inline=False)
                total += trophy_total
        embed.title = t(N_("{count} Raid trophies earned"), count=total)
        embed.description = t(N_("{on_hand} on hand, {crafted} used in crafting"),
                              on_hand=total - crafted_total, crafted=crafted_total)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        embed.set_thumbnail(
            url="https://wiki.guildwars2.com/images/5/5e/Legendary_Insight.png"
        )
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def kp(self, interaction: discord.Interaction):
        """Shows completed raids, fractals, and strikes, as well as important challenges"""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        user = interaction.user
        scopes = ["progression"]
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
        except APIError:
            raise

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
                # The achievement is not in the list or player hasn't
                # progressed far enough
                return "-✖"

        embed = discord.Embed(title=self.t(lang, N_("Kill Proof")),
                              color=await self.get_embed_color(interaction))
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        for area in areas:
            value = ["```diff"]
            encounters = area["encounters"]
            for encounter in encounters:
                value.append(is_completed(encounter) + self.t(lang, encounter["name"]))
            value.append("```")
            embed.add_field(name=self.t(lang, area["name"]), value="\n".join(value))

        embed.description = self.t(lang, N_("Achievements were checked to find "
                                            "completed encounters."))
        embed.set_footer(text=self.t(lang, N_("Green (+) means completed. Red (-) means not. "
                                              "CM stands for Challenge Mode.")))

        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def bosses(self, interaction: discord.Interaction):
        """Shows your raid progression for the week"""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        user = interaction.user
        scopes = ["progression"]
        endpoints = ["account/raids", "account"]
        doc = await self.fetch_key(user, scopes)
        schema = datetime.datetime(2019, 2, 21)
        results, account = await self.call_multiple(endpoints,
                                                    key=doc["key"],
                                                    schema_version=schema)
        last_modified = datetime.datetime.strptime(account["last_modified"],
                                                   "%Y-%m-%dT%H:%M:%Sz")
        raids = await self.get_raids()
        embed = await self.boss_embed(interaction, raids, results,
                                      doc["account_name"], last_modified, lang)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    async def item_autocomplete(self, interaction: discord.Interaction,
                                current: str):
        if not current:
            return []

        lang = await self.lang(interaction)

        def consolidate_duplicates(items):
            unique_items = collections.OrderedDict()
            for item in items:
                item_tuple = localized(item, lang), item["rarity"], item["type"]
                if item_tuple not in unique_items:
                    unique_items[item_tuple] = []
                unique_items[item_tuple].append(item["_id"])
            unique_list = []
            for k, v in unique_items.items():
                ids = " ".join(str(i) for i in v)
                if len(ids) > 100:
                    continue
                unique_list.append({
                    "name": k[0],
                    "rarity": k[1],
                    "ids": ids,
                    "type": k[2]
                })
            return unique_list

        items = await self.find_by_name(self.db.items, current, lang)
        items = sorted(consolidate_duplicates(items), key=lambda c: c["name"])
        return [
            Choice(name=f"{it['name']} - {self.t(lang, it['rarity'])}"[:100], value=it["ids"])
            for it in items
        ]

    @app_commands.command()
    @app_commands.describe(item="Specify the name of an item to search for. "
                           "Select an item from the list.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def search(self, interaction: discord.Interaction, item: str):
        """Find items on your account"""
        lang = await self.lang(interaction)

        def t(text, **fields):
            return self.t(lang, text, **fields)

        await interaction.response.defer()
        try:
            ids = [int(it) for it in item.split(" ")]
        except ValueError:
            try:
                choices = await self.item_autocomplete(interaction, item)
                ids = [int(it) for it in choices[0].value.split(" ")]
            except (ValueError, IndexError):
                return await interaction.followup.send(
                    t(N_("Could not find any items with that name.")))
        item_doc = await self.fetch_item(ids[0])
        if not item_doc:
            # The results show its name, rarity and icon
            return await interaction.followup.send(
                t(N_("Could not find any items with that name.")))
        item_name = localized(item_doc, lang)

        def place(name):
            """A place's name, upper case, as the results show it."""
            return t(PLACES[name]).upper() if name in PLACES else name.upper()

        async def generate_results_embed(results, characters):
            seq = [place(k) for k, v in results.items() if v]
            if not seq:
                return None
            location, total_label = t(N_("LOCATION")), t(N_("TOTAL:"))
            # The columns are aligned for "LOCATION" and "TOTAL:" at least
            longest = max(len(max(seq, key=len)), 8, len(location) - 3, len(total_label) - 4)
            if 'is_upgrade' in item_doc and item_doc['is_upgrade']:
                output = [
                    location.ljust(longest + 3) + t(N_("INV / GEAR")),
                    "--------{}|-----".format("-" * (longest - 6))
                ]
                align = 110
            else:
                output = [
                    location.ljust(longest + 3) + t(N_("COUNT")),
                    "--------{}|-----".format("-" * (longest - 6))
                ]
                align = 80
            total = 0
            storage_counts = OrderedDict(
                sorted(results.items(), key=lambda kv: kv[1], reverse=True))
            char_names = []
            for character in characters:
                char_names.append(character["name"])
            for k, v in storage_counts.items():
                name = place(k)
                if v:
                    if 'is_upgrade' in item_doc and item_doc['is_upgrade']:
                        total += v[0]
                        total += v[1]
                        if k in char_names:
                            slotted_upg = v[1]
                            if slotted_upg == 0:
                                inf = ""
                            else:
                                inf = "/ {} ".format(slotted_upg)
                            output.append("{} {} | {} {}".format(
                                name, " " * (longest - len(name)), v[0],
                                inf))
                        else:
                            output.append("{} {} | {}".format(
                                name, " " * (longest - len(name)), v[0]))
                    else:
                        total += v[0]
                        total += v[1]
                        output.append("{} {} | {}".format(
                            name, " " * (longest - len(name)), v[0] + v[1]))
            output.append("--------{}------".format("-" * (longest - 5)))
            output.append(total_label.ljust(longest + 4) + str(total))
            color = int(
                self.gamedata["items"]["rarity_colors"][item_doc["rarity"]],
                16)
            icon_url = item_doc["icon"]
            data = discord.Embed(description=t(N_("Search results")) + " " * align +
                                 u'\u200b',
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
                data.add_field(name=item_name,
                               value="```ml\n{}```".format(values[0]),
                               inline=False)
                for v in values[1:]:
                    data.add_field(
                        name=u'\u200b',  # Zero width space
                        value="```ml\n{}```".format(v),
                        inline=False)
            else:
                data.add_field(name=item_name,
                               value="```ml\n{}\n```".format(value))
            data.set_author(name=doc["account_name"],
                            icon_url=user.display_avatar.url)
            if 'is_upgrade' in item_doc and item_doc['is_upgrade']:
                data.set_footer(text=t(N_("Amount in inventory / Amount in gear")),
                                icon_url=self.bot.user.display_avatar.url)
            else:
                data.set_footer(text=self.bot.user.name,
                                icon_url=self.bot.user.display_avatar.url)
            data.set_thumbnail(url=icon_url)
            return data

        user = interaction.user
        doc = await self.fetch_key(user, ["inventories", "characters"])
        endpoints = [
            "account/bank", "account/inventory", "account/materials",
            CHARACTERS
        ]
        storage = await self.call_multiple(endpoints,
                                           key=doc["key"],
                                           schema_string=CHARACTERS_SCHEMA)
        search_results = await self.find_items_in_account(interaction.user,
                                                          ids,
                                                          flatten=True,
                                                          search=True,
                                                          results=storage)
        embed = await generate_results_embed(search_results, storage[3])
        if not embed:
            return await interaction.followup.send(
                content=t(N_("`{item}`: Not found on your account."), item=item_name))
        return await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def cats(self, interaction: discord.Interaction):
        """Displays the cats you haven't unlocked yet"""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        user = interaction.user
        endpoint = "account/home/cats"
        doc = await self.fetch_key(user, ["progression"])
        results = await self.call_api(endpoint, key=doc["key"])
        owned_cats = [cat["id"] for cat in results]
        lines = []
        for cat in self.gamedata["cats"]:
            if cat["id"] not in owned_cats:
                lines.append(cat["guide"])
        if not lines:
            return await interaction.followup.send(
                self.t(lang, N_("You have collected all the cats! Congratulations!")) + " :cat2:")
        embed = discord.Embed(color=await self.get_embed_color(interaction))
        embed = embed_list_lines(embed, lines,
                                 self.t(lang, N_("Cats you haven't collected yet")))
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def nodes(self, interaction: discord.Interaction):
        """Displays the home instance nodes you have not yet unlocked."""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        user = interaction.user
        endpoint = "account/home/nodes"
        doc = await self.fetch_key(user, ["progression"])
        results = await self.call_api(endpoint, key=doc["key"])
        owned_nodes = results
        lines = []
        for nodes in self.gamedata["nodes"]:
            if nodes["id"] not in owned_nodes:
                lines.append(nodes["guide"])
        if not lines:
            return await interaction.followup.send(
                self.t(lang, N_("You've collected all home instance nodes! Congratulations!")))
        embed = discord.Embed(color=await self.get_embed_color(interaction))
        embed = embed_list_lines(embed, lines,
                                 self.t(lang, N_("Nodes you haven't collected yet:")))
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    async def boss_embed(self, ctx, raids, results, account_name,
                         last_modified, lang="en"):
        def t(text, **fields):
            return self.t(lang, text, **fields)

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

        def raid_name(_id):
            return t(RAID_NAMES.get(_id) or readable_id(_id))

        monday = last_modified - datetime.timedelta(
            days=last_modified.weekday())
        if not last_modified.weekday():
            if last_modified < last_modified.replace(hour=7,
                                                     minute=30,
                                                     second=0,
                                                     microsecond=0):
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
        embed = discord.Embed(title=t(N_("Bosses")),
                              color=await self.get_embed_color(ctx))
        wings = [wing for raid in raids for wing in raid["wings"]]
        cotm = self.get_emoji(ctx, "call_of_the_mists")
        emboldened = self.get_emoji(ctx, "emboldened")
        start_date = datetime.date(year=2022, month=6, day=20)
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        current = now.date()
        monday_1 = (start_date - datetime.timedelta(days=start_date.weekday()))
        monday_2 = (current - datetime.timedelta(days=current.weekday()))
        weeks = (monday_2 - monday_1).days // 7
        cotm_index = weeks % len(wings)
        emboldened_index = (weeks - 1) % len(wings)
        for index, wing in enumerate(wings):
            wing_done = True
            value = []
            for boss in wing["events"]:
                if boss["id"] not in results:
                    wing_done = False
                    not_completed.append(boss)
                reports = await get_dps_reports(boss["id"])
                if reports:
                    boss_name = (f"[{raid_name(boss['id'])}]"
                                 f"({reports[0]['permalink']})")
                    if len(reports) > 1:
                        links = []
                        for i, report in enumerate(reports[1:], 2):
                            links.append(f"[{i}]({report['permalink']})")
                        boss_name += f" ({', '.join(links)})"
                else:
                    boss_name = raid_name(boss["id"])
                value.append("> " + is_killed(boss) + boss_name)
            name = raid_name(wing["id"])
            if index == cotm_index:
                name = f"{cotm}{name}"
            elif index == emboldened_index:
                name = f"{emboldened}{name}"
            if wing_done:
                name += " :white_check_mark:"
            else:
                name += " :x:"
            embed.add_field(name=f"**{name}**", value="\n".join(value))
        outdated = now > next_reset_time
        if len(not_completed) == 0:
            description = t(N_("Everything completed that week") if outdated
                            else N_("Everything completed this week")) + " :star:"
        else:
            bosses = list(filter(lambda b: b["type"] == "Boss", not_completed))
            events = list(
                filter(lambda b: b["type"] == "Checkpoint", not_completed))
            if bosses:
                bosses = t(N_("{count} bosses") if len(bosses) > 1 else N_("{count} boss"), count=len(bosses))
            if events:
                events = t(N_("{count} events") if len(events) > 1 else N_("{count} event"), count=len(events))
            description = t(N_("{missing} not completed that week") if outdated
                            else N_("{missing} not completed this week"),
                            missing=", ".join(filter(None, [bosses, events])))
        if outdated:
            description += "\n❗{}❗\n {}".format(
                t(N_("Warning")), t(N_("Data outdated for this week. Log into GW2 in order to update.")))
        embed.description = description
        embed.set_footer(text=t(N_("Logs uploaded via evtc will "
                                   "appear here with links - they don't have to be "
                                   "uploaded by you")),
                         icon_url=self.bot.user.display_avatar.url)
        return embed


async def setup(bot):
    await bot.add_cog(Account(bot))
