"""Stand-ins for what the bot talks to, for the adapters in subject.py.

- bot: the bot itself (game data, the API client, keys, emojis), the
  clock, and running a slash command with a fake interaction.
- http: the GW2 API and other websites (the wiki, the forum, dps.report).
- db: MongoDB collections and the users / guilds / channels settings.
- discord: servers, roles, members and channels.

All data in tests is synthetic, never from a real account.
"""
