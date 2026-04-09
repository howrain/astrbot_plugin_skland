from __future__ import annotations

import httpx


APP_CODE = "4ca99fa6b56cc2ba"


class AuthService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=25.0)

    async def close(self):
        await self.client.aclose()

    async def get_scan_id(self) -> str:
        resp = await self.client.post(
            "https://as.hypergryph.com/general/v1/gen_scan/login",
            json={"appCode": APP_CODE},
            headers={"Content-Type": "application/json;charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0 or data.get("msg") != "OK":
            raise RuntimeError(f"获取扫码 ID 失败: {data}")
        return data["data"]["scanId"]

    async def get_scan_status(self, scan_id: str) -> str | None:
        resp = await self.client.get(
            "https://as.hypergryph.com/general/v1/scan_status",
            params={"scanId": scan_id},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0:
            return None
        return data.get("data", {}).get("scanCode")

    async def get_token_by_scan_code(self, scan_code: str) -> str:
        resp = await self.client.post(
            "https://as.hypergryph.com/user/auth/v1/token_by_scan_code",
            json={"scanCode": scan_code},
            headers={"Content-Type": "application/json;charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != 0 or data.get("msg") != "OK":
            raise RuntimeError(f"通过扫码结果换取 token 失败: {data}")
        return data["data"]["token"]
