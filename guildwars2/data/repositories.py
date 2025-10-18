class Gw2Repository:
    """Thin wrappers over your Mongo collections.

    Keep it minimal and explicit; services call into here.
    """

    def __init__(self, db):
        self.db = db

    async def get_world_name(self, wid: int) -> str | None:
        doc = await self.db.worlds.find_one({"_id": wid})
        if not doc:
            return None
        return doc.get("name")

    async def get_item(self, item_id: int):
        return await self.db.items.find_one({"_id": item_id})

    async def get_stat_name(self, stat_id: int) -> str:
        statset = await self.db.itemstats.find_one({"_id": stat_id})
        if not statset:
            return ""
        return statset.get("name", "")

    async def get_title(self, title_id: int) -> str:
        doc = await self.db.titles.find_one({"_id": title_id})
        return doc.get("name", "") if doc else ""

    async def get_specialization(self, spec_id: int):
        return await self.db.specializations.find_one({"_id": spec_id})

    async def get_public_character(self, name: str):
        return await self.db.characters.find_one({"name": name})
