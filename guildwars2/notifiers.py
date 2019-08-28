import asyncio
import datetime
import html
import re
import unicodedata
import xml.etree.ElementTree as et

import discord
from bs4 import BeautifulSoup
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError

class NotiifiersMixin:
#### For the "BOSSNOTIFIER" group command
    @commands.group(case_insensitive=True, name='bossnotifier')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def bossnotifier(self, ctx):
        """Sends the next two bosses every 15 minutes to a channel"""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command)

  ### For the bossnotifier "CHANNEL" command
    @commands.cooldown(1, 5, BucketType.guild)
    @bossnotifier.command(name='channel', usage='<channel name>')
    async def bossnotifier_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel."""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permissions to send "
                                  f"messages to {channel.mention}.")
        await self.bot.database.set_guild(
            guild, {'bossnotifs.channel': channel.id}, self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc['bossnotifs'].get('on', False)
        if enabled:
            msg = (f"Channel set to {channel.mention}.\n"
                   "The last message will automatically be deleted.")
        else:
            msg = (f"Channel set to {channel.mention}\nUse `{ctx.prefix}"
                   "bossnotifier toggle on` in order to receive notifications.")
        await channel.send(msg)

  ### For the bossnotifier "TOGGLE" command
    @commands.cooldown(1, 5, BucketType.guild)
    @bossnotifier.command(name='toggle', usage='<on|off>')
    async def bossnotifier_toggle(self, ctx, on_off: bool):
        """Toggles notifications."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'bossnotifs.on': on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc['bossnotifs'].get('channel')
            if channel:
                channel = guild.get_channel(channel)
                if channel:
                    msg = (f"Upcoming bosses will now be sent to {channel.mention}.\n"
                           "The last message will be automatically deleted.")
            else:
                msg = (f"Boss notifications enabled.\n Use `{ctx.prefix}"
                       "bossnotifier channel <channel>` in order to receive "
                       "notifications.")
        else:
            msg = ("Boss notifier disabled.")
        await ctx.send(msg)

#### For the "DAILYNOTIFIER" group command
    @commands.group(case_insensitive=True, name='dailynotifier')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def dailynotifier(self, ctx):
        """Commands related to Daily Notifications"""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command)
            
  ### For the dailynotifier "AUTODELETE" command
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='autodelete', usage='<on|off>')
    async def daily_notifier_autodelete(self, ctx, on_off: bool):
        """Deletes notifications.
        
        Enabling this will automatically delete yesterday's dailies."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'daily.autodelete': on_off}, self)
        if on_off:
            await ctx.send("Autodeletion enabled.")
        if not on_off:
            await ctx.send("Autodeletion disabled.")
            
  ### For the dailynotifier "AUTODELETE" command. These are for hidden aliases
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='autodel', usage='<on|off>', aliases=['adelete', 'autod', 'ad', 'automaticallydelete'], hidden=True)
    async def daily_notifier_autodel(self, ctx, on_off: bool):
        """Deletes notifications.
    
        Enabling this will automatically delete yesterday's dailies."""
        await ctx.invoke(self.daily_notifier_autodelete, on_off=on_off)

  ### For the dailynotifier "AUTOPIN" command
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='autopin', usage='<on|off>')
    async def daily_notifier_autopin(self, ctx, on_off: bool):
        """Pins notifications.
        
        Enabling this will automatically pin today's dailies and remove yesterday's pin."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'daily.autopin': on_off}, self)
        if on_off:
            await ctx.send("Autopinning enabled.")
        if not on_off:
            await ctx.send("Autopinning disabled.")
            
  ### For the dailynotifier "AUTOPIN" command. This is for aliases
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='autop', usage='<on|off>', aliases=['automaticallypin', 'ap', 'apin'], hidden=True)
    async def daily_notifier_autop(self, ctx, on_off: bool):
        """Pins notifications.
        
        Enabling this will automatically pin today's dailies and remove yesterday's pin."""
        await ctx.invoke(self.daily_notifier_autopin, on_off=on_off)

  ### For the dailynotifier "CATEGORIES" command
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='categories', usage='<categories>')
    async def daily_notifier_categories(self, ctx, *categories):
        """Select the dailies to display.
        
        This will tailor your daily notifications to your specifications.
        
        Available options:
        all, psna, psna_later, pve, pvp, wvw, fractals
        
        Example: dailynotifier categories psna pve fractals"""
        if not categories:
            await ctx.send_help(ctx.command)
            return
        guild = ctx.guild
        possible_values = [
            'all', 'psna', 'psna_later', 'pve', 'pvp', 'wvw', 'fractals'
        ]
        categories = [x.lower() for x in categories]
        if len(categories) > 6:
            await ctx.send_help(ctx.command)
            return
        for category in categories:
            if category not in possible_values:
                await ctx.send_help(ctx.command)
                return
            if categories.count(category) > 1:
                await ctx.send_help(ctx.command)
                return
            if category == 'all':
                categories = [
                    'psna', 'psna_later', 'pve', 'pvp', 'wvw', 'fractals'
                ]
                break
        embed = await self.daily_embed(categories)
        await self.bot.database.set_guild(
            guild, {'daily.categories': categories}, self)
        await ctx.send(
            "Your categories have been set. Here's an example of "
            "your current daily notifications:",
            embed=embed)

  ### For the dailynotifier "CHANNEL" command
    @dailynotifier.command(name='channel', usage='<channel name>')
    async def daily_notifier_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel.
        
        Daily notifications are sent to the specified channel at daily reset."""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permission to send "
                                  f"messages to {channel.mention}.")
        await self.bot.database.set_guild(guild, {'daily.channel': channel.id},
                                          self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc['daily'].get('on', False)
        if enabled:
            msg = (f"Channel set to {channel.mention}.")
        else:
            msg = (f"Channel set to {channel.mention}.\nIn order to receive "
                   "notifications, you need to enable it using "
                   f"`{ctx.prefix}dailynotifier toggle on`.")
        await channel.send(msg)

  ### For the dailynotifier "TOGGLE" command
    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name='toggle', usage='<on|off>')
    async def daily_notifier_toggle(self, ctx, on_off: bool):
        """Toggles notifications."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'daily.om': on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc['daily'].get('channel')
            if channel:
                channel = guild.get_channel(channel)
                if channel:
                    msg = ("Daily notifications enabled.")
            else:
                msg = ("Daily notifications enabled.\nIn order to receive "
                       "dailies, you need to set a channel using "
                       f"`{ctx.prefix}dailynotifier channel <channel>`.")
        else:
            msg = ("Daily notifications diabled.")
        await ctx.send(msg)

#### For the "NEWSFEED" group command
    @commands.group(case_insensitive=True, name='newsfeed')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def newsfeed(self, ctx):
        """Automatically sends Guild Wars 2 news
        This does not send game updates."""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command)

  ### For the newsfeed "CHANNEL" command
    @newsfeed.command(name='channel', usage='<channel name>')
    async def newsfeed_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel."""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permission to send "
                                  f"messages to {channel.mention}.")
        await self.bot.database.set_guild(guild, {'news.channel': channel.id},
                                          self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc['news'].get('on', False)
        if enabled:
            msg = (f"Channel set to {channel.mention}.")
        else:
            msg = (f"Channel set to {channel.mention}.\nIn order to receive "
                   "news, you need to enable it using "
                   f"`{ctx.prefix}newsfeed toggle on`.")
        await channel.send(msg)

  ### For the newsfeed "FILTER" command
    @newsfeed.command(name='filter', usage='<on|off>')
    async def newsfeed_filter(self, ctx, on_off: bool):
        """Filters the news to display.
        
        If enabled, will filter out the Livestream Schedule and Community Showcase news."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'news.filter': on_off}, self)
        if on_off:
            msg = "Newsfeed filter enabled."
        else:
            msg = "Newsfeed filter disabled."
        await ctx.send(msg)

  ### For the newsfeed "TOGGLE" command
    @newsfeed.command(name='toggle', usage='<on|off>')
    async def newsfeed_toggle(self, ctx, on_off: bool):
        """Toggles news posting."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'news.on': on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc['news'].get('channel')
            if channel:
                channel = guild.get_channel(channel)
                if channel: # Channel can be none now
                    msg = ("Newsfeed enabled.")
            else:
                msg = ("Newsfeed enabled.\nIn order to receive "
                       "news, you need to set a channel using "
                       f"`{ctx.prefix}newsfeed channel <channel>`.")
        else:
            msg = ("Newsfeed disabled.")
        await ctx.send(msg)

#### For the "UPDATENOTIFIER" group command
    @commands.group(case_insensitive=True, name='updatenotifier')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def updatenotifier(self, ctx):
        """Sends Guild Wars 2 Updates"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

  ### For the updatenotifier "CHANNEL" command
    @updatenotifier.command(name='channel', usage='<channel name>')
    async def update_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel."""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permission to send "
                                  f"messages to {channel.mention}.")
        await self.bot.database.set_guild(
            guild, {'updates.channel': channel.id}, self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc['updates'].get('on', False)
        if enabled:
            mention = doc['updates'].get('mention', 'here')
            if mention == 'none':
                suffix = ""
            else:
                suffix = ("\n**WARNING:**\nCurrently the bot will "
                          f"mention `@{mention}`. Use `{ctx.prefix}updatenotifier "
                          "mention` to change that.")
            msg = (f"Channel set to {channel.mention}.{suffix}")
        else:
            msg = (f"Channel set to {channel.mention}.\nIn order to receive "
                   "notifications, you need to enable it using "
                   f"`{ctx.prefix}updatenotifier toggle on`.")
        await channel.send(msg)

  ### For the updatenotifier "MENTION" command
    @commands.cooldown(1, 5, BucketType.guild)
    @updatenotifier.command(name='mention', usage='<type>')
    async def updatenotifier_mention(self, ctx, mention_type):
        """Changes how updates are mentioned.
        
        Mention Types: none, here, everyone"""
        valid_types = 'none', 'here', 'everyone'
        mention_type = mention_type.lower()
        if mention_type not in valid_types:
            return await ctx.send_help(ctx.command)
        guild = ctx.guild
        await self.bot.database.set_guild(
            guild, {'updates.mention': mention_type}, self)
        await ctx.send("Mention type set.")

  ### For the updatenotifier "TOGGLE" command
    @updatenotifier.command(name='toggle', usage='<on|off>')
    async def update_toggle(self, ctx, on_off: bool):
        """Toggles update notifications."""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {'updates.on': on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc['updates'].get('channel')
            if channel:
                channel = guild.get_channel(channel)
                if channel: # Channel can be none now
                    mention = doc['updates'].get('mention', 'here')
                    if mention == 'none':
                        suffix = ""
                    else:
                        suffix = ("\n**WARNING:**\nCurrently the bot will "
                                  f"mention `@{mention}`. Use `{ctx.prefix}updatenotifier "
                                  "mention` to change that.")
                    msg = (
                        "Update notifications enabled.")
                else:  # TODO change it, ugly
                    msg = (
                        "Update notifications enabled. In order to receive "
                        "them, you need to set a channel using "
                        f"`{ctx.prefix}updatenotifier channel <channel>`.")
            else:
                msg = ("Update notifications enabled. In order to receive "
                       "them, you need to set a channel using "
                       f"`{ctx.prefix}updatenotifier channel <channel>`.")
        else:
            msg = ("Update notifications disabled.")
        await ctx.send(msg)

    ## Build checker
    async def check_build(self):
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return False
        current_build = doc['cache']['build']
        endpoint = 'build'
        try:
            results = await self.call_api(endpoint)
        except APIError:
            return False
        build = results['id']
        if not current_build == build:
            await self.bot.database.set_cog_config(self,
                                                   {'cache.build': build})
            return True
        else:
            return False

    ## Boss notifications
    @tasks.loop(minutes=5)
    async def boss_notifier(self):
        name = self.__class__.__name__
        boss = self.get_upcoming_bosses(1)[0]
        await asyncio.sleep(boss['diff'].total_seconds() + 1)
        cursor = self.bot.database.get_guilds_cursor({
            'bossnotifs.on': True,
            'bossnotifs.channel': {
                '$ne': None
            }
        }, self)
        async for doc in cursor:
            try:
                doc = doc['cogs'][name]['bossnotifs']
                channel = self.bot.get_channel(doc['channel'])
                timezone = await self.get_timezone(channel.guild)
                embed = self.schedule_embed(2, timezone=timezone)
                try:
                    message = await channel.send(embed=embed)
                except discord.Forbidden:
                    message = await channel.send("Need permission to "
                                                 "embed links in order "
                                                 "to send boss "
                                                 "notifications!")
                    continue
                await self.bot.database.set_guild(
                    channel.guild, {'bossnotifs.message': message.id}, self)
                old_message = doc.get('message')
                if old_message:
                    to_delete = await channel.fetch_message(old_message)
                    await to_delete.delete()
            except:
                pass

    ## Day checker
    async def check_day(self):
        current = datetime.datetime.utcnow().weekday()
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return False
        cache = doc['cache']
        day = cache.get('day')
        dailies = cache.get('dailies')
        if not dailies:
            await self.cache_dailies()
        if day != current:
            await self.bot.database.set_cog_config(self,
                                                   {'cache.day': current})
            return True
        else:
            return False

    ## Daily checker
    @tasks.loop(minutes=3)
    async def daily_checker(self):
        if await self.check_day():
            await asyncio.sleep(300)
            if not self.bot.available:
                await asyncio.sleep(360)
            await self.cache_dailies()
            await self.send_daily_notifs()

    ## Daily notification
    async def send_daily_notifs(self):
        try:
            name = self.__class__.__name__
            cursor = self.bot.database.get_guilds_cursor({
                'daily.on': True,
                'daily.channel': {
                    '$ne': None
                }
            }, self)
            daily_doc = await self.bot.database.get_cog_config(self)
            sent = 0
            deleted = 0
            forbidden = 0
            pinned = 0
            async for doc in cursor:
                try:
                    guild = doc['cogs'][name]['daily']
                    categories = guild.get("categories")
                    if not categories:
                        categories = [
                            'psna', 'psna_later', 'pve', 'pvp', 'wvw',
                            'fractals'
                        ]
                    embed = await self.daily_embed(categories, doc=daily_doc)
                    channel = self.bot.get_channel(guild['channel'])
                    try:
                        embed.set_thumbnail(
                            url='https://wiki.guildwars2.com/images/'
                            '1/14/Daily_Achievement.png')
                        message = await channel.send(embed=embed)
                        sent += 1
                    except discord.Forbidden:
                        forbidden += 1
                        message = await channel.send("Need permission to embed links.")
                    await self.bot.database.set_guild(
                        channel.guild, {'daily.message': message.id}, self)
                    autodelete = guild.get('autodelete', False)
                    if autodelete:
                        try:
                            old_message = guild.get('message')
                            if old_message:
                                to_delete = await channel.fetch_message(
                                    old_message)
                                await to_delete.delete()
                                deleted += 1
                        except:
                            pass
                    autopin = guild.get('autopin', False)
                    if autopin:
                        try:
                            await message.pin()
                            pinned += 1
                            try:
                                async for m in channel.history(
                                        after=message, limit=3):
                                    if (m.type == discord.MessageType.pins_add
                                            and m.author == self.bot.user):
                                        await m.delete()
                                        break
                            except:
                                pass
                            old_message = guild.get('message')
                            if old_message:
                                to_unpin = await channel.fetch_message(
                                    old_message)
                                await to_unpin.unpin()
                        except:
                            pass

                except:
                    pass
            self.log.info(
                f"Daily notifications: sent {sent}, deleted {deleted}, "
                f"forbidden {forbidden}, pinned {pinned}.")
        except Exception as e:
            self.log.exception(e)
            return

    ## Force account names
    @tasks.loop(minutes=5)
    async def forced_account_names(self):
        cursor = self.bot.database.get_guilds_cursor(
            {
                'force_account_names': True
            }, self)
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc['_id'])
                await self.force_guild_account_names(guild)
            except:
                pass

    ## Gem tracker
    @tasks.loop(minutes=5)
    async def gem_tracker(self):
        cost = await self.get_gem_price()
        cost_coins = self.gold_to_coins(None, cost)
        cursor = self.bot.database.iter('users', {'gemtrack': {
            '$ne': None
        }}, self)
        async for doc in cursor:
            try:
                if cost < doc['gemtrack']:
                    user = doc["_obj"]
                    user_price = self.gold_to_coins(None, doc['gemtrack'])
                    msg = (f"Hey, {user.mention}! You asked to be notified "
                           f"when 400 gems were cheaper than {user_price}. Guess "
                           f"what? They're now only {cost_coins}!")
                    await user.send(msg)
                    await self.bot.database.set(user, {'gemtrack': None}, self)
            except:
                pass

    ## News acquisition
    async def check_news(self):
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return []
        last_news = doc['cache']['news']
        url = 'https://www.guildwars2.com/en/feed/'
        async with self.session.get(url) as r:
            feed = et.fromstring(await r.text())[0]
        to_post = []
        if last_news:
            for item in feed.findall('item'):
                try:
                    if item.find('title').text not in last_news:
                        to_post.append({
                            'link':
                            item.find('link').text,
                            'title':
                            item.find('title').text,
                            'description':
                            item.find('description').text.split('</p>', 1)[0]
                        })
                except:
                    pass
        last_news = [x.find('title').text for x in feed.findall('item')]
        await self.bot.database.set_cog_config(self, {'cache.news': last_news})
        return to_post

    ## News checker
    @tasks.loop(minutes=3)
    async def news_checker(self):
        to_post = await self.check_news()
        if to_post:
            embeds = []
            for item in to_post:
                embeds.append(self.news_embed(item))
            await self.send_news(embeds)

    ## News embedder
    def news_embed(self, item):
        soup = BeautifulSoup(item['description'], 'html.parser')
        description = f"[Click here]({item['link']})\n{soup.get_text()}"
        data = discord.Embed(
            title=unicodedata.normalize('NFKD', item['title']),
            description=description,
            color=0xc12d2b)
        return data

    ## News sender
    async def send_news(self, embeds):
        cursor = self.bot.database.iter(
            'guilds',
            {
                'news.on': True,
                'news.channel': {
                    '$ne': None
                }
            },
            self,
            subdocs=['news'],
        )
        to_filter = ['the arenanet streaming schedule', 'community showcase']
        filtered = [
            embed.title for embed in embeds
            if any(f in embed.title.lower() for f in to_filter)
        ]

        async def process_doc(doc):
            channel = self.bot.get_channel(doc['channel'])
            filter_on = doc.get('filter', True)
            for embed in embeds:
                if filter_on:
                    if embed.title in filtered:
                        continue
                await channel.send(embed=embed)

        async for doc in cursor:
            try:
                asyncio.create_task(process_doc(doc))
            except Exception as e:
                self.log.exception(e)

    ## Update Notification
    async def update_notification(self, new_build):
        def get_short_patchnotes(body, url):
            if len(body) < 1000:
                return body
            return body[:1000] + "... [Read more]({url})"

        async def get_page(url):
            async with self.session.get(url + '.json') as r:
                return await r.json()

        def patchnotes_embed(embed, notes):
            notes = '\n'.join(html.unescape(notes).splitlines())
            lines = notes.splitlines()
            notes_sub = ""
            for line in lines:
                # Don't sub #### as those are made to a new header
                line = re.sub('^#{1,3} ', '**', line)
                line = re.sub('#{5} ', '**', line)
                line = re.sub('(\*{2}.*)', r'\1**', line)
                line = re.sub('\*{4}', '**', line)
                line = re.sub('&quot;(.*)&quot;', r'*\1*', line)
                notes_sub += f"{line}\n"

            headers = re.findall('#{4}.*', notes_sub, re.MULTILINE)
            values = re.split('#{4}.*', notes_sub)
            counter = 0
            if headers:
                for header in headers:
                    counter += 1
                    header = re.sub("#{4} ", "", header)
                    values[counter] = re.sub('\n\n', '\n', values[counter])
                    embed.add_field(name=header, value=values[counter])
            else:
                embed.description = notes_sub
            return embed

        base_url = 'https://en-forum.guildwars2.com'
        url_category = base_url + '/categories/game-release-notes'
        category = await get_page(url_category)
        category = category['Category']
        last_discussion = category['LastDiscussionID']
        url_topic = base_url + f"/discussion/{last_discussion}"
        patch_notes = ""
        title = "GW2 has just updated!"
        try:  # Playing it safe in case forums die or something
            topic_result = await get_page(url_topic)
            topic = topic_result['Discussion']
            last_comment = topic['LastCommentID']
            if not last_comment:
                comment_url = url_topic
                body = topic['Body']
            else:
                comment_url = url_topic + f"#Comment_{last_comment}"
                for comment in topic_result['Comments']:
                    if comment['CommentID'] == last_comment:
                        body = comment['Body']
                        break
                else:
                    raise Exception('Comment not found')
            patch_notes = get_short_patchnotes(body, comment_url)
            url_topic = comment_url
            title = topic['Name']
        except Exception as e:
            self.log.exception(e)
        embed = discord.Embed(
            title=f"**{title}**",
            url=url_topic,
            color=self.embed_color)
        if patch_notes:
            embed = patchnotes_embed(embed, patch_notes)
        embed.set_footer(text=f"Build: {new_build}")
        text_version = ("@here Guild Wars 2 has just updated! "
                        f"New build: {new_build} "
                        f"Update notes: <{url_topic}>\n{patch_notes}")
        return embed, text_version

    ## Update notification checker
    @tasks.loop(minutes=1)
    async def game_update_checker(self):
        if await self.check_build():
            await self.send_update_notifs()
            await self.rebuild_database()

    ## Update notification sender
    async def send_update_notifs(self):
        doc = await self.bot.database.get_cog_config(self)
        build = doc['cache']['build']
        embed_available = False
        try:
            embed, text = await self.update_notification(build)
            embed_available = True
        except:
            text = (
                f"Guild Wars 2 has just updated! New build: {build}")
        async def process_doc(doc):
            mention = doc.get('mention', 'here')
            if mention == 'none':
                mention = ""
            else:
                mention = f"@{mention} "
            channel = self.bot.get_channel(doc['channel'])
            if (channel.permissions_for(channel.guild.me).embed_links
                    and embed_available):
                message = mention + "Guild Wars 2 has just updated!"
                await channel.send(message, embed=embed)
            else:
                await channel.send(text)

        cursor = self.bot.database.iter(
            'guilds', {
                'updates.on': True,
                'updates.channel': {
                    '$ne': None
                }
            },
            self,
            subdocs=['updates'])
        async for doc in cursor:
            try:
                asyncio.create_task(process_doc(doc))
            except:
                pass

    ## World population checker
    @tasks.loop(minutes=5)
    async def world_population_checker(self):
        await self.send_population_notifs()
        await asyncio.sleep(300)
        await self.cache_endpoint('worlds', True)

    ## World population notification sending
    async def send_population_notifs(self):
        async for world in self.db.worlds.find({
                'population': {
                    '$ne': 'Full'
                }
        }):
            world_name = world['name']
            wid = world['_id']
            msg = (
                f"{world_name} is no longer full! [populationtrack]")
            cursor = self.bot.database.get_users_cursor({
                'poptrack': wid
            }, self)
            async for doc in cursor:
                try:
                    user = await self.bot.fetch_user(doc['_id'])
                    await self.bot.database.set_user(
                        user, {'poptrack': wid}, self, operator='$pull')
                    await user.send(msg)
                except:
                    pass
