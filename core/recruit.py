from __future__ import annotations

import itertools

import httpx


PRTS_API_URL = (
    "https://prts.wiki/api.php?action=cargoquery&format=json&tables=chara%2Cchar_obtain"
    "&limit=500&fields=chara.profession%2Cchara.position%2Cchara.rarity%2Cchara.tag%2C"
    "chara.cn%2Cchar_obtain.obtainMethod%2Cchara.charId"
    "&where=char_obtain.obtainMethod+like+%22%25%E5%85%AC%E5%BC%80%E6%8B%9B%E5%8B%9F%25%22+"
    "AND+chara.charIndex%3E0&join_on=chara._pageName%3Dchar_obtain._pageName"
)

PROFESSION_MAP = {
    "先锋": "先锋干员",
    "近卫": "近卫干员",
    "重装": "重装干员",
    "狙击": "狙击干员",
    "术师": "术师干员",
    "医疗": "医疗干员",
    "辅助": "辅助干员",
    "特种": "特种干员",
}


class RecruitService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=20.0)
        self._cache: dict | None = None

    async def close(self):
        await self.client.aclose()

    async def get_data(self) -> dict:
        if self._cache:
            return self._cache
        resp = await self.client.get(
            PRTS_API_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot/1.0)"},
        )
        resp.raise_for_status()
        data = resp.json()
        cargo = data.get("cargoquery", [])

        normal = {}
        top = {}
        for item in cargo:
            char = item.get("title", {})
            if not char.get("obtainMethod") or "公开招募" not in char.get("obtainMethod", ""):
                continue
            name = char.get("cn")
            rarity = int(char.get("rarity", 0)) + 1
            tags = []
            if char.get("profession") in PROFESSION_MAP:
                tags.append(PROFESSION_MAP[char["profession"]])
            if char.get("position"):
                tags.append(char["position"])
            if char.get("tag"):
                tags.extend([part for part in str(char["tag"]).split(" ") if part.strip()])
            item_data = {
                "level": rarity,
                "tags": tags[:] + (["资深干员"] if rarity in {4, 5} else []),
                "charId": char.get("charId", ""),
            }
            if rarity == 6:
                top[name] = {"level": rarity, "tags": tags, "charId": char.get("charId", "")}
            else:
                normal[name] = item_data

        self._cache = {"normal": normal, "top": top}
        return self._cache

    async def calculate(self, tags: list[str]) -> dict[str, dict[str, list[str]]]:
        data = await self.get_data()
        normal = data["normal"]
        top = data["top"]
        tags = [tag for tag in tags if tag]
        results = {"6": {}, "5": {}, "4": {}, "1": {}}

        work_tags = tags[:]
        if "高级资深干员" in work_tags:
            base_tags = [t for t in work_tags if t != "高级资深干员"]
            for r in range(len(base_tags), -1, -1):
                for combo in itertools.combinations(base_tags, r):
                    matched = [
                        name for name, info in top.items() if all(tag in info["tags"] for tag in combo)
                    ]
                    if matched:
                        key_tags = ["高级资深干员", *combo]
                        results["6"]["+".join(key_tags)] = sorted(matched)

        for r in range(min(3, len(work_tags)), 0, -1):
            for combo in itertools.combinations(work_tags, r):
                matched = [
                    name for name, info in normal.items() if all(tag in info["tags"] for tag in combo)
                ]
                if not matched:
                    continue
                matched = sorted(matched, key=lambda name: normal[name]["level"], reverse=True)
                levels = [normal[name]["level"] for name in matched]
                min_level = min(levels)
                key = "+".join(combo)
                if min_level == 4:
                    results["4"][key] = matched
                elif min_level == 5:
                    results["5"][key] = matched
                elif min_level == 1:
                    results["1"][key] = matched
                elif min_level > 1:
                    results["4"][key] = matched
        return results
