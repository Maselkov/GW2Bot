# Run this from the folder of old bot
import time
import json

from pymongo import MongoClient

start = time.time()
client = MongoClient()
old = client.gw2
new = client.toothy

def update_keys():
    for key in old.keys.find():
        updated = {
            "_id": int(key["_id"]),
            "cogs": {
                "GuildWars2": {
                    "key": {
                        "name": key["name"],
                        "account_name": key["account_name"],
                        "permissions": key["permissions"],
                        "key": key["key"]
                    }
                }
            }
        }
        new.users.insert_one(updated)
    print("Users migrated")


def updated_notifier(doc, notifier):
    d = doc.get(notifier)
    if d:
        enabled = d.get("on", False)
        channel = d.get("channel")
        channel = int(channel) if channel else None
        updated = {}
        if enabled:
            updated["on"] = enabled
        if channel:
            updated["channel"] = channel
        return updated


def update_guilds():
    with open("data/red/settings.json", encoding="utf-8", mode="r") as f:
        data = json.load(f)

    for guild in old.settings.find(): 
        updates_channel = guild.get("channel")
        updates_channel = int(updates_channel) if updates_channel else None
        daily_updated = updated_notifier(guild, "daily")
        news_updated = updated_notifier(guild, "news")
        updated = {
            "_id": int(guild["_id"]),
            "cogs": {
                "GuildWars2": {
                    "updates": {
                        "on": guild.get("on", False),
                    }
                }
            }
        }
        gw2 = updated["cogs"]["GuildWars2"]
        if updates_channel:
            gw2["updates"]["channel"] = updates_channel
        if daily_updated:
            gw2["daily"] = daily_updated
        if news_updated:
            gw2["news"] = news_updated
        if guild["_id"] in data:
            prefixes = data[guild["_id"]]["PREFIXES"]
            if prefixes:
                updated["prefixes"] = prefixes
        new.guilds.insert_one(updated)
        print("Guild migrated")


if __name__ == "__main__":
    update_keys()
    update_guilds()
    print("Elapsed time: {}".format(time.time() - start))
