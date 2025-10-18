class AchievementsService:
    def __init__(self, api_client, repo):
        self.api = api_client
        self.repo = repo

    async def total_possible_ap(self) -> int:
        total = 15000
        cursor = self.repo.db.achievements.find()
        async for ach in cursor:
            flags = ach.get("flags", [])
            if "Repeatable" in flags:
                total += ach.get("point_cap", 0)
            else:
                total += sum(t.get("points", 0) for t in ach.get("tiers", []))
        return total

    def _max_ap(self, ach, repeatable=False) -> int:
        if not ach:
            return 0
        if repeatable:
            return ach.get("point_cap", 0)
        return sum(t.get("points", 0) for t in ach.get("tiers", []))

    def _earned_ap(self, ach, res) -> int:
        if not res:
            return 0
        repeats = res.get("repeated", 0)
        max_possible = self._max_ap(ach, repeats)
        earned = 0
        for tier in ach.get("tiers", []):
            if res.get("current", 0) >= tier.get("count", 0):
                earned += tier.get("points", 0)
        earned += self._max_ap(ach) * repeats
        return min(earned, max_possible)

    async def calculate_user_ap(self, account_achievements, account_doc) -> int:
        total = account_doc.get("daily_ap", 0) + account_doc.get("monthly_ap", 0)
        for ach in account_achievements:
            doc = await self.repo.db.achievements.find_one({"_id": ach["id"]})
            if doc is not None:
                total += self._earned_ap(doc, ach)
        return total
