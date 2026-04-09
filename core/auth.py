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
        state = await self.get_scan_state(scan_id)
        if state.get("state") == "done":
            return state.get("scan_code")
        return None

    async def get_scan_state(self, scan_id: str) -> dict:
        resp = await self.client.get(
            "https://as.hypergryph.com/general/v1/scan_status",
            params={"scanId": scan_id},
        )
        resp.raise_for_status()
        data = resp.json()
        payload = data.get("data", {}) or {}
        scan_code = payload.get("scanCode") or ""
        if scan_code:
            return {"state": "done", "scan_code": scan_code, "raw": data}

        state_candidates = [
            payload.get("status"),
            payload.get("state"),
            payload.get("scanStatus"),
            payload.get("scan_state"),
            data.get("msg"),
            data.get("message"),
        ]
        normalized = " ".join(str(item).strip().lower() for item in state_candidates if item not in (None, ""))

        if any(keyword in normalized for keyword in ["reject", "denied", "refuse", "cancel", "拒绝", "取消"]):
            return {"state": "rejected", "scan_code": "", "raw": data}
        if any(keyword in normalized for keyword in ["expire", "timeout", "过期", "失效", "超时"]):
            return {"state": "expired", "scan_code": "", "raw": data}
        if any(keyword in normalized for keyword in ["failed", "error", "invalid", "失败"]):
            return {"state": "failed", "scan_code": "", "raw": data}

        if data.get("status") == 0:
            return {"state": "pending", "scan_code": "", "raw": data}

        return {"state": "pending", "scan_code": "", "raw": data}

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
