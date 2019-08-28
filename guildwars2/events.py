import asyncio
import datetime

import discord
from discord.ext import commands, tasks

UTC_TZ = datetime.timezone.utc


class EventsMixin:
#### For the "ET" group command
    @commands.group(case_insensitive=True, name='et', aliases=['hotet'])
    async def et(self, ctx):
        """The event timer"""
        # Help formatter preview
        if ctx.invoked_subcommand is None:
            msg = ("**{0}et bosses | b**: Upcoming world bosses.\n"
                   "**{0}et hot | h**: Event timer for HoT maps and Dry Top.\n"
                   "**{0}et pof | p**: Event timer for PoF and LS4 maps.\n"
                   "**{0}et day | d**: Current day/night.\n"
                   "**{0}et reminder**: Enable automatic reminders for events."
                   .format(ctx.prefix))
            embed = discord.Embed(
                title="Event Timer Help",
                description=msg,
                color=await self.get_embed_color(ctx))
            embed.set_footer(
                text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
            info = None
            if ctx.invoked_with.lower() == "hotet":
                info = ("`{0}hotet` has evolved into `{0}et`, use "
                        "`{0}et h` to access the old functionality.").format(
                            ctx.prefix)
            try:
                await ctx.send(info, embed=embed)
            except:
                await ctx.send_help(ctx.command)

  ### For the et "HOT" command
    @et.command(name='hot', aliases=['h'])
    async def et_hot(self, ctx):
        """Event timer for HoT maps and Dry Top."""
        await ctx.send(embed=await self.timer_embed(ctx, 'hot'))

  ### For the et "POF" command
    @et.command(name='pof', aliases=['p'])
    async def et_pof(self, ctx):
        """Event timer for PoF and LS4 maps."""
        await ctx.send(embed=await self.timer_embed(ctx, 'pof'))

  ### For the et "DAY" command
    @et.command(name='day', aliases=['d'])
    async def et_day(self, ctx):
        """Current day/night cycle."""
        await ctx.send(embed=await self.timer_embed(ctx, 'day'))

  ### For the et "BOSSES" command
    @et.command(name='bosses', aliases=['b'])
    async def et_bosses(self, ctx):
        """Upcoming world bosses."""
        tz = await self.get_timezone(ctx.guild)
        embed = self.schedule_embed(timezone=tz)
        await ctx.send(embed=embed)

  ### For the et "REMINDER" command
    @et.command(name='reminder', usage='<event name>')
    async def et_reminder(self, ctx, *, event_name):
        """Enable automatic reminders for events.
        
        This make the bot automatically notify you before an event starts.

        For the event name, use the exact name as it appears in $et
        Examples:
        $et reminder Shadow Behemoth
        $et reminder Gerent Preparation
        $et reminder Rounds 1-3
        $et reminder Assault
        """
        if not event_name:
            return await ctx.send_help(ctx.command)
        event_name = event_name.lower()
        # if event_name == "settings":
        # return await self.et_reminder_settings_menu(ctx)
        if event_name == 'nothing':
            return await ctx.send("Invalid event name.")
        reminder = {}
        for boss in self.boss_schedule:
            if boss['name'].lower() == event_name:
                reminder['type'] = 'boss'
                reminder['name'] = boss['name']
        if not reminder:
            for group in 'hot', 'pof':
                maps = self.gamedata['event_timers'][group]
                for location in maps:
                    for phase in location['phases']:
                        if phase['name'].lower() == event_name:
                            reminder['type'] = 'phase'
                            reminder['name'] = phase['name']
                            reminder['group'] = group
                            reminder['map_name'] = location['name']
        if not reminder:
            return await ctx.send("No event found matching that name.")
        embed = discord.Embed(
            description=f"How many minutes before **{event_name.title()}** begins do you want "
            "to be notified by?\nType the number below. (1-60)",
            color=await self.get_embed_color(ctx))
        await ctx.send(embed=embed)
        ans = await ctx.get_answer()
        if not ans:
            return
        try:
            time = int(ans)
        except:
            return await ctx.send("Invalid answer.")
        if time < 0:
            return await ctx.send("That's not how it works!")
        if time > 60:
            return await ctx.send("Time can't be greater than one hour.")
        reminder['time'] = time * 60
        await self.bot.database.set(
            ctx.author, {'event_reminders': reminder}, self, operator='push')
        await ctx.send("Reminder successfully set.")

    ## The "ET" reminder settings menu
    async def et_reminder_settings_menu(self, ctx):
        user = ctx.author
        embed_templates = [
            {
                'setting':
                'online_only',
                'title':
                'Online only',
                'description':
                "Enable to have reminders sent only when you're online on Discord",
                'footer':
                "Note that the bot can't distinguish whether you're invisible or offline"
            },
            {
                'setting':
                'ingame_only',
                'title':
                'Ingame only',
                'description':
                "Enable to have reminders sent only while you're in game",
                'footer':
                "This works based off your Discord game status. Make sure to enable it"
            }
        ]
        doc = await self.bot.database.get(user, self)
        doc = doc.get('et_reminder_settings', {})
        settings = [t['setting'] for t in embed_templates]
        settings = {s: doc.get(s, False) for s in settings}
        messages = []
        reactions = {"✔": True, "❌": False}
        to_cleanup = [
            await user.send("Use the reactions below to configure reminders.")
        ]

        def setting_embed(template):
            enabled = 'enabled' if settings[
                template['setting']] else 'disabled'
            description = (f"**{template['description']}**\n"
                           f"Current state: **{enabled}**")
            embed = discord.Embed(
                title=template['title'],
                description=description,
                color=self.embed_color)
            if template['footer']:
                embed.set_footer(text=template['footer'])
            return embed

        for template in embed_templates:
            embed = setting_embed(template)
            msg = await user.send(embed=embed)
            messages.append({'message': msg, 'setting': template['setting']})
            to_cleanup.append(msg)
            for reaction in reactions:
                asyncio.create_task(msg.add_reaction(reaction))

        def check(r, u):
            if not isinstance(r.emoji, str):
                return False
            if u != user:
                return False
            return r.emoji in reactions and r.message.id in [
                m['message'].id for m in messages
            ]

        while True:
            try:
                reaction, _ = await self.bot.wait_for(
                    'reaction_add', check=check, timeout=120)
            except asyncio.TimeoutError:
                break
            setting = next(m['setting'] for m in messages
                           if m['message'].id == reaction.message.id)
            settings[setting] = reactions[reaction.emoji]
            template = next(
                t for t in embed_templates if t['setting'] == setting)
            embed = setting_embed(template)
            asyncio.create_task(reaction.message.edit(embed=embed))
            await self.bot.database.set(
                user, {'et_reminder_settings': settings}, self)
        for message in to_cleanup:
            asyncio.create_task(message.delete())

    ## Event reminder tracker
    @tasks.loop(seconds=10)
    async def event_reminder_task(self):
        cursor = self.bot.database.iter(
            'users', {'event_reminders': {
                '$exists': True,
                '$ne': []
            }}, self)
        async for doc in cursor:
            try:
                user = doc['_obj']
                for i, reminder in enumerate(doc['event_reminders']):
                    asyncio.create_task(
                        self.process_reminder(user, reminder, i))
            except Exception as e:
                pass

    ## Formats the time
    def format_timedelta(self, td):
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours} hours and {minutes} minutes"
        else:
            return f"{minutes} minutes"

    ## Generates the schedule
    def generate_schedule(self):
        now = datetime.datetime.now(UTC_TZ)
        normal = self.gamedata['event_timers']['bosses']['normal']
        hardcore = self.gamedata['event_timers']['bosses']['hardcore']
        schedule = []
        counter = 0
        while counter < 12:
            for boss in normal:
                increment = datetime.timedelta(
                    hours=boss['interval'] * counter)
                time = (datetime.datetime(
                    1, 1, 1, *boss['start_time'], tzinfo=UTC_TZ) + increment)
                if time.day != 1:
                    continue
                time = time.replace(
                    year=now.year, month=now.month, day=now.day, tzinfo=UTC_TZ)
                output = {
                    'name': boss['name'],
                    'time': time,
                    'waypoint': boss['waypoint']
                }
                schedule.append(output)
            counter += 1
        for boss in hardcore:
            for hours in boss['times']:
                time = datetime.datetime.now(UTC_TZ)
                time = time.replace(hour=hours[0], minute=hours[1])
                output = {
                    'name': boss['name'],
                    'time': time,
                    'waypoint': boss['waypoint']
                }
                schedule.append(output)
        return sorted(schedule, key=lambda t: t['time'].time())

    ## Gets the timezone
    async def get_timezone(self, guild):
        if not guild:
            return UTC_TZ
        doc = await self.bot.database.get_guild(guild, self)
        if not doc:
            return UTC_TZ
        tz = doc.get('timezone')
        if tz:
            offset = datetime.timedelta(hours=tz)
            tz = datetime.timezone(offset)
        return tz or UTC_TZ

    ## Gets the time until event
    def get_time_until_event(self, reminder):
        if reminder['type'] == 'boss':
            time = datetime.datetime.now(UTC_TZ)
            day = 0
            done = False
            while not done:
                for boss in self.boss_schedule:
                    boss_time = boss['time']
                    boss_time = boss_time + datetime.timedelta(days=day)
                    if time < boss_time:
                        if boss['name'] == reminder['name']:
                            return int(
                                (boss_time - datetime.datetime.now(UTC_TZ)
                                 ).total_seconds())
                day += 1
        time = datetime.datetime.utcnow()
        position = (60 * time.hour + time.minute) % 120
        for location in self.gamedata['event_timers'][reminder['group']]:
            if location['name'] == reminder['map_name']:
                duration_so_far = 0
                index = 0
                phases = location['phases']
                for i, phase in enumerate(phases):
                    if position < duration_so_far:
                        break
                    index = i
                    duration_so_far += phase['duration']
                index += 1
                if index == len(phases):
                    if phases[0]['name'] == phases[index - 1]['name']:
                        index = 1
                        duration_so_far += phases[0]['duration']
                    else:
                        index = 0
                for phase in phases[index:]:
                    if phase['name'] == reminder['name']:
                        break
                    duration_so_far += phase['duration']
                else:
                    for phase in phases:
                        if phase['name'] == reminder['name']:
                            break
                        duration_so_far += phase['duration']
                return (duration_so_far - position) * 60

    ## Gets the upcoming bosses
    def get_upcoming_bosses(self, limit=8, *, timezone=UTC_TZ):
        upcoming_bosses = []
        time = datetime.datetime.now(UTC_TZ)
        counter = 0
        day = 0
        done = False
        while not done:
            for boss in self.boss_schedule:
                if counter == limit:
                    done = True
                    break
                boss_time = boss['time']
                boss_time = boss_time + datetime.timedelta(days=day)
                if time < boss_time:
                    output = {
                        'name':
                        boss['name'],
                        'time':
                        boss_time.astimezone(tz=timezone).strftime("%H:%M"),
                        'waypoint':
                        boss['waypoint'],
                        'diff':
                        boss_time - time
                    }
                    upcoming_bosses.append(output)
                    counter += 1
            day += 1
        return upcoming_bosses

    ## Cog Listener
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id:
            return
        if payload.user_id == self.bot.user.id:
            return
        user = self.bot.get_user(payload.user_id)
        if not user:
            return
        if payload.emoji.name != "❌":
            return
        update_result = await self.bot.database.set(
            user, {'event_reminders': {
                'last_message': payload.message_id
            }},
            self,
            operator='pull')
        if update_result.modified_count:
            message = await user.fetch_message(payload.message_id)
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    ## Processing the reminder
    async def process_reminder(self, user, reminder, i):
        time = self.get_time_until_event(reminder)
        if time < reminder['time'] + 30:
            last_reminded = reminder.get('last_reminded')
            if last_reminded and (datetime.datetime.utcnow() - last_reminded
                                  ).total_seconds() < reminder['time'] + 120:
                return
            try:
                last_message = reminder.get('last_message')
                if last_message:
                    last_message = await user.fetch_message(last_message)
                    await last_message.delete()
            except discord.HTTPException:
                pass
            minutes, seconds = divmod(time, 60)
            if minutes:
                time_string = (f"{minutes} minutes and {seconds} seconds")
            else:
                time_string = f"{seconds} seconds"
            description = (f"{reminder['name']} will begin in {time_string}")
            embed = discord.Embed(
                title="Event reminder",
                description=description,
                color=self.embed_color)
            embed.set_footer(
                icon_url=self.bot.user.avatar_url,
                text="Click on the reaction below to unsubscribe to this event.")
            try:
                msg = await user.send(embed=embed)
            except discord.HTTPException:
                return
            reminder['last_reminded'] = msg.created_at
            reminder['last_message'] = msg.id
            await self.bot.database.set(
                user, {f"event_reminders.{i}": reminder}, self)
            await msg.add_reaction("❌")

    ## Embeds the schedule
    def schedule_embed(self, limit=8, *, timezone=UTC_TZ):
        schedule = self.get_upcoming_bosses(limit, timezone=timezone)
        data = discord.Embed(
            title="Upcoming world bosses", color=self.embed_color)
        for boss in schedule:
            value = f"Time: {boss['time']}\nWaypoint: {boss['waypoint']}"
            data.add_field(
                name=f"{boss['name']} in {self.format_timedelta(boss['diff'])}",
                value=value,
                inline=False)
        data.set_footer(
            text=f"Timezone: {timezone.tzname(None)}",
            icon_url=self.bot.user.avatar_url)
        return data

    ## Embeds the timer
    async def timer_embed(self, ctx, group):
        time = datetime.datetime.utcnow()
        position = (
            60 * time.hour + time.minute
        ) % 120  # this gets the minutes elapsed in the current 2 hour window
        maps = self.gamedata['event_timers'][group]
        title = {
            'hot': "HoT Event Timer",
            'pof': "PoF Event Timer",
            'day': "Day/Night cycle"
        }.get(group)
        embed = discord.Embed(
            title=title, color=await self.get_embed_color(ctx))
        for location in maps:
            duration_so_far = 0
            current_phase = None
            index = 0
            phases = location['phases']
            for i, phase in enumerate(phases):
                if position < duration_so_far:
                    break
                current_phase = phase['name']
                index = i
                duration_so_far += phase['duration']
            index += 1
            if index == len(phases):
                if phases[0]['name'] == phases[index - 1]['name']:
                    index = 1
                    duration_so_far += phases[0]['duration']
                else:
                    index = 0
            next_phase = phases[index]['name']
            time_until = duration_so_far - position
            value = (f"Current phase: **{current_phase}**"
                     f"\nNext phase: **{next_phase}** in **{time_until}** minutes")
            embed.add_field(name=location['name'], value=value, inline=False)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        return embed
