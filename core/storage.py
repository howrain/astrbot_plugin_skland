from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
import uuid


class StorageService:
    def __init__(self, plugin):
        self.plugin = plugin

    async def get_all_users(self) -> dict[str, dict]:
        users = await self.plugin.get_kv_data("users", {})
        normalized: dict[str, dict] = {}
        changed = False
        for user_id, raw in users.items():
            user_id_str = str(user_id)
            normalized_user, was_changed = self._normalize_user_record(user_id_str, raw)
            normalized[user_id_str] = normalized_user
            changed = changed or was_changed
        if changed:
            await self.plugin.put_kv_data("users", normalized)
        return normalized

    async def save_all_users(self, users: dict[str, dict]):
        await self.plugin.put_kv_data("users", users)

    async def get_user(self, user_id: str) -> dict | None:
        users = await self.get_all_users()
        return users.get(str(user_id))

    async def save_user(self, user_id: str, user_data: dict):
        users = await self.get_all_users()
        users[str(user_id)] = user_data
        await self.save_all_users(users)

    async def delete_user(self, user_id: str):
        users = await self.get_all_users()
        users.pop(str(user_id), None)
        await self.save_all_users(users)

    async def get_primary_account(self, user_id: str) -> dict | None:
        user_data = await self.get_user(user_id)
        if not user_data:
            return None
        accounts = user_data.get("accounts", [])
        if not accounts:
            return None
        primary_id = user_data.get("primary_account_id")
        for account in accounts:
            if account.get("id") == primary_id:
                return deepcopy(account)
        return deepcopy(accounts[0])

    async def bind_or_replace_primary_account(self, user_id: str, account: dict):
        user_id = str(user_id)
        users = await self.get_all_users()
        user_data = users.get(user_id) or {
            "accounts": [],
            "primary_account_id": "",
        }

        account = deepcopy(account)
        account.setdefault("id", uuid.uuid4().hex)
        account.setdefault("bound_at", datetime.now().isoformat())
        account.setdefault("last_sign", {})

        accounts = user_data.get("accounts", [])
        replaced = False
        for idx, existing in enumerate(accounts):
            if existing.get("id") == user_data.get("primary_account_id"):
                merged = deepcopy(existing)
                merged.update(account)
                accounts[idx] = merged
                account = merged
                replaced = True
                break

        if not replaced:
            accounts = [account]

        user_data["accounts"] = accounts
        user_data["primary_account_id"] = account["id"]
        user_data["last_updated_at"] = datetime.now().isoformat()
        users[user_id] = user_data
        await self.save_all_users(users)

    async def update_primary_account(self, user_id: str, updater):
        user_id = str(user_id)
        users = await self.get_all_users()
        user_data = users.get(user_id)
        if not user_data:
            return None
        primary_id = user_data.get("primary_account_id")
        accounts = user_data.get("accounts", [])
        updated_account = None
        for idx, account in enumerate(accounts):
            if account.get("id") == primary_id or (not primary_id and idx == 0):
                working = deepcopy(account)
                updater(working)
                accounts[idx] = working
                updated_account = working
                if not user_data.get("primary_account_id"):
                    user_data["primary_account_id"] = working.get("id")
                break
        if updated_account is None:
            return None
        user_data["accounts"] = accounts
        user_data["last_updated_at"] = datetime.now().isoformat()
        users[user_id] = user_data
        await self.save_all_users(users)
        return updated_account

    async def get_groups(self) -> dict[str, list[str]]:
        groups = await self.plugin.get_kv_data("groups", {})
        normalized: dict[str, list[str]] = {}
        for group_id, members in groups.items():
            normalized[str(group_id)] = [str(member) for member in members or []]
        return normalized

    async def touch_group_member(self, group_id: str, user_id: str):
        groups = await self.get_groups()
        gid = str(group_id)
        uid = str(user_id)
        members = groups.setdefault(gid, [])
        if uid not in members:
            members.append(uid)
            await self.plugin.put_kv_data("groups", groups)

    def _normalize_user_record(self, user_id: str, raw: Any) -> tuple[dict, bool]:
        changed = False
        if not isinstance(raw, dict):
            raw = {}
            changed = True

        if "accounts" in raw:
            accounts = raw.get("accounts") or []
            normalized_accounts = []
            for account in accounts:
                norm_account = deepcopy(account) if isinstance(account, dict) else {}
                if not norm_account.get("id"):
                    norm_account["id"] = uuid.uuid4().hex
                    changed = True
                norm_account.setdefault("bound_at", raw.get("bound_at") or datetime.now().isoformat())
                norm_account.setdefault("last_sign", {})
                normalized_accounts.append(norm_account)
            primary_id = raw.get("primary_account_id")
            if normalized_accounts and not primary_id:
                primary_id = normalized_accounts[0]["id"]
                changed = True
            return {
                "accounts": normalized_accounts,
                "primary_account_id": primary_id or "",
                "last_updated_at": raw.get("last_updated_at", raw.get("bound_at", "")),
            }, changed

        legacy_account = {
            "id": uuid.uuid4().hex,
            "token": raw.get("token", ""),
            "cred": raw.get("cred", ""),
            "nickname": raw.get("nickname", ""),
            "last_username": raw.get("last_username", ""),
            "last_sign": deepcopy(raw.get("last_sign", {})),
            "bound_at": raw.get("bound_at", datetime.now().isoformat()),
            "platform_name": raw.get("platform_name", ""),
            "umo": raw.get("umo", ""),
            "login_type": raw.get("login_type", "token"),
        }
        changed = True
        return {
            "accounts": [legacy_account] if legacy_account.get("token") else [],
            "primary_account_id": legacy_account["id"] if legacy_account.get("token") else "",
            "last_updated_at": raw.get("bound_at", ""),
        }, changed
