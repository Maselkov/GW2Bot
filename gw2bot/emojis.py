"""The bot's custom emojis, registered by name with `>emojis register`."""
import re

import discord


class Emojis:
    def __init__(self, bot, config):
        self.bot = bot
        # The config repository; emoji ids are stored under "emojis"
        self.config = config
        self.ids = {}

    async def load(self):
        doc = await self.config.get()
        self.ids = (doc or {}).get("emojis", {})

    async def register(self, name, emoji_id):
        await self.config.update({"emojis." + name.lower(): emoji_id})
        self.ids[name.lower()] = emoji_id

    def get(
        self,
        ctx,
        emoji,
        *,
        fallback=False,
        fallback_fmt="{}",
        return_obj=False,
        force_emoji=False
    ):
        """The emoji named `emoji` as a string (or object), if it can be used
        in `ctx`; otherwise `emoji` formatted with `fallback_fmt` if
        `fallback`, else ""."""
        # This monstrosity is due for a rework. But at least it works
        def get_emoji():
            search_str = emoji.lower().replace(" ", "_")
            # Remove illegal emoji characters
            search_str = re.sub(r"[\.,\,,',\:,\;,!\?]", "", search_str)
            emoji_id = self.ids.get(search_str)
            if emoji_id:
                emoji_obj = self.bot.get_emoji(emoji_id)
                if emoji_obj:
                    if return_obj:
                        return emoji_obj
                    return str(emoji_obj)

        if force_emoji:
            em = get_emoji()
            if em:
                return em
            elif fallback:
                return fallback_fmt.format(emoji)
            return
        if isinstance(ctx, discord.Webhook):
            if ctx.guild:
                can_use = ctx.channel.permissions_for(
                    ctx.guild.default_role
                ).external_emojis
            else:
                can_use = True
            em = get_emoji() if can_use else None
            if em:
                return em
            return fallback_fmt.format(emoji) if fallback else ""
        elif isinstance(ctx, (discord.Message, discord.TextChannel)):
            if ctx.guild:
                me = ctx.guild.me
            else:
                me = self.bot.user
        elif isinstance(ctx, discord.Interaction):
            is_dm = ctx.guild is None
            if not is_dm:
                me = ctx.channel.guild.me
            else:
                em = get_emoji()
                if em:
                    return em
                elif fallback:
                    return fallback_fmt.format(emoji)
                return ""
        else:
            me = None
        if ctx:
            if isinstance(ctx, discord.Interaction):
                can_use = ctx.channel.permissions_for(me).external_emojis
            else:
                if isinstance(ctx, discord.TextChannel):
                    channel = ctx
                elif ctx.channel:
                    channel = ctx.channel
                else:
                    channel = None
                if channel:
                    can_use = channel.permissions_for(me).external_emojis
                else:
                    can_use = True
            if can_use:
                em = get_emoji()
                if em:
                    return em
                elif fallback:
                    return fallback_fmt.format(emoji)
                return ""
        if fallback:
            return fallback_fmt.format(emoji)
        return ""
