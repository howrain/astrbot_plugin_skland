from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "docs" / "preview"
RESOURCE_DIR = ROOT / "resources"
# README 预览图统一使用固定身份，避免把真实账号昵称和 UID 带进仓库。
PREVIEW_PLAYER_NAME = "博士#114514"
PREVIEW_PLAYER_UID = "1145141919810"
sys.path.insert(0, str(ROOT.parent))


def install_astrbot_stub() -> None:
    logger = logging.getLogger("astrbot_stub")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    api_module.logger = logger
    astrbot_module.api = api_module
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules["astrbot.api"] = api_module


install_astrbot_stub()

from astrbot_plugin_skland.core.arknights import ArknightsService
from astrbot_plugin_skland.core.gacha import GachaService
from astrbot_plugin_skland.core.material import MaterialService
from astrbot_plugin_skland.core.recruit import RecruitService
from astrbot_plugin_skland.core.render import Renderer
from astrbot_plugin_skland.skland_api import SklandAPI


def get_avatar_url(status: dict) -> str:
    avatar = status.get("avatar", {}) or {}
    avatar_type = avatar.get("type")
    avatar_id = avatar.get("id")
    if not avatar_type or not avatar_id:
        return ""
    avatar_id = str(avatar_id).replace("@", "%40").replace("#", "%23")
    if avatar_type == "ICON":
        return f"https://web.hycdn.cn/arknights/game/assets/avatar/{avatar_id}.png"
    return f"https://web.hycdn.cn/arknights/game/assets/char_skin/avatar/{avatar_id}.png"


def build_recruit_marks(player_data: dict) -> tuple[dict[str, str], dict[str, str]]:
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


def copy_preview(src: str | None, target_name: str) -> str | None:
    if not src:
        return None
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    target = PREVIEW_DIR / target_name
    shutil.copyfile(src, target)
    return str(target.relative_to(ROOT)).replace("\\", "/")


async def main() -> None:
    token = os.environ.get("SKLAND_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先设置环境变量 SKLAND_TOKEN。")

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    api = SklandAPI(max_retries=3)
    ark_service = ArknightsService()
    gacha_service = GachaService()
    material_service = MaterialService()
    recruit_service = RecruitService()
    renderer = Renderer(str(RESOURCE_DIR))

    checks: list[dict] = []

    try:
        results, nickname = await api.do_full_sign_in(token)
        preview_name = PREVIEW_PLAYER_NAME
        preview_uid = PREVIEW_PLAYER_UID
        checks.append(
            {
                "name": "sign_in",
                "ok": True,
                "nickname": preview_name,
                "games": [result.game for result in results],
                "details": [
                    {
                        "game": result.game,
                        "success": result.success,
                        "error": result.error,
                        "awards": result.awards,
                    }
                    for result in results
                ],
            }
        )

        player = await api.get_arknights_player_info(token)
        player_data = player.get("data", {}) or {}
        status = player_data.get("status", {}) or {}
        cards = await api.get_game_cards(token)
        card_data = ((cards.get("data", {}) or {}).get("list", [{}])[0] or {}).get("arknights", {})
        checks.append(
            {
                "name": "player_info",
                "ok": True,
                "uid": preview_uid,
                "nickname": preview_name,
                "char_count": card_data.get("charCnt", 0),
            }
        )

        ap = status.get("ap", {})
        current_ap = min(
            ap.get("max", 0),
            ap.get("max", 0) - max(0, int((ap.get("completeRecoveryTime", 0) - datetime.now().timestamp()) / 360)),
        )
        routine = player_data.get("routine", {})
        campaign = player_data.get("campaign", {})
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
        note_path = await renderer.render_html(
            "arknights/note.html",
            {
                "doctor": {
                    "name": preview_name,
                    "uid": preview_uid,
                    "level": status.get("level", "未知"),
                    "register_date": register_date,
                    "progress": status.get("mainStageProgress") or "全部完成",
                    "avatar_url": get_avatar_url(status),
                },
                "stats": note_stats,
                "clues": clues,
                "recruit": recruit_items[:5],
            },
        )
        checks.append({"name": "render_note", "ok": bool(note_path), "path": copy_preview(note_path, "note.png")})

        announcements = await ark_service.get_announcements()
        announcement_cards = [
            {
                "index": idx,
                "title": item.get("title") or item.get("webTitle") or "未命名公告",
                "label": item.get("group", "官方公告"),
                "date": datetime.fromtimestamp(int(item.get("displayTime", 0))).strftime("%Y-%m-%d")
                if item.get("displayTime")
                else "-",
                "url": item.get("webUrl") or item.get("announceUrl") or "",
            }
            for idx, item in enumerate(announcements[:10], start=1)
        ]
        announcement_list_path = await renderer.render_html(
            "arknights/announcement.html",
            {"items": announcement_cards},
        )
        checks.append(
            {
                "name": "announcement_list",
                "ok": bool(announcement_list_path),
                "count": len(announcement_cards),
                "path": copy_preview(announcement_list_path, "announcement-list.png"),
            }
        )

        detail_ok = False
        detail_title = ""
        if announcements:
            first = announcements[0]
            detail_title = first.get("title") or first.get("webTitle") or "未命名公告"
            detail = await ark_service.get_announcement_detail(first)
            detail_path = await renderer.render_html(
                "arknights/announcement-detail.html",
                {
                    "title": detail.get("title") or detail_title,
                    "author": detail.get("author") or first.get("author") or "明日方舟运营组",
                    "date": datetime.fromtimestamp(int(detail.get("displayTime", 0))).strftime("%Y-%m-%d %H:%M")
                    if detail.get("displayTime")
                    else "-",
                    "brief": detail.get("brief") or first.get("brief") or "",
                    "url": detail.get("url") or first.get("webUrl") or first.get("announceUrl") or "",
                    "content_html": detail.get("content_html") or "",
                },
            )
            detail_ok = bool(detail_path)
            if detail_ok:
                copy_preview(detail_path, "announcement-1.png")
        checks.append({"name": "announcement_detail", "ok": detail_ok, "title": detail_title, "path": "docs/preview/announcement-1.png" if detail_ok else None})

        material_path = await renderer.screenshot_url(
            "https://ark.yituliu.cn/",
            viewport_width=1500,
            viewport_height=2400,
            full_page=False,
            selector="#stageForCards",
        )
        checks.append({"name": "material", "ok": bool(material_path), "items": 1, "path": copy_preview(material_path, "material.png")})

        material_data = await material_service.get_data()
        material_items = material_data.get("recommendedStageList") or []
        render_items = []
        for item in material_items:
            stages = sorted(
                item.get("stageResultList") or [],
                key=lambda stage: (float(stage.get("stageEfficiency", 0)), float(stage.get("sampleConfidence", 0))),
                reverse=True,
            )[:3]
            render_items.append(
                {
                    "itemType": item.get("itemType", "未知材料"),
                    "icon": material_service.get_icon_path(item.get("itemType", "")),
                    "stageResultList": stages,
                }
            )
        material_render_path = await renderer.render_html(
            "arknights/material.html",
            {"items": render_items, "update_time": material_data.get("updateTime", "")},
        )
        checks.append(
            {
                "name": "material_render",
                "ok": bool(material_render_path),
                "items": len(render_items),
                "path": copy_preview(material_render_path, "material-render.png"),
            }
        )

        recruit_result = await recruit_service.calculate(["支援", "远程位"])
        mark_map, class_map = build_recruit_marks(player_data)
        recruit_groups = []
        recruit_group_count = 0
        for star in ["6", "5", "4", "1"]:
            star_data = recruit_result.get(star) or {}
            if not star_data:
                continue
            recruit_group_count += 1
            recruit_groups.append(
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
        recruit_path = await renderer.render_html(
            "arknights/recruit.html",
            {"tags": ["支援", "远程位"], "groups": recruit_groups},
        )
        checks.append({"name": "recruit", "ok": bool(recruit_path), "groups": recruit_group_count, "path": copy_preview(recruit_path, "recruit.png")})

        rogue = player_data.get("rogue", {})
        rogue_info_map = player_data.get("rogueInfoMap", {})
        records = rogue.get("records") or []
        ordered = sorted(records, key=lambda record: (rogue_info_map.get(record.get("rogueId"), {}) or {}).get("sort", 999))
        rogue_list = [
            {
                "name": (rogue_info_map.get(record.get("rogueId"), {}) or {}).get("name", record.get("rogueId", "未知主题")),
                "image": (rogue_info_map.get(record.get("rogueId"), {}) or {}).get("picUrl", ""),
                "bankCurrent": (record.get("bank", {}) or {}).get("current", 0),
                "bankRecord": (record.get("bank", {}) or {}).get("record", 0),
                "relicCnt": record.get("relicCnt", 0),
                "clearTime": record.get("clearTime", 0),
                "bpLevel": record.get("bpLevel", 0),
                "medalCurrent": (record.get("medal", {}) or {}).get("current", 0),
                "medalTotal": (record.get("medal", {}) or {}).get("total", 0),
            }
            for record in ordered
        ]
        rogue_path = await renderer.render_html(
            "arknights/rogue.html",
            {
                "user_name": preview_name,
                "uid": preview_uid,
                "rogue_list": rogue_list,
            },
        )
        checks.append({"name": "rogue", "ok": bool(rogue_path), "records": len(rogue_list), "path": copy_preview(rogue_path, "rogue.png")})

        binding = await api.get_arknights_binding(token)
        if not binding:
            raise RuntimeError("未找到明日方舟绑定信息")
        gacha_records = await gacha_service.get_all_records(binding.uid, token)
        gacha_view = await gacha_service.build_record_view(
            records=gacha_records,
            user_name=preview_name,
            user_uid=preview_uid,
            user_level=status.get("level", "未知"),
            user_avatar=get_avatar_url(status),
            server_label=binding.channel_name or "官服",
            title="抽卡记录",
        )
        gacha_path = await renderer.render_html(
            "arknights/gacha.html",
            gacha_view,
        )
        checks.append({"name": "gacha", "ok": bool(gacha_path), "records": len(gacha_records), "path": copy_preview(gacha_path, "gacha.png")})

        pool_keyword = ""
        if gacha_records:
            pool_keyword = str(gacha_records[0].get("poolName", "")).split(" ")[0] or str(gacha_records[0].get("poolName", ""))
        if pool_keyword:
            pool_records = await gacha_service.get_all_records(binding.uid, token, pool_name=pool_keyword)
            pool_view = await gacha_service.build_record_view(
                records=pool_records,
                user_name=preview_name,
                user_uid=preview_uid,
                user_level=status.get("level", "未知"),
                user_avatar=get_avatar_url(status),
                server_label=binding.channel_name or "官服",
                title=f"{pool_keyword} 抽卡记录",
            )
            gacha_pool_path = await renderer.render_html(
                "arknights/gacha.html",
                pool_view,
            )
            checks.append(
                {
                    "name": "gacha_pool",
                    "ok": bool(gacha_pool_path),
                    "keyword": pool_keyword,
                    "records": len(pool_records),
                    "path": copy_preview(gacha_pool_path, "gacha-pool.png"),
                }
            )

        analysis_view = await gacha_service.analyze_records(
            records=gacha_records,
            user_name=preview_name,
            user_uid=preview_uid,
            user_level=status.get("level", "未知"),
            user_avatar=get_avatar_url(status),
            server_label=binding.channel_name or "官服",
        )
        gacha_analysis_path = await renderer.render_html("arknights/gacha-analysis.html", analysis_view)
        checks.append(
            {
                "name": "gacha_analysis",
                "ok": bool(gacha_analysis_path),
                "records": len(gacha_records),
                "path": copy_preview(gacha_analysis_path, "gacha-analysis.png"),
            }
        )

        report = {"generated_at": datetime.now().isoformat(), "checks": checks}
        report_path = PREVIEW_DIR / "test-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await renderer.close()
        await recruit_service.close()
        await material_service.close()
        await gacha_service.close()
        await ark_service.close()
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
