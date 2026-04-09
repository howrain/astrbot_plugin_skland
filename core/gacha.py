from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime

import httpx


GACHA_TABLE_URL = "https://weedy.prts.wiki/gacha_table.json"
GACHA_RULE_TYPES = {
    "limit": {1, 2, 3, 8},
    "normal": {0, 5, 9},
    "classic": {4, 6, 7, 10},
}
POOL_TYPE_LABELS = {
    "limit": "限定",
    "normal": "常驻",
    "classic": "中坚",
}


class GachaService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=25.0)
        self._gacha_table: dict | None = None
        self._up_char_cache: dict[str, tuple[list[str], list[str]]] = {}

    async def close(self):
        await self.client.aclose()

    async def get_grant_code(self, token: str) -> str:
        resp = await self.client.post(
            "https://as.hypergryph.com/user/oauth2/v2/grant",
            json={"appCode": "be36d44aa36bfb5b", "token": token, "type": 1},
            headers={
                "User-Agent": "Skland/1.21.0 (com.hypergryph.skland; build:102100065; iOS 17.6.0; ) Alamofire/5.7.1",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            raise RuntimeError("获取 grant_code 失败")
        return data["data"]["token"]

    async def get_role_token(self, uid: str, grant_code: str) -> str:
        resp = await self.client.post(
            "https://binding-api-account-prod.hypergryph.com/account/binding/v1/u8_token_by_uid",
            json={"uid": uid, "token": grant_code},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            raise RuntimeError("获取 role_token 失败")
        return data["data"]["token"]

    async def get_ak_cookie(self, role_token: str) -> str:
        resp = await self.client.post(
            "https://ak.hypergryph.com/user/api/role/login",
            json={"token": role_token},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError("获取 ak cookie 失败")
        cookie_headers = resp.headers.get_list("set-cookie")
        joined = "; ".join(cookie_headers)
        match = re.search(r"ak-user-center=([^;]+)", joined)
        if not match:
            raise RuntimeError("未能获取 ak-user-center cookie")
        return match.group(1)

    async def get_categories(self, uid: str, role_token: str, token: str, ak_cookie: str) -> list[dict]:
        resp = await self.client.get(
            "https://ak.hypergryph.com/user/api/inquiry/gacha/cate",
            params={"uid": uid},
            headers={
                "X-Account-Token": token,
                "X-Role-Token": role_token,
                "Cookie": f"ak-user-center={ak_cookie}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError("获取卡池分类失败")
        return data.get("data") or []

    async def get_gacha_history(
        self,
        uid: str,
        category: str,
        role_token: str,
        token: str,
        ak_cookie: str,
        gacha_ts: str | None = None,
        pos: int | None = None,
    ) -> dict:
        params = {"uid": uid, "category": category, "size": 100}
        if gacha_ts and pos is not None:
            params["gachaTs"] = gacha_ts
            params["pos"] = pos
        resp = await self.client.get(
            "https://ak.hypergryph.com/user/api/inquiry/gacha/history",
            params=params,
            headers={
                "X-Account-Token": token,
                "X-Role-Token": role_token,
                "Cookie": f"ak-user-center={ak_cookie}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError("获取抽卡记录失败")
        return data.get("data") or {}

    async def get_all_records(
        self,
        uid: str,
        token: str,
        pool_name: str = "",
        limit: int | None = None,
        max_pages_per_category: int = 30,
    ) -> list[dict]:
        grant_code = await self.get_grant_code(token)
        role_token = await self.get_role_token(uid, grant_code)
        ak_cookie = await self.get_ak_cookie(role_token)
        categories = await self.get_categories(uid, role_token, token, ak_cookie)
        records: list[dict] = []
        seen: set[tuple[str, str, int]] = set()

        for cate in categories:
            last_ts: str | None = None
            last_pos: int | None = None
            for _ in range(max_pages_per_category):
                data = await self.get_gacha_history(uid, cate["id"], role_token, token, ak_cookie, last_ts, last_pos)
                items = data.get("list") or []
                if not items:
                    break
                for item in items:
                    record_key = (
                        str(item.get("poolId", "")),
                        str(item.get("gachaTs", "")),
                        int(item.get("pos", 0)),
                    )
                    if record_key in seen:
                        continue
                    seen.add(record_key)
                    records.append(item)
                if len(items) < 100:
                    break
                last = items[-1]
                last_ts = str(last.get("gachaTs", ""))
                last_pos = int(last.get("pos", 0))

        records.sort(key=lambda item: (int(item.get("gachaTs", 0)), int(item.get("pos", 0))), reverse=True)
        if pool_name:
            keyword = pool_name.lower()
            records = [item for item in records if keyword in str(item.get("poolName", "")).lower()]
        if limit is not None:
            return records[:limit]
        return records

    async def get_recent_records(
        self,
        uid: str,
        token: str,
        limit: int = 20,
        pool_name: str = "",
    ) -> list[dict]:
        return await self.get_all_records(uid, token, pool_name=pool_name, limit=limit)

    async def _ensure_gacha_table(self) -> dict:
        if self._gacha_table is None:
            resp = await self.client.get(GACHA_TABLE_URL, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            self._gacha_table = resp.json()
        return self._gacha_table

    async def _get_pool_info(self, pool_id: str) -> dict:
        table = await self._ensure_gacha_table()
        for pool in table.get("gachaPoolClient", []):
            if pool.get("gachaPoolId") == pool_id:
                return pool
        return {}

    async def _get_up_chars(self, pool_id: str) -> tuple[list[str], list[str]]:
        if pool_id in self._up_char_cache:
            return self._up_char_cache[pool_id]
        pool = await self._get_pool_info(pool_id)
        detail = ((pool.get("gachaPoolDetail") or {}).get("detailInfo") or {}).get("upCharInfo") or {}
        up_six: list[str] = []
        up_five: list[str] = []
        for item in detail.get("perCharList") or []:
            char_ids = item.get("charIdList") or []
            if item.get("rarityRank") == 5:
                up_six.extend(char_ids)
            elif item.get("rarityRank") == 4:
                up_five.extend(char_ids)
        self._up_char_cache[pool_id] = (up_six, up_five)
        return self._up_char_cache[pool_id]

    def _get_pool_type(self, rule_type: int | None) -> str:
        if rule_type in GACHA_RULE_TYPES["limit"]:
            return "limit"
        if rule_type in GACHA_RULE_TYPES["classic"]:
            return "classic"
        return "normal"

    def _get_char_avatar(self, char_id: str) -> str:
        safe_id = str(char_id or "").replace("@", "%40").replace("#", "%23")
        return f"https://web.hycdn.cn/arknights/game/assets/char_skin/avatar/{safe_id}%231.png"

    async def build_record_view(
        self,
        records: list[dict],
        user_name: str,
        user_uid: str,
        user_level: int | str,
        user_avatar: str,
        server_label: str,
        title: str,
    ) -> dict:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            grouped[str(record.get("poolId", ""))].append(record)

        sections = []
        category_totals = {
            "limit": {"pulls": 0, "six": 0, "spook": 0, "avg": 0.0, "pity": 0},
            "normal": {"pulls": 0, "six": 0, "spook": 0, "avg": 0.0, "pity": 0},
            "classic": {"pulls": 0, "six": 0, "spook": 0, "avg": 0.0, "pity": 0},
        }
        avg_samples: dict[str, list[int]] = defaultdict(list)

        for pool_id, pool_records in grouped.items():
            pool_records = sorted(pool_records, key=lambda item: (int(item.get("gachaTs", 0)), int(item.get("pos", 0))))
            pool_info = await self._get_pool_info(pool_id)
            up_six_chars, _ = await self._get_up_chars(pool_id)
            rule_type = pool_info.get("gachaRuleType")
            pool_type = self._get_pool_type(rule_type)
            pool_total = len(pool_records)
            pity_count = 0
            five_star_chars: list[dict] = []
            six_star_entries: list[dict] = []

            for record in pool_records:
                pity_count += 1
                rarity = int(record.get("rarity", 0)) + 1
                if rarity == 5:
                    five_star_chars.append(
                        {
                            "name": record.get("charName", "未知干员"),
                            "avatar": self._get_char_avatar(record.get("charId", "")),
                        }
                    )
                if rarity == 6:
                    char_id = str(record.get("charId", ""))
                    is_up = char_id in up_six_chars if up_six_chars else False
                    six_star_entries.append(
                        {
                            "date": self._format_date(record.get("gachaTs")),
                            "name": record.get("charName", "未知干员"),
                            "avatar": self._get_char_avatar(char_id),
                            "pity_count": pity_count,
                            "bar_width": min(110, max(22, 10 + pity_count)),
                            "bar_class": self._get_bar_class(pity_count),
                            "is_new": bool(record.get("isNew")),
                            "is_up": is_up,
                            "is_off_banner": bool(up_six_chars) and not is_up,
                            "is_lucky": pity_count <= 20,
                            "is_very_lucky": pity_count <= 10,
                            "is_very_unlucky": pity_count >= 60,
                            "five_stars": five_star_chars[-8:],
                        }
                    )
                    avg_samples[pool_type].append(pity_count)
                    pity_count = 0
                    five_star_chars = []

            sections.append(
                {
                    "pool_name": pool_records[-1].get("poolName", "未知卡池"),
                    "pool_type_label": POOL_TYPE_LABELS[pool_type],
                    "pool_type": pool_type,
                    "up_avatars": [self._get_char_avatar(char_id) for char_id in up_six_chars[:3]],
                    "pool_total": pool_total,
                    "entries": list(reversed(six_star_entries)),
                    "current_pity": min(pity_count, 99),
                    "current_rate": f"{2 + max(0, pity_count - 50) * 2:.0f}%" if pity_count >= 50 else "2%",
                    "sort_time": max(int(item.get("gachaTs", 0)) for item in pool_records),
                }
            )

            category_totals[pool_type]["pulls"] += pool_total
            category_totals[pool_type]["six"] += len(six_star_entries)
            category_totals[pool_type]["spook"] += len([entry for entry in six_star_entries if entry["is_off_banner"]])
            category_totals[pool_type]["pity"] = max(category_totals[pool_type]["pity"], min(pity_count, 99))

        for pool_type, values in category_totals.items():
            if avg_samples[pool_type]:
                values["avg"] = round(sum(avg_samples[pool_type]) / len(avg_samples[pool_type]), 1)

        sections.sort(key=lambda item: item["sort_time"], reverse=True)
        return {
            "title": title,
            "user": {
                "name": user_name,
                "uid": user_uid,
                "level": user_level,
                "avatar": user_avatar,
                "server_label": server_label,
            },
            "summary": [
                {
                    "label": "限定",
                    "pulls": category_totals["limit"]["pulls"],
                    "six": category_totals["limit"]["six"],
                    "spook": category_totals["limit"]["spook"],
                    "avg": category_totals["limit"]["avg"],
                    "pity": category_totals["limit"]["pity"],
                    "rate": f"{2 + max(0, category_totals['limit']['pity'] - 50) * 2:.0f}%" if category_totals["limit"]["pity"] >= 50 else "2%",
                },
                {
                    "label": "常驻",
                    "pulls": category_totals["normal"]["pulls"],
                    "six": category_totals["normal"]["six"],
                    "spook": category_totals["normal"]["spook"],
                    "avg": category_totals["normal"]["avg"],
                    "pity": category_totals["normal"]["pity"],
                    "rate": f"{2 + max(0, category_totals['normal']['pity'] - 50) * 2:.0f}%" if category_totals["normal"]["pity"] >= 50 else "2%",
                },
                {
                    "label": "中坚",
                    "pulls": category_totals["classic"]["pulls"],
                    "six": category_totals["classic"]["six"],
                    "spook": category_totals["classic"]["spook"],
                    "avg": category_totals["classic"]["avg"],
                    "pity": category_totals["classic"]["pity"],
                    "rate": f"{2 + max(0, category_totals['classic']['pity'] - 50) * 2:.0f}%" if category_totals["classic"]["pity"] >= 50 else "2%",
                },
            ],
            "sections": sections,
        }

    async def analyze_records(
        self,
        records: list[dict],
        user_name: str,
        user_uid: str,
        user_level: int | str,
        user_avatar: str,
        server_label: str,
    ) -> dict:
        six_star_records = [item for item in records if int(item.get("rarity", 0)) + 1 == 6]
        char_counter = Counter(item.get("charId", "") for item in six_star_records if item.get("charId"))
        total_up = 0
        for item in six_star_records:
            up_six, _ = await self._get_up_chars(str(item.get("poolId", "")))
            if str(item.get("charId", "")) in up_six:
                total_up += 1

        avg_six = round(len(records) / len(six_star_records), 1) if six_star_records else 0.0
        avg_up = round(len(records) / total_up, 1) if total_up else 0.0
        up_rate = round(total_up / len(six_star_records) * 100, 1) if six_star_records else 0.0
        evaluation = self._evaluate_luck(avg_six)

        chars = []
        for char_id, count in char_counter.most_common(12):
            sample = next(item for item in six_star_records if item.get("charId") == char_id)
            chars.append(
                {
                    "char_id": char_id,
                    "char_name": sample.get("charName", "未知干员"),
                    "count": count,
                    "avatar": self._get_char_avatar(char_id),
                }
            )

        return {
            "user": {
                "name": user_name,
                "uid": user_uid,
                "level": user_level,
                "avatar": user_avatar,
                "server_label": server_label,
            },
            "analysis": {
                "total_pulls": len(records),
                "avg_six_star_pulls": avg_six,
                "evaluation": evaluation,
                "up_six_star": total_up,
                "total_six_star": len(six_star_records),
                "up_six_star_rate": up_rate,
                "avg_up_pulls": avg_up,
                "six_star_chars": chars,
            },
        }

    def _evaluate_luck(self, avg_six: float) -> str:
        if avg_six <= 18:
            return "至尊欧皇"
        if avg_six <= 22:
            return "大欧皇"
        if avg_six <= 27:
            return "欧皇"
        if avg_six <= 33:
            return "欧洲人"
        if avg_six <= 39:
            return "欧非守恒"
        if avg_six <= 45:
            return "非洲人"
        if avg_six <= 50:
            return "非酋"
        if avg_six <= 56:
            return "大非酋"
        return "超级非酋"

    def _get_bar_class(self, pity_count: int) -> str:
        if pity_count >= 60:
            return "spook"
        if pity_count >= 35:
            return "up"
        return "normal"

    def _format_date(self, gacha_ts: str | int | None) -> str:
        if not gacha_ts:
            return "--"
        value = int(gacha_ts)
        if value > 10_000_000_000:
            value = value // 1000
        return datetime.fromtimestamp(value).strftime("%m-%d")
