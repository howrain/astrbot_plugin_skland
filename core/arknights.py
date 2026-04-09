from __future__ import annotations

from datetime import datetime
import html
import re

import httpx


OFFICIAL_NEWS_URL = "https://ak.hypergryph.com/news"


class ArknightsService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=25.0)
        self._announce_cache: tuple[datetime, list[dict]] | None = None

    async def close(self):
        await self.client.aclose()

    async def get_announcements(self) -> list[dict]:
        now = datetime.now()
        if self._announce_cache and (now - self._announce_cache[0]).seconds < 900:
            return self._announce_cache[1]

        resp = await self.client.get(
            OFFICIAL_NEWS_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot/1.0)"},
        )
        resp.raise_for_status()
        announce_list = self._parse_official_news(resp.text)
        self._announce_cache = (now, announce_list)
        return announce_list

    async def get_announcement_detail(self, announcement: dict) -> dict:
        url = announcement.get("webUrl") or announcement.get("announceUrl")
        if not url:
            raise ValueError("公告链接不存在")

        resp = await self.client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot/1.0)"},
        )
        resp.raise_for_status()
        return self._parse_announcement_detail(resp.text, announcement)

    def _parse_official_news(self, html: str) -> list[dict]:
        # 官网新闻页没有稳定公开的 JSON 接口，这里直接解析 Next.js 注水数据。
        start_marker = 'initialData\\":{\\"LATEST\\":{\\"list\\":['
        end_marker = ']}},\\"ACTIVITY\\":'
        start = html.find(start_marker)
        end = html.find(end_marker, start)
        if start == -1 or end == -1:
            return []
        raw_list = html[start + len(start_marker) : end]
        pattern = re.compile(
            r'\{\\"cid\\":\\"(?P<cid>[^"\\]+)\\",\\"tab\\":\\"(?P<tab>[^"\\]+)\\",'
            r'\\"sticky\\":(?P<sticky>true|false),\\"title\\":\\"(?P<title>.*?)\\",'
            r'\\"author\\":\\"(?P<author>.*?)\\",\\"displayTime\\":(?P<ts>\d+),'
            r'\\"cover\\":\\"(?P<cover>.*?)\\",\\"extraCover\\":\\"(?P<extra>.*?)\\",'
            r'\\"brief\\":\\"(?P<brief>.*?)\\"\}',
            re.DOTALL,
        )

        results: list[dict] = []
        seen: set[str] = set()
        for match in pattern.finditer(raw_list):
            cid = match.group("cid")
            ts = int(match.group("ts"))
            key = f"{cid}:{ts}"
            if key in seen:
                continue
            seen.add(key)
            tab = match.group("tab")
            title = self._decode_field(match.group("title"))
            brief = self._decode_field(match.group("brief"))
            author = self._decode_field(match.group("author"))
            results.append(
                {
                    "announceId": cid,
                    "cid": cid,
                    "title": title,
                    "webTitle": title,
                    "group": self._map_tab(tab),
                    "tab": tab,
                    "sticky": match.group("sticky") == "true",
                    "author": author,
                    "brief": brief,
                    "displayTime": ts,
                    "webUrl": f"{OFFICIAL_NEWS_URL}/{cid}",
                    "announceUrl": f"{OFFICIAL_NEWS_URL}/{cid}",
                }
            )

        results.sort(key=lambda item: (int(item.get("displayTime", 0)), int(item.get("cid", "0"))), reverse=True)
        return results

    def _parse_announcement_detail(self, page_html: str, fallback: dict) -> dict:
        scripts = list(
            re.finditer(r'<script>self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page_html, re.DOTALL)
        )
        article_script_index = -1
        article_match = None
        article_pattern = re.compile(
            r'articleData":\{"cid":"(?P<cid>[^"]+)","tab":"(?P<tab>[^"]+)",'
            r'"sticky":(?P<sticky>true|false),"title":"(?P<title>.*?)","author":"(?P<author>.*?)",'
            r'"displayTime":(?P<ts>\d+),"cover":"(?P<cover>.*?)","extraCover":"(?P<extra>.*?)",'
            r'"brief":"(?P<brief>.*?)","data":"(?P<data>\$?\d+)"\}',
            re.DOTALL,
        )

        for idx, script in enumerate(scripts):
            decoded = self._decode_script_block(script.group(1))
            match = article_pattern.search(decoded)
            if match:
                article_script_index = idx
                article_match = match
                break

        detail = {
            "cid": fallback.get("cid") or fallback.get("announceId", ""),
            "title": fallback.get("title") or fallback.get("webTitle") or "未命名公告",
            "author": fallback.get("author") or "明日方舟运营组",
            "brief": fallback.get("brief") or "",
            "displayTime": int(fallback.get("displayTime", 0) or 0),
            "url": fallback.get("webUrl") or fallback.get("announceUrl") or "",
            "content_html": "",
        }

        if article_match:
            detail.update(
                {
                    "cid": article_match.group("cid"),
                    "title": self._decode_field(article_match.group("title")),
                    "author": self._decode_field(article_match.group("author")),
                    "brief": self._decode_field(article_match.group("brief")),
                    "displayTime": int(article_match.group("ts")),
                }
            )

        if article_script_index > 0:
            # 正文 HTML 会出现在 articleData 前一个 flight script 片段里。
            body_html = self._decode_script_block(scripts[article_script_index - 1].group(1)).strip()
            if "<" in body_html and ">" in body_html:
                detail["content_html"] = body_html

        return detail

    def _decode_field(self, value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").strip()

    def _decode_script_block(self, value: str) -> str:
        decoded = html.unescape(value.encode("utf-8").decode("unicode_escape"))
        try:
            return decoded.encode("latin1").decode("utf-8")
        except UnicodeError:
            return decoded

    def _map_tab(self, tab: str) -> str:
        return {
            "0": "SYSTEM",
            "1": "ACTIVITY",
            "2": "NEWS",
        }.get(tab, "OFFICIAL")
