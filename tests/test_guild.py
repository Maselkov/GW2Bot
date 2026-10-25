"""/guild info, members, treasury and log, and the guild name autocomplete."""
import datetime

import pytest

import subject

API = "https://api.guildwars2.com/v2/"
GUILD = "4BBB52AA-D768-4FC6-8EDE-C299F2822F0F"
ZWSP = "\u200b"


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


# Synthetic guild data (never real guild data)
BASE = {
    "id": GUILD, "name": "Example Guild", "tag": "EX", "level": 69, "influence": 1000, "aetherium": 2500,
    "resonance": 300, "favor": 450, "member_count": 120, "member_capacity": 500, "motd": "Welcome!",
}
RANKS = [{"id": "Leader", "order": 1}, {"id": "Officer", "order": 2}, {"id": "Member", "order": 3}]
MEMBERS = [
    {"name": "Member.1111", "rank": "Member"},
    {"name": "Example.1234", "rank": "Leader"},
    {"name": "Invited.2222", "rank": "invited"},
    {"name": "Officer.3333", "rank": "Officer"},
]


# --- /guild info -------------------------------------------------------------------------


async def test_info():
    embed, requests = await subject.guild_command("info", [(200, BASE)], guild=GUILD)
    assert embed["description"] == "General Info about Example Guild"
    assert embed["author"]["name"] == "Example Guild [EX]"
    assert fields(embed) == [
        ("Influence", " 1000"),
        ("Aetherium", " 2500"),
        ("Resonance", " 300"),
        ("Favor", " 450"),
        ("Members", " 120/500"),
        ("Message of the day:", "Welcome!"),
    ]
    assert embed["footer"]["text"] == "A level 69 guild"
    assert requests == [(API + "guild/" + GUILD, {"access_token": "KEY"})]


async def test_info_needs_guilds_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError, match="`guilds`"):
        await subject.guild_command("info", [], permissions=("account",), guild=GUILD)


# --- /guild members ------------------------------------------------------------------------


async def test_members_by_rank_in_dms():
    embed, requests = await subject.guild_command(
        "members", [(200, BASE), (200, MEMBERS), (200, RANKS)], guild=GUILD
    )
    assert embed["title"] == "Example Guild"
    # Leaders first, invited members left out
    assert fields(embed) == [("> **MEMBERS**", "\n".join([
        "**Example.1234**\n*Leader*", "**Officer.3333**\n*Officer*", "**Member.1111**\n*Member*",
    ]))]
    assert [url for url, _ in requests] == [
        API + "guild/" + GUILD, API + f"guild/{GUILD}/members", API + f"guild/{GUILD}/ranks",
    ]


async def test_members_mention_people_on_the_server():
    users = {2: subject.stored_key(["account"], account_name="Officer.3333"),
             3: subject.stored_key(["account"], account_name="Member.1111")}
    # User 3 isn't on this server
    embed, _ = await subject.guild_command(
        "members", [(200, BASE), (200, MEMBERS), (200, RANKS)], users=users, discord_members={1: "<@1>", 2: "<@2>"},
        guild=GUILD,
    )
    assert fields(embed)[0][1] == "\n".join([
        "**Example.1234** - <@1>\n*Leader*", "**Officer.3333** - <@2>\n*Officer*", "**Member.1111**\n*Member*",
    ])


async def test_members_chunk_the_server_first():
    users = {2: subject.stored_key(["account"], account_name="Officer.3333")}
    embed, _ = await subject.guild_command(
        "members", [(200, BASE), (200, MEMBERS), (200, RANKS)], users=users, discord_members={1: "<@1>", 2: "<@2>"},
        chunked=False, guild=GUILD,
    )
    assert fields(embed)[0][1].startswith("**Example.1234** - <@1>\n*Leader*\n**Officer.3333** - <@2>")


async def test_members_over_several_pages():
    members = [{"name": f"Member{i:03}.{i:04}", "rank": "Member"} for i in range(300)]
    embed, _ = await subject.guild_command(
        "members", [(200, BASE), (200, members), (200, RANKS)], guild=GUILD
    )
    assert embed["footer"]["text"] == "Page 1/2"
    assert fields(embed)[0][1].startswith("**Member000.0000**\n*Member*")


# --- /guild treasury ---------------------------------------------------------------------------


async def test_treasury():
    treasury = [
        {"item_id": 1, "count": 10, "needed_by": [{"upgrade_id": 1, "count": 25}, {"upgrade_id": 2, "count": 5}]},
        {"item_id": 2, "count": 50, "needed_by": [{"upgrade_id": 3, "count": 50}]},
    ]
    items = [{"_id": 1, "name": "Pile of Bloodstone Dust"}, {"_id": 2, "name": "Iron Ore"}]
    embed, requests = await subject.guild_command(
        "treasury", [(200, BASE), (200, treasury)], items=items, guild=GUILD
    )
    assert embed["author"]["name"] == "Example Guild"
    # Fully stocked items are left out
    assert fields(embed) == [("> **TREASURY**", "**Pile of Bloodstone Dust**\n*10/30*")]
    assert [url for url, _ in requests] == [API + "guild/" + GUILD, API + f"guild/{GUILD}/treasury"]


async def test_empty_treasury():
    sent, _ = await subject.guild_command("treasury", [(200, BASE), (200, [])], guild=GUILD)
    assert sent == "Treasury is empty!"


# --- /guild log ----------------------------------------------------------------------------------

LOG = [
    {"id": 6, "time": "2024-03-05T10:06:00.000Z", "type": "stash", "user": "Example.1234", "operation": "deposit",
     "item_id": 0, "count": 0, "coins": 12345},
    {"id": 5, "time": "2024-03-05T10:05:00.000Z", "type": "stash", "user": "Member.1111", "operation": "withdraw",
     "item_id": 1, "count": 3, "coins": 0},
    {"id": 4, "time": "2024-03-05T10:04:00.000Z", "type": "treasury", "user": "Member.1111", "item_id": 1,
     "count": 25},
    {"id": 3, "time": "2024-03-05T10:03:00.000Z", "type": "joined", "user": "Member.1111"},
    {"id": 2, "time": "2024-03-05T10:02:00.000Z", "type": "kick", "user": "Gone.4444", "kicked_by": "Gone.4444"},
    {"id": 1, "time": "2024-03-05T10:01:00.000Z", "type": "kick", "user": "Kicked.5555",
     "kicked_by": "Example.1234"},
    {"id": 0, "time": "2024-03-05T10:00:00.000Z", "type": "motd", "user": "Example.1234", "motd": "Hi"},
]
LOG_ITEMS = [{"_id": 1, "name": "Pile of Bloodstone Dust"}]


async def log(log_type, entries=LOG):
    embed, requests = await subject.guild_command(
        "log", [(200, BASE), (200, entries)], items=LOG_ITEMS, guild=GUILD, log_type=log_type
    )
    assert [url for url, _ in requests] == [API + "guild/" + GUILD, API + f"guild/{GUILD}/log/"]
    return embed


async def test_stash_log():
    embed = await log("stash")
    assert embed["author"]["name"] == "Example Guild"
    assert fields(embed) == [("> **Stash Log**", "\n".join([
        "**05.03.2024 10:06**\n*Example.1234 deposited  1 gold 23 silver 45 copper *",
        "**05.03.2024 10:05**\n*Member.1111 withdrew 3x Pile of Bloodstone Dust*",
    ]))]


async def test_treasury_log():
    embed = await log("treasury")
    assert fields(embed) == [
        ("> **Treasury Log**", "**05.03.2024 10:04**\n*Member.1111 donated 25x Pile of Bloodstone Dust*"),
    ]


async def test_members_log():
    embed = await log("members")
    assert fields(embed) == [("> **Members Log**", "\n".join([
        "**05.03.2024 10:03**\n*Member.1111 has joined the guild.*",
        "**05.03.2024 10:02**\n*Gone.4444 has left the guild.*",
        "**05.03.2024 10:01**\n*Kicked.5555 has been kicked by Example.1234.*",
    ]))]


async def test_empty_log():
    sent, _ = await subject.guild_command(
        "log", [(200, BASE), (200, LOG[3:])], guild=GUILD, log_type="stash"
    )
    assert sent == "No stash log entries yet for Example Guild"


# --- Guild name autocomplete -------------------------------------------------------------------

NOW = datetime.datetime(2024, 3, 6, 12)
GUILDS = [{"name": "Example Guild", "id": GUILD}, {"name": "Other Guild", "id": "OTHER-ID"}]


def cached(guilds, updated):
    return {**subject.stored_key(["account", "guilds"]),
            "guild_cache": {"Example_1234": {"last_update": updated, "guild_list": guilds}}}


async def test_autocomplete_from_the_cache_with_the_server_default():
    choices, writes, requests = await subject.guild_choices(
        "example", cached(GUILDS, NOW - datetime.timedelta(days=1)), server_default="DEFAULT-ID", now=NOW
    )
    # The server's default guild comes first, whatever was typed
    assert choices == [("Server's default guild", "DEFAULT-ID"), ("Example Guild", GUILD)]
    assert writes == requests == []


async def test_autocomplete_refreshes_an_old_cache_in_the_background():
    responses = [(200, {"name": "Example.1234", "guilds": [GUILD]}), (200, GUILDS[0])]
    choices, writes, requests = await subject.guild_choices(
        "", cached(GUILDS, NOW - datetime.timedelta(days=8)), responses, now=NOW
    )
    assert choices == [("Example Guild", GUILD), ("Other Guild", "OTHER-ID")]
    assert writes == [("set", {"guild_cache.Example_1234": {"last_update": NOW, "guild_list": GUILDS[:1]}})]
    assert [url for url, _ in requests] == [API + "account", API + "guild/" + GUILD]


async def test_autocomplete_without_a_key():
    choices, writes, requests = await subject.guild_choices("", {}, now=NOW)
    assert choices == writes == requests == []


# --- Fixes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("status, message", [
    (404, "Invalid guild name"),
    (403, "You don't have enough permissions in game to use this command"),
])
async def test_info_errors(status, message):
    sent, _ = await subject.guild_command("info", [(status, {"text": "error"})], guild=GUILD)
    assert sent == message


async def test_autocomplete_fills_the_cache():
    responses = [(200, {"name": "Example.1234", "guilds": [GUILD]}), (200, GUILDS[0])]
    choices, writes, _ = await subject.guild_choices(
        "", subject.stored_key(["account", "guilds"]), responses, now=NOW
    )
    assert choices == [("Example Guild", GUILD)]
    assert writes == [("set", {"guild_cache.Example_1234": {"last_update": NOW, "guild_list": GUILDS[:1]}})]


async def test_members_log_invites_and_rank_changes():
    entries = [
        {"id": 3, "time": "2024-03-05T10:03:00.000Z", "type": "invited", "user": "New.6666",
         "invited_by": "Example.1234"},
        {"id": 2, "time": "2024-03-05T10:02:00.000Z", "type": "rank_change", "user": "Member.1111",
         "old_rank": "Member", "new_rank": "Officer", "changed_by": "Example.1234"},
        {"id": 1, "time": "2024-03-05T10:01:00.000Z", "type": "rank_change", "user": "Member.1111",
         "old_rank": "Officer", "new_rank": "Member"},
    ]
    embed = await log("members", entries)
    assert fields(embed)[0][1] == "\n".join([
        "**05.03.2024 10:03**\n*Example.1234 has invited New.6666 to the guild.*",
        "**05.03.2024 10:02**\n*Example.1234 has changed the role of Member.1111 from Member to Officer.*",
        "**05.03.2024 10:01**\n*Member.1111 changed their role from Officer to Member.*",
    ])


async def test_uncached_items():
    treasury = [{"item_id": 9, "count": 1, "needed_by": [{"upgrade_id": 1, "count": 2}]}]
    embed, _ = await subject.guild_command("treasury", [(200, BASE), (200, treasury)], guild=GUILD)
    assert fields(embed) == [("> **TREASURY**", "**Unknown item**\n*1/2*")]
    entries = [{"id": 1, "time": "2024-03-05T10:05:00.000Z", "type": "stash", "user": "Member.1111",
                "operation": "withdraw", "item_id": 9, "count": 3, "coins": 0}]
    embed = await log("stash", entries)
    assert fields(embed)[0][1] == "**05.03.2024 10:05**\n*Member.1111 withdrew 3x Unknown item*"
