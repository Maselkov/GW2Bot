import discord
from discord.ext import commands
from discord.ext.commands import BucketType

BT_PIPELINE = [{
    '$group': {
        '_id': '$account_name',
        'bosses': {
            '$push': '$bosses'
        }
    }
}, {
    '$unwind': '$bosses'
}, {
    '$unwind': '$bosses'
},
               {
                   '$group': {
                       '_id': {
                           'account_name': '$_id',
                           'boss': '$bosses'
                       },
                       'sum': {
                           '$sum': 1
                       }
                   }
               },
               {
                   '$group': {
                       '_id': '$_id.account_name',
                       'bosses': {
                           '$push': {
                               'k': '$_id.boss',
                               'v': '$sum'
                           }
                       }
                   }
               },
               {
                   '$project': {
                       '_id': 0,
                       'account_name': '$_id',
                       'bosses': {
                           '$arrayToObject': '$bosses'
                       }
                   }
               }]


class BtMixin():
    @commands.command(aliases=["oldbt"], hidden=True)
    @commands.cooldown(1, 4, BucketType.user)
    async def oldbossestotal(self, ctx):
        """Display the number of times you've killed bosses"""
        user = ctx.author
        try:
            doc = await self.bot.database.get_user(user, self)
            embed = await self.old_boss_embed(doc["bosses_total"])
            embed.set_author(
                name=doc["key"]["account_name"], icon_url=user.avatar_url)
            await ctx.send(embed=embed)
        except:
            await ctx.send("No recorded bosskills yet")

    @commands.command(aliases=["bt"], hidden=True)
    @commands.cooldown(1, 4, BucketType.user)
    async def bossestotal(self, ctx):
        """Display the number of times you've killed bosses"""
        user = ctx.author
        doc = await self.bot.database.get(user, self)
        active_key = doc.get("key")
        keys = doc.get("keys", [])
        if active_key:
            keys.append(active_key)
        accounts = [key["account_name"] for key in keys]
        embed = await self.bt_embed(ctx, accounts)
        await ctx.send(user.mention, embed=embed)

    async def bt_embed(self, ctx, accounts):
        def readable_id(_id):
            _id = _id.split("_")
            dont_capitalize = ("of", "the", "in")
            title = " ".join([
                x.capitalize() if x not in dont_capitalize else x for x in _id
            ])
            return title[0].upper() + title[1:]

        embed = discord.Embed(
            title="Total boss kills", color=await self.get_embed_color(ctx))
        raids = await self.get_raids()
        wings = [wing for raid in raids for wing in raid["wings"]]
        match = {"account_name": {"$in": accounts}}
        pipeline = [{"$match": match}] + BT_PIPELINE
        results = await self.db.bosskills.aggregate(pipeline).to_list(None)
        first = await self.db.bosskills.find_one(match, sort=[("week", 1)])
        if not first:
            first = {}
        recording_since = first.get("week")
        for index, wing in enumerate(wings):
            value = []
            for boss in wing["events"]:
                total = 0
                breakdown = [""]
                for account in results:
                    kills = account["bosses"].get(boss["id"], 0)
                    if kills:
                        breakdown.append(
                            f"{account['account_name']}: **{kills}**")
                    total += kills
                boss_name = f"{readable_id(boss['id'])}: **{total}**"
                value.append(f"> {boss_name}" + "\n".join(breakdown))
            name = readable_id(wing["id"])
            embed.add_field(name=f"**{name}**", value="\n".join(value))
        if recording_since:
            embed.set_footer(
                text="Recording bosskills for this account since",
                icon_url=self.bot.user.avatar_url)
            embed.timestamp = recording_since
        return embed

    async def old_boss_embed(self, results):
        def is_killed(boss):
            return "+" if boss["id"] in results else "-"

        def readable_id(_id):
            _id = _id.split("_")
            dont_capitalize = ("of", "the", "in")
            return " ".join([
                x.capitalize() if x not in dont_capitalize else x for x in _id
            ])

        raids = await self.get_raids()
        embed = discord.Embed(title="Total boss kills", color=self.embed_color)
        for raid in raids:
            for wing in raid["wings"]:
                value = ["```diff"]
                for boss in wing["events"]:
                    count = results.get(boss["id"], 0)
                    value.append("{}{}: {}".format(
                        is_killed(boss), readable_id(boss["id"]), count))
                value.append("```")
                name = readable_id(wing["id"])
                embed.add_field(name=name, value="\n".join(value))
        embed.set_footer(text="Only one kill can be recorded per week")
        return embed

    async def get_raids(self):
        config = await self.bot.database.configs.find_one({
            "cog_name":
            "GuildWars2"
        })
        return config["cache"].get("raids")
