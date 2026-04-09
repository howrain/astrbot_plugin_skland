from __future__ import annotations

import os
import httpx


YITULIU_API = "https://backend.yituliu.cn/stage/result?expCoefficient=0.633&sampleSize=300"


class MaterialService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=20.0)
        self._cache: dict | None = None
        self._icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "arknights", "material_icons")

    async def close(self):
        await self.client.aclose()

    async def get_data(self) -> dict:
        if self._cache:
            return self._cache
        resp = await self.client.get(YITULIU_API)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError("一图流掉率接口返回异常")
        self._cache = data.get("data") or {}
        return self._cache

    def get_icon_path(self, item_name: str) -> str:
        if not item_name:
            return ""
        icon_path = os.path.join(self._icon_dir, f"{item_name}.png")
        if not os.path.exists(icon_path):
            return ""
        return f"file:///{icon_path.replace(chr(92), '/')}"
