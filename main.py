from __future__ import annotations

import asyncio
from datetime import datetime
import os
import random
import re
import tempfile

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Image, Plain
from astrbot.core.star.config import put_config

from .core.arknights import ArknightsService
from .core.auth import AuthService
from .core.gacha import GachaService
from .core.material import MaterialService
from .core.message import MessageService
from .core.recruit import RecruitService
from .core.render import Renderer
from .core.storage import StorageService
from .skland_api import SklandAPI

PLUGIN_NAME = "astrbot_plugin_skland"


@register(PLUGIN_NAME, "AstrBot", "森空岛自动签到与基础查询插件", "2.0.0")
class SklandPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.api = SklandAPI(max_retries=3)
        self.auth = AuthService()
        self.storage = StorageService(self)
        self.message_service = MessageService()
        self.ark_service = ArknightsService()
        self.gacha_service = GachaService()
        self.material_service = MaterialService()
        self.recruit_service = RecruitService()
        self.renderer = Renderer(os.path.join(os.path.dirname(__file__), "resources"))
        self.scheduler = AsyncIOScheduler()
        self._init_config()

    def _init_config(self):
        put_config(
            namespace=PLUGIN_NAME,
            name="自动签到开关",
            key="auto_sign_enabled",
            value=True,
            description="开启后，将在指定时间自动为所有已注册用户签到，并私发结果",
        )
        put_config(
            namespace=PLUGIN_NAME,
            name="自动签到时间（小时）",
            key="auto_sign_hour",
            value=1,
            description="自动签到执行的小时（0-23），默认凌晨1点",
        )
        put_config(
            namespace=PLUGIN_NAME,
            name="显示玩家名称",
            key="show_player_name",
            value=True,
            description="开启后，将在签到结果中显示森空岛昵称，否则显示QQ昵称",
        )
        put_config(
            namespace=PLUGIN_NAME,
            name="自动签到的延迟",
            key="auto_sign_delay",
            value=10,
            description="开启后，将在签到时进行向后随机延迟（随机范围 0 至 设定的秒数）",
        )
        put_config(
            namespace=PLUGIN_NAME,
            name="最大用户数",
            key="max_users",
            value=10,
            description="允许绑定的最大用户数量，0表示无限制",
        )

    def _get_config(self) -> dict:
        return {
            "auto_sign_enabled": self.config.get("auto_sign_enabled", True),
            "auto_sign_hour": self.config.get("auto_sign_hour", 1),
            "show_player_name": self.config.get("show_player_name", True),
            "auto_sign_delay": self.config.get("auto_sign_delay", 10),
            "max_users": self.config.get("max_users", 10),
        }

    async def initialize(self):
        logger.info("森空岛插件已加载")
        await self.storage.get_all_users()
        config = self._get_config()
        if config.get("auto_sign_enabled", False):
            self._start_auto_sign_job(config.get("auto_sign_hour", 1))
        if not self.scheduler.running:
            self.scheduler.start()

    async def terminate(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
        await self.api.close()
        await self.auth.close()
        await self.ark_service.close()
        await self.gacha_service.close()
        await self.material_service.close()
        await self.recruit_service.close()
        await self.renderer.close()
        logger.info("森空岛插件已卸载")

    def _start_auto_sign_job(self, hour: int = 1):
        hour = max(0, min(23, hour))
        trigger = CronTrigger(hour=hour, minute=0)
        try:
            self.scheduler.remove_job("skland_auto_sign")
        except Exception:
            pass
        self.scheduler.add_job(
            self._auto_sign_all_users,
            trigger=trigger,
            id="skland_auto_sign",
            misfire_grace_time=3600,
        )
        logger.info(f"森空岛自动签到任务已启动，每天 {hour:02d}:00 执行")

    async def _auto_sign_all_users(self):
        config = self._get_config()
        if not config.get("auto_sign_enabled", False):
            return

        users = await self.storage.get_all_users()
        if not users:
            return

        max_delay = config.get("auto_sign_delay", 10)
        for user_id, user_data in users.items():
            account = await self.storage.get_primary_account(user_id)
            if not account or not account.get("token"):
                continue
            if max_delay > 0:
                await asyncio.sleep(random.uniform(0, max_delay))
            try:
                results, nickname = await self.api.do_full_sign_in(account["token"])
                await self.storage.update_primary_account(
                    user_id,
                    lambda acc: self._update_account_after_sign(
                        acc, results, nickname, acc.get("last_username", "")
                    ),
                )
                message = f"森空岛自动签到结果\n\n{self._format_sign_status(results, nickname)}"
                await self._send_private_message(user_id, message)
            except Exception as exc:
                logger.error(f"用户 {user_id} 自动签到失败: {exc}")
                await self._send_private_message(
                    user_id, f"自动签到失败：{exc}\n请使用 /skdlogin 或 /skdscan 重新绑定。"
                )

    async def _send_private_message(self, user_id: str, message: str):
        account = await self.storage.get_primary_account(user_id)
        if not account or not account.get("umo"):
            return
        try:
            await self.context.send_message(account["umo"], MessageChain().message(message))
        except Exception as exc:
            logger.error(f"发送私聊消息失败: {exc}")

    def _is_group(self, event: AstrMessageEvent) -> bool:
        return bool(getattr(event.message_obj, "group_id", None))

    def _is_signed_today(self, result) -> bool:
        if result.success:
            return True
        error = result.error.lower() if result.error else ""
        return any(
            keyword in error
            for keyword in ["已签到", "请勿重复", "重复签到", "already", "签到过", "今日已"]
        )

    def _format_sign_status(self, results: list, nickname: str = "") -> str:
        if not results:
            return "没有绑定游戏"
        lines = []
        if nickname:
            lines.append(f"【{nickname}】")
        for result in results:
            if result.success or self._is_signed_today(result):
                award = ", ".join(result.awards) if getattr(result, "awards", None) else "无奖励"
                lines.append(f"{result.game} 已签到 ({award})")
            else:
                lines.append(f"{result.game} 签到失败: {result.error}")
        return "\n".join(lines)

    def _update_account_after_sign(self, account: dict, results: list, nickname: str, fallback_name: str):
        if nickname:
            account["nickname"] = nickname
        account.setdefault("last_sign", {})
        for result in results:
            if result.game == "明日方舟" and self._is_signed_today(result):
                account["last_sign"]["arknights"] = datetime.now().strftime("%Y-%m-%d")
            elif result.game == "终末地" and self._is_signed_today(result):
                account["last_sign"]["endfield"] = datetime.now().strftime("%Y-%m-%d")
        if fallback_name:
            account["last_username"] = fallback_name
        account["last_checked_at"] = datetime.now().isoformat()

    def _build_recruit_marks(self, player_data: dict) -> tuple[dict[str, str], dict[str, str]]:
        meta_info_map = player_data.get("charInfoMap", {}) or {}
        chars = player_data.get("chars", []) or []
        char_map = {item.get("charId"): item for item in chars if item.get("charId")}
        name_to_mark: dict[str, str] = {}
        name_to_class: dict[str, str] = {}
        for meta in meta_info_map.values():
            name = meta.get("name")
            char_id = meta.get("id")
            if not name or not char_id:
                continue
            owned = char_map.get(char_id)
            if not owned:
                name_to_mark[name] = "未持有"
                name_to_class[name] = "new"
            elif owned.get("potentialRank") == 5:
                name_to_mark[name] = "满潜"
                name_to_class[name] = "max"
            else:
                name_to_mark[name] = "已持有"
                name_to_class[name] = "owned"
        return name_to_mark, name_to_class

    def _get_avatar_url(self, status: dict) -> str:
        avatar = status.get("avatar", {}) or {}
        avatar_type = avatar.get("type")
        avatar_id = avatar.get("id")
        if not avatar_type or not avatar_id:
            return ""
        avatar_id = str(avatar_id).replace("@", "%40").replace("#", "%23")
        if avatar_type == "ICON":
            return f"https://web.hycdn.cn/arknights/game/assets/avatar/{avatar_id}.png"
        return f"https://web.hycdn.cn/arknights/game/assets/char_skin/avatar/{avatar_id}.png"

    def _build_account(self, event: AstrMessageEvent, token: str, cred: str, nickname: str, login_type: str) -> dict:
        return {
            "token": token,
            "cred": cred,
            "nickname": nickname,
            "last_username": event.get_sender_name(),
            "last_sign": {},
            "bound_at": datetime.now().isoformat(),
            "platform_name": event.get_platform_name(),
            "umo": event.unified_msg_origin,
            "login_type": login_type,
        }

    async def _bind_with_token(
        self,
        event: AstrMessageEvent,
        token: str,
        login_type: str = "token",
        cred: str = "",
    ) -> str:
        results, nickname = await self.api.do_full_sign_in(token)
        if not cred:
            try:
                generated = await self.api.get_credential_from_token(token)
                cred = generated.cred
            except Exception:
                cred = ""
        account = self._build_account(event, token, cred, nickname, login_type)
        self._update_account_after_sign(account, results, nickname, event.get_sender_name())
        await self.storage.bind_or_replace_primary_account(event.get_sender_id(), account)
        return self._format_sign_status(results, nickname)

    async def _check_user_limit(self, user_id: str) -> str | None:
        config = self._get_config()
        users = await self.storage.get_all_users()
        max_users = config.get("max_users", 10)
        if user_id not in users and max_users > 0 and len(users) >= max_users:
            return f"绑定失败：已达到最大用户数限制（{max_users} 个）。"
        return None

    @filter.command("skdhelp", alias=["森空岛帮助"])
    async def skdhelp(self, event: AstrMessageEvent):
        config = self._get_config()
        lines = [
            "森空岛帮助",
            "",
            "账号相关：",
            "/skdlogin <token> 或 /森空岛登录 <token>：手动复制 token 绑定并立即签到",
            "/skdscan 或 /森空岛扫码登录：使用森空岛 APP 扫码绑定并立即签到",
            "/skdlogout 或 /森空岛登出：删除当前绑定",
            "/skdusers 或 /森空岛用户：查看当前插件用户统计",
            "",
            "签到相关：",
            "/skd 或 /森空岛：私聊查看自己的签到状态，群聊查看本群已登记成员状态",
            f"自动签到：当前为 {'开启' if config.get('auto_sign_enabled') else '关闭'}，执行时间 {config.get('auto_sign_hour', 1):02d}:00",
            "",
            "明日方舟查询：",
            "/arknights 便签",
            "/arknights 理智",
            "/arknights 剿灭",
            "/arknights 日常",
            "/arknights 周常",
            "/arknights 公告",
            "/arknights 公告 1",
            "/arknights 刷图推荐",
            "/arknights 材料掉率",
            "/arknights 公招查询 支援 远程位",
            "/arknights 肉鸽",
            "/arknights 抽卡记录",
            "/arknights 抽卡分析",
            "命令别名：/明日方舟、/方舟",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("skdlogin", alias=["森空岛登录"])
    async def skdlogin(self, event: AstrMessageEvent, token: str = ""):
        if self._is_group(event):
            yield event.plain_result("请在私聊中使用此命令登录。为保护隐私，请撤回群内消息。")
            return
        limit_error = await self._check_user_limit(str(event.get_sender_id()))
        if limit_error:
            yield event.plain_result(limit_error)
            return
        token = token.strip()
        if not token:
            yield event.plain_result(
                "请先获取 token：\n"
                "1. 登录鹰角通行证后打开 https://web-api.hypergryph.com/account/info/hg\n"
                "2. 复制返回 JSON 中 content 的值\n"
                "3. 私聊发送 /skdlogin <content>"
            )
            return
        yield event.plain_result("正在登录并签到，请稍候...")
        try:
            result_text = await self._bind_with_token(event, token, login_type="token")
            yield event.plain_result(f"登录成功！\n{result_text}")
        except Exception as exc:
            logger.error(f"skdlogin 失败: {exc}")
            yield event.plain_result(f"登录失败：{exc}")

    @filter.command("skdscan", alias=["森空岛扫码登录"])
    async def skdscan(self, event: AstrMessageEvent):
        if self._is_group(event):
            yield event.plain_result("请在私聊中使用扫码登录，以保护账号安全。")
            return
        limit_error = await self._check_user_limit(str(event.get_sender_id()))
        if limit_error:
            yield event.plain_result(limit_error)
            return

        tmp_path = None
        recall_task = None
        client = None
        message_id = None
        try:
            try:
                import qrcode
            except ImportError:
                yield event.plain_result("缺少依赖 qrcode，请先重新安装插件依赖后再使用扫码登录。")
                return
            scan_id = await self.auth.get_scan_id()
            scan_url = f"hypergryph://scan_login?scanId={scan_id}"
            qr = qrcode.QRCode(border=2)
            qr.add_data(scan_url)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            image.save(tmp_path)

            obmsg = [
                {"type": "image", "data": {"file": f"file:///{tmp_path.replace(os.sep, '/')}"}},
                {
                    "type": "text",
                    "data": {
                        "text": "请使用森空岛 APP 扫描二维码完成登录。\n二维码有效时间约 100 秒。"
                    },
                },
            ]
            client, message_id = await self.message_service.send_and_get_msg_id(event, obmsg)
            if message_id is None:
                yield event.chain_result(
                    [
                        Image.fromFileSystem(tmp_path),
                        Plain("请使用森空岛 APP 扫描二维码完成登录。\n二维码有效时间约 100 秒。"),
                    ]
                )
            else:
                recall_task = self.message_service.schedule_recall(client, message_id, 100)

            scan_code = None
            for _ in range(48):
                await asyncio.sleep(2)
                scan_code = await self.auth.get_scan_status(scan_id)
                if scan_code:
                    break

            if not scan_code:
                yield event.plain_result("二维码已超时，请重新发送 /skdscan。")
                return

            token = await self.auth.get_token_by_scan_code(scan_code)
            if recall_task and not recall_task.done():
                recall_task.cancel()
            if client and message_id:
                await self.message_service.recall_now(client, message_id)

            yield event.plain_result("检测到扫码成功，正在登录并签到，请稍候...")
            result_text = await self._bind_with_token(event, token, login_type="scan")
            yield event.plain_result(f"扫码登录成功！\n{result_text}")
        except Exception as exc:
            logger.error(f"skdscan 失败: {exc}")
            yield event.plain_result(f"扫码登录失败：{exc}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    @filter.command("skdlogout", alias=["森空岛登出", "森空岛退出"])
    async def skdlogout(self, event: AstrMessageEvent):
        if self._is_group(event):
            yield event.plain_result("请在私聊中使用此命令登出。为保护隐私，请撤回群内消息。")
            return
        user_id = str(event.get_sender_id())
        user = await self.storage.get_user(user_id)
        if not user:
            yield event.plain_result("您尚未绑定森空岛账号。")
            return
        await self.storage.delete_user(user_id)
        yield event.plain_result("已退出登录并清除绑定信息。")

    @filter.command("skdusers", alias=["森空岛用户"])
    async def skdusers(self, event: AstrMessageEvent):
        users = await self.storage.get_all_users()
        groups = await self.storage.get_groups()
        config = self._get_config()
        max_users = config.get("max_users", 10)

        signed_users = 0
        for user_data in users.values():
            accounts = user_data.get("accounts", [])
            if accounts and accounts[0].get("last_sign"):
                signed_users += 1

        lines = [
            "森空岛用户统计",
            f"总注册用户：{len(users)}",
            f"已产生签到记录用户：{signed_users}",
            f"未产生签到记录用户：{max(0, len(users) - signed_users)}",
        ]
        if event.is_admin():
            if max_users > 0:
                lines.append(f"最大限制：{max_users}")
                lines.append(f"剩余名额：{max(0, max_users - len(users))}")
            if not self._is_group(event):
                if groups:
                    lines.append("")
                    lines.append("群聊分布：")
                    for group_id, member_ids in groups.items():
                        lines.append(f"- 群 {group_id}: {len(member_ids)} 人")
                if len(users) <= 20:
                    lines.append("")
                    lines.append("用户列表：")
                    for user_id, user_data in users.items():
                        account = user_data.get("accounts", [{}])[0]
                        nickname = account.get("nickname") or account.get("last_username") or user_id
                        last_sign = list(account.get("last_sign", {}).values())[-1] if account.get("last_sign") else "未签到"
                        lines.append(f"- {nickname} (最后签到: {last_sign})")
        yield event.plain_result("\n".join(lines))

    @filter.command("skd", alias=["森空岛"])
    async def skd(self, event: AstrMessageEvent):
        user_id = str(event.get_sender_id())
        users = await self.storage.get_all_users()
        if self._is_group(event):
            group_id = str(getattr(event.message_obj, "group_id", ""))
            if user_id in users:
                await self.storage.touch_group_member(group_id, user_id)
            group_users = (await self.storage.get_groups()).get(group_id, [])
            lines = ["森空岛签到统计", "方舟 | 终末 | 昵称", "-----------------"]
            for member_id in group_users:
                account = await self.storage.get_primary_account(member_id)
                if not account or not account.get("token"):
                    continue
                try:
                    results, nickname = await self.api.do_full_sign_in(account["token"])
                    nickname = nickname or account.get("last_username") or "(未知)"
                    await self.storage.update_primary_account(
                        member_id,
                        lambda acc: self._update_account_after_sign(
                            acc, results, nickname, acc.get("last_username", "")
                        ),
                    )
                    refreshed = await self.storage.get_primary_account(member_id)
                    ak_icon = "OK" if refreshed and refreshed.get("last_sign", {}).get("arknights") else "--"
                    ef_icon = "OK" if refreshed and refreshed.get("last_sign", {}).get("endfield") else "--"
                    lines.append(f"{ak_icon} | {ef_icon} | {nickname}")
                except Exception:
                    lines.append("ERR | ERR | (查询失败)")
            yield event.plain_result("\n".join(lines))
            return

        account = await self.storage.get_primary_account(user_id)
        if not account or not account.get("token"):
            yield event.plain_result("你还未绑定账号，请使用 /skdlogin <token> 或 /skdscan。")
            return
        try:
            results, nickname = await self.api.do_full_sign_in(account["token"])
            await self.storage.update_primary_account(
                user_id,
                lambda acc: self._update_account_after_sign(
                    acc, results, nickname, event.get_sender_name()
                ),
            )
            yield event.plain_result(self._format_sign_status(results, nickname))
        except Exception as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @filter.command("arknights", alias=["明日方舟", "方舟"])
    async def arknights(
        self,
        event: AstrMessageEvent,
        action: str = "",
        arg1: str = "",
        arg2: str = "",
        arg3: str = "",
        arg4: str = "",
    ):
        action = (action or "").strip()
        extra_args = [part.strip() for part in [arg1, arg2, arg3, arg4] if (part or "").strip()]
        extra = " ".join(extra_args).strip()
        if not action:
            yield event.plain_result(
                "明日方舟基础查询\n"
                "/arknights 便签\n"
                "/arknights 理智\n"
                "/arknights 剿灭\n"
                "/arknights 日常\n"
                "/arknights 周常\n"
                "/arknights 公告\n"
                "/arknights 公告 1\n"
                "/arknights 刷图推荐\n"
                "/arknights 公招查询 支援 远程位\n"
                "/arknights 肉鸽\n"
                "/arknights 抽卡记录\n"
                "/arknights 抽卡分析"
            )
            return

        if action in {"公告", "公告列表"} and not extra:
            try:
                announcements = await self.ark_service.get_announcements()
                image_path = await self.renderer.render_html(
                    "arknights/announcement.html",
                    {
                        "items": [
                            {
                                "title": item.get("title") or item.get("webTitle") or "未命名公告",
                                "date": datetime.fromtimestamp(int(item.get("displayTime", 0))).strftime("%Y-%m-%d")
                                if item.get("displayTime")
                                else "-",
                                "url": item.get("webUrl") or item.get("announceUrl") or "无链接",
                            }
                            for item in announcements[:10]
                        ]
                    },
                )
                if image_path:
                    yield event.image_result(image_path)
                    return
                lines = ["明日方舟公告列表"]
                for idx, item in enumerate(announcements[:10], start=1):
                    title = item.get("title") or item.get("webTitle") or "未命名公告"
                    date_text = (
                        datetime.fromtimestamp(int(item.get("displayTime", 0))).strftime("%Y-%m-%d")
                        if item.get("displayTime")
                        else "-"
                    )
                    lines.append(f"{idx}. [{date_text}] {title}")
                lines.append("使用 /arknights 公告 1 查看详情链接。")
                yield event.plain_result("\n".join(lines))
            except Exception as exc:
                yield event.plain_result(f"获取公告失败：{exc}")
            return

        match = re.match(r"^公告(\d+)$", action)
        if match or (action == "公告" and extra.isdigit()):
            try:
                index = int(match.group(1) if match else extra)
                announcements = await self.ark_service.get_announcements()
                if index <= 0 or index > len(announcements[:10]):
                    yield event.plain_result("公告序号超出范围。")
                    return
                item = announcements[index - 1]
                detail = await self.ark_service.get_announcement_detail(item)
                date_text = (
                    datetime.fromtimestamp(int(detail.get("displayTime", 0))).strftime("%Y-%m-%d %H:%M")
                    if detail.get("displayTime")
                    else "-"
                )
                image_path = await self.renderer.render_html(
                    "arknights/announcement-detail.html",
                    {
                        "title": detail.get("title") or item.get("title") or item.get("webTitle") or "未命名公告",
                        "author": detail.get("author") or item.get("author") or "明日方舟运营组",
                        "date": date_text,
                        "brief": detail.get("brief") or item.get("brief") or "",
                        "url": detail.get("url") or item.get("webUrl") or item.get("announceUrl") or "无链接",
                        "content_html": detail.get("content_html") or "",
                    },
                )
                if image_path:
                    yield event.image_result(image_path)
                    return
                yield event.plain_result(
                    "\n".join(
                        [
                            detail.get("title") or item.get("title") or item.get("webTitle") or "未命名公告",
                            f"日期：{date_text}",
                            f"作者：{detail.get('author') or item.get('author') or '明日方舟运营组'}",
                            detail.get("brief") or item.get("brief") or "",
                            detail.get("url") or item.get("webUrl") or item.get("announceUrl") or "无链接",
                        ]
                    )
                )
            except Exception as exc:
                yield event.plain_result(f"获取公告详情失败：{exc}")
            return

        if action in {"刷图推荐", "材料掉率", "一图流"}:
            try:
                site_image = await self.renderer.screenshot_url(
                    "https://ark.yituliu.cn/",
                    viewport_width=1500,
                    viewport_height=2400,
                    full_page=False,
                    selector="#stageForCards",
                )
                if site_image:
                    yield event.image_result(site_image)
                    return
                data = await self.material_service.get_data()
                items = data.get("recommendedStageList") or []
                update_time = data.get("updateTime", "")
                render_items = []
                for item in items:
                    stages = sorted(
                        item.get("stageResultList") or [],
                        key=lambda stage: (
                            float(stage.get("stageEfficiency", 0)),
                            float(stage.get("sampleConfidence", 0)),
                        ),
                        reverse=True,
                    )[:3]
                    render_items.append(
                        {
                            "itemType": item.get("itemType", "未知材料"),
                            "icon": self.material_service.get_icon_path(item.get("itemType", "")),
                            "stageResultList": stages,
                        }
                    )
                image_path = await self.renderer.render_html(
                    "arknights/material.html",
                    {"items": render_items, "update_time": update_time},
                )
                if image_path:
                    yield event.image_result(image_path)
                    return
                lines = [f"一图流材料掉率表（更新时间：{update_time}）"]
                for item in render_items:
                    stages = item["stageResultList"]
                    stage_text = " / ".join(
                        f"{stage.get('code', '?')} 效率{float(stage.get('stageEfficiency', 0)):.3f}"
                        for stage in stages
                    )
                    lines.append(f"- {item.get('itemType', '未知材料')}: {stage_text}")
                yield event.plain_result("\n".join(lines))
            except Exception as exc:
                yield event.plain_result(f"获取材料掉率失败：{exc}")
            return

        if action in {"公招查询", "公招"}:
            tags = [part for part in extra_args if part]
            if not tags:
                yield event.plain_result("请输入公招标签，例如：/arknights 公招查询 支援 远程位")
                return
            try:
                result = await self.recruit_service.calculate(tags)
                lines = [f"公招查询：{' '.join(tags)}"]
                any_hit = False
                groups = []
                mark_map: dict[str, str] = {}
                class_map: dict[str, str] = {}
                account = await self.storage.get_primary_account(str(event.get_sender_id()))
                if account and account.get("token"):
                    try:
                        player = await self.api.get_arknights_player_info(account["token"])
                        mark_map, class_map = self._build_recruit_marks(player.get("data", {}) or {})
                    except Exception:
                        mark_map, class_map = {}, {}
                for star in ["6", "5", "4", "1"]:
                    star_data = result.get(star) or {}
                    if not star_data:
                        continue
                    any_hit = True
                    groups.append(
                        {
                            "star_label": f"{star} 星结果",
                            "combos": [
                                {
                                    "combo": combo,
                                    "ops": [
                                        {
                                            "name": name,
                                            "mark": mark_map.get(name, ""),
                                            "mark_class": class_map.get(name, "owned"),
                                        }
                                        for name in names[:10]
                                    ],
                                }
                                for combo, names in list(star_data.items())[:8]
                            ],
                        }
                    )
                    lines.append(f"{star}星结果：")
                    for combo, names in list(star_data.items())[:5]:
                        rendered_names = []
                        for name in names[:8]:
                            mark = mark_map.get(name)
                            rendered_names.append(f"{name}[{mark}]" if mark else name)
                        lines.append(f"- {combo}: {', '.join(rendered_names)}")
                if groups:
                    image_path = await self.renderer.render_html(
                        "arknights/recruit.html",
                        {"tags": tags, "groups": groups},
                    )
                    if image_path:
                        yield event.image_result(image_path)
                        return
                if not any_hit:
                    lines.append("当前 tag 组合没有稳定的高星结果。")
                yield event.plain_result("\n".join(lines))
            except Exception as exc:
                yield event.plain_result(f"公招查询失败：{exc}")
            return

        account = await self.storage.get_primary_account(str(event.get_sender_id()))
        if not account or not account.get("token"):
            yield event.plain_result("该功能需要先绑定森空岛账号，请使用 /skdlogin 或 /skdscan。")
            return

        try:
            player = await self.api.get_arknights_player_info(account["token"])
            player_data = player.get("data", {})
        except Exception as exc:
            yield event.plain_result(f"获取游戏信息失败：{exc}")
            return

        if action in {"便签", "博士卡片", "卡片"}:
            status = player_data.get("status", {})
            ap = status.get("ap", {})
            current_ap = min(
                ap.get("max", 0),
                ap.get("max", 0) - max(0, int((ap.get("completeRecoveryTime", 0) - datetime.now().timestamp()) / 360)),
            )
            routine = player_data.get("routine", {})
            campaign = player_data.get("campaign", {})
            try:
                cards = await self.api.get_game_cards(account["token"])
                card_data = ((cards.get("data", {}) or {}).get("list", [{}])[0] or {}).get("arknights", {})
            except Exception:
                card_data = {}
            lines = [
                f"博士：{status.get('name', account.get('nickname', '未知'))}",
                f"UID：{status.get('uid', '未知')}",
                f"等级：{status.get('level', '未知')}",
                f"理智：{current_ap}/{ap.get('max', 0)}",
                f"日常：{routine.get('daily', {}).get('current', 0)}/{routine.get('daily', {}).get('total', 0)}",
                f"周常：{routine.get('weekly', {}).get('current', 0)}/{routine.get('weekly', {}).get('total', 0)}",
                f"剿灭：{campaign.get('reward', {}).get('current', 0)}/{campaign.get('reward', {}).get('total', 0)}",
            ]
            if card_data:
                lines.extend(
                    [
                        f"干员数：{card_data.get('charCnt', 'N/A')}",
                        f"时装数：{card_data.get('skinCnt', 'N/A')}",
                        f"家具数：{card_data.get('furnitureCnt', 'N/A')}",
                    ]
                )
            register_ts = status.get("registerTs", 0)
            register_date = datetime.fromtimestamp(register_ts).strftime("%Y-%m-%d") if register_ts else "-"
            clue_board = player_data.get("building", {}).get("meeting", {}).get("clue", {}).get("board", []) or []
            clue_keys = [
                ("RHINE", "①"),
                ("PENGUIN", "②"),
                ("BLACKSTEEL", "③"),
                ("URSUS", "④"),
                ("GLASGOW", "⑤"),
                ("KJERAG", "⑥"),
                ("RHODES", "⑦"),
            ]
            clues = [{"label": label, "active": key in clue_board} for key, label in clue_keys]
            recruit_items = []
            for idx, recruit in enumerate(player_data.get("recruit", []) or [], start=1):
                state = recruit.get("state", 0)
                done = False
                finish_ts = recruit.get("finishTs", 0)
                if state == 2 and finish_ts and finish_ts < int(datetime.now().timestamp() * 1000):
                    done = True
                label = f"公招{idx}: " + ("已完成" if done else ("进行中" if state else "空闲"))
                recruit_items.append({"label": label, "done": done})
            if not recruit_items:
                recruit_items = [{"label": "暂无公招槽位数据", "done": False}]
            note_stats = [
                {
                    "label": "理智",
                    "value": f"{current_ap}/{ap.get('max', 0)}",
                    "sub": f"回满时间 {datetime.fromtimestamp(ap.get('completeRecoveryTime', 0)).strftime('%m-%d %H:%M') if ap.get('completeRecoveryTime') else '-'}",
                },
                {
                    "label": "日常 / 周常",
                    "value": f"{routine.get('daily', {}).get('current', 0)}/{routine.get('daily', {}).get('total', 0)}",
                    "sub": f"周常 {routine.get('weekly', {}).get('current', 0)}/{routine.get('weekly', {}).get('total', 0)}",
                },
                {
                    "label": "剿灭",
                    "value": f"{campaign.get('reward', {}).get('current', 0)}/{campaign.get('reward', {}).get('total', 0)}",
                    "sub": "本周合成玉进度",
                },
                {
                    "label": "无人机",
                    "value": f"{player_data.get('building', {}).get('labor', {}).get('value', 0)}/{player_data.get('building', {}).get('labor', {}).get('maxValue', 0)}",
                    "sub": "基建加速库存",
                },
                {
                    "label": "干员 / 时装 / 家具",
                    "value": f"{card_data.get('charCnt', 'N/A')} / {card_data.get('skinCnt', 'N/A')} / {card_data.get('furnitureCnt', 'N/A')}",
                    "sub": "收藏统计",
                },
                {
                    "label": "公招",
                    "value": f"{len([item for item in player_data.get('recruit', []) if item.get('state') != 0])}",
                    "sub": "当前槽位中可用公招数",
                },
            ]
            image_path = await self.renderer.render_html(
                "arknights/note.html",
                {
                    "doctor": {
                        "name": status.get("name", account.get("nickname", "未知博士")),
                        "uid": status.get("uid", "未知"),
                        "level": status.get("level", "未知"),
                        "register_date": register_date,
                        "progress": status.get("mainStageProgress") or "全部完成",
                        "avatar_url": self._get_avatar_url(status),
                    },
                    "stats": note_stats,
                    "clues": clues,
                    "recruit": recruit_items[:5],
                },
            )
            if image_path:
                yield event.image_result(image_path)
                return
            yield event.plain_result("\n".join(lines))
            return

        if action == "理智":
            ap = player_data.get("status", {}).get("ap", {})
            current_ap = min(
                ap.get("max", 0),
                ap.get("max", 0) - max(0, int((ap.get("completeRecoveryTime", 0) - datetime.now().timestamp()) / 360)),
            )
            recovery_time = ap.get("completeRecoveryTime", 0)
            recovery_text = datetime.fromtimestamp(recovery_time).strftime("%Y-%m-%d %H:%M") if recovery_time else "-"
            yield event.plain_result(f"理智：{current_ap}/{ap.get('max', 0)}\n预计回满时间：{recovery_text}")
            return

        if action == "剿灭":
            campaign = player_data.get("campaign", {})
            reward = campaign.get("reward", {})
            yield event.plain_result(f"本周剿灭合成玉：{reward.get('current', 0)}/{reward.get('total', 0)}")
            return

        if action in {"日常", "周常"}:
            routine = player_data.get("routine", {})
            if action == "周常":
                yield event.plain_result(
                    f"周常完成情况：{routine.get('weekly', {}).get('current', 0)}/{routine.get('weekly', {}).get('total', 0)}"
                )
            else:
                yield event.plain_result(
                    "日常/周常完成情况：\n"
                    f"每日任务：{routine.get('daily', {}).get('current', 0)}/{routine.get('daily', {}).get('total', 0)}\n"
                    f"每周任务：{routine.get('weekly', {}).get('current', 0)}/{routine.get('weekly', {}).get('total', 0)}"
                )
            return

        if action in {"肉鸽", "集成战略"}:
            rogue = player_data.get("rogue", {})
            rogue_info_map = player_data.get("rogueInfoMap", {})
            records = rogue.get("records") or []
            if not records:
                yield event.plain_result("暂无肉鸽战绩数据。")
                return
            lines = [f"集成战略战绩：{player_data.get('status', {}).get('name', '未知博士')}"]
            ordered = sorted(
                records,
                key=lambda record: (rogue_info_map.get(record.get("rogueId"), {}) or {}).get("sort", 999),
            )
            rogue_list = []
            for record in ordered:
                info = rogue_info_map.get(record.get("rogueId"), {}) or {}
                name = info.get("name", record.get("rogueId", "未知主题"))
                rogue_list.append(
                    {
                        "name": name,
                        "image": info.get("picUrl", ""),
                        "bankCurrent": (record.get("bank", {}) or {}).get("current", 0),
                        "bankRecord": (record.get("bank", {}) or {}).get("record", 0),
                        "relicCnt": record.get("relicCnt", 0),
                        "clearTime": record.get("clearTime", 0),
                        "bpLevel": record.get("bpLevel", 0),
                        "medalCurrent": (record.get("medal", {}) or {}).get("current", 0),
                        "medalTotal": (record.get("medal", {}) or {}).get("total", 0),
                    }
                )
                lines.append(
                    f"- {name}: 奖励等级 {record.get('bpLevel', 0)} / 解锁藏品 {record.get('relicCnt', 0)} / 通关 {record.get('clearTime', 0)}"
                )
            image_path = await self.renderer.render_html(
                "arknights/rogue.html",
                {
                    "user_name": player_data.get("status", {}).get("name", "未知博士"),
                    "uid": player_data.get("status", {}).get("uid", "未知"),
                    "rogue_list": rogue_list,
                },
            )
            if image_path:
                yield event.image_result(image_path)
                return
            yield event.plain_result("\n".join(lines))
            return

        if action in {"抽卡记录", "寻访记录"}:
            try:
                binding = await self.api.get_arknights_binding(account["token"])
                if not binding:
                    yield event.plain_result("未找到明日方舟绑定信息。")
                    return
                pool_name = extra
                records = await self.gacha_service.get_all_records(
                    binding.uid,
                    account["token"],
                    pool_name=pool_name,
                )
                if not records:
                    if pool_name:
                        yield event.plain_result(f"未找到包含“{pool_name}”的抽卡记录。")
                    else:
                        yield event.plain_result("暂未获取到抽卡记录。")
                    return
                title = "抽卡记录" if not pool_name else f"{pool_name} 抽卡记录"
                status = player_data.get("status", {}) or {}
                render_data = await self.gacha_service.build_record_view(
                    records=records,
                    user_name=status.get("name", account.get("nickname", "未知博士")),
                    user_uid=str(status.get("uid", binding.uid)),
                    user_level=status.get("level", 0),
                    user_avatar=self._get_avatar_url(status),
                    server_label=binding.channel_name or "官服",
                    title=title,
                )
                lines = [f"{title}：共 {len(records)} 抽"]
                for section in render_data.get("sections", [])[:3]:
                    lines.append(
                        f"- {section['pool_name']}: {section['pool_total']} 抽 / 当前已垫 {section['current_pity']} 抽"
                    )
                image_path = await self.renderer.render_html(
                    "arknights/gacha.html",
                    render_data,
                )
                if image_path:
                    yield event.image_result(image_path)
                    return
                yield event.plain_result("\n".join(lines))
            except Exception as exc:
                yield event.plain_result(f"获取抽卡记录失败：{exc}")
            return

        if action in {"抽卡分析", "寻访分析", "抽卡统计", "寻访统计"}:
            try:
                binding = await self.api.get_arknights_binding(account["token"])
                if not binding:
                    yield event.plain_result("未找到明日方舟绑定信息。")
                    return
                records = await self.gacha_service.get_all_records(binding.uid, account["token"])
                if not records:
                    yield event.plain_result("暂未获取到抽卡记录，无法分析。")
                    return
                status = player_data.get("status", {}) or {}
                render_data = await self.gacha_service.analyze_records(
                    records=records,
                    user_name=status.get("name", account.get("nickname", "未知博士")),
                    user_uid=str(status.get("uid", binding.uid)),
                    user_level=status.get("level", 0),
                    user_avatar=self._get_avatar_url(status),
                    server_label=binding.channel_name or "官服",
                )
                analysis = render_data["analysis"]
                image_path = await self.renderer.render_html("arknights/gacha-analysis.html", render_data)
                if image_path:
                    yield event.image_result(image_path)
                    return
                yield event.plain_result(
                    "抽卡分析：\n"
                    f"总抽数：{analysis['total_pulls']}\n"
                    f"平均六星抽数：{analysis['avg_six_star_pulls']}\n"
                    f"UP 六星：{analysis['up_six_star']}/{analysis['total_six_star']}\n"
                    f"评价：{analysis['evaluation']}"
                )
            except Exception as exc:
                yield event.plain_result(f"获取抽卡分析失败：{exc}")
            return

        yield event.plain_result("暂不支持该子命令。可用项：便签、理智、剿灭、日常、周常、公告、刷图推荐、材料掉率、公招查询、肉鸽、抽卡记录、抽卡分析。")
