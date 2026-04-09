from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from typing import Any

import jinja2
from astrbot.api import logger


class Renderer:
    def __init__(self, res_path: str, render_timeout: int = 30000, cache_ttl_seconds: int = 3600):
        self.res_path = res_path
        self.render_timeout = render_timeout
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self._browser = None
        self._playwright = None
        self._lock = asyncio.Lock()
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.res_path),
            autoescape=True,
            keep_trailing_newline=True,
        )
        self._output_dir = os.path.join(self.res_path, "render_cache")
        os.makedirs(self._output_dir, exist_ok=True)
        self._cleanup_old_cache()

    async def render_html(self, template_name: str, data: dict[str, Any]) -> str | None:
        self._cleanup_old_cache()
        try:
            template = self._env.get_template(template_name)
            html = template.render(**data)
            html = self._inline_css_links(html, template_name)
        except Exception as exc:
            logger.error(f"[Skland Render] 模板渲染失败: {exc}")
            return None
        return await self._screenshot(html, template_name)

    async def render_raw_html(self, html: str, name: str = "raw.html") -> str | None:
        self._cleanup_old_cache()
        return await self._screenshot(html, name)

    async def screenshot_url(
        self,
        url: str,
        viewport_width: int = 1080,
        viewport_height: int = 900,
        full_page: bool = True,
        selector: str | None = None,
    ) -> str | None:
        self._cleanup_old_cache()
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.warning(f"[Skland Render] Playwright 不可用，无法截图网页: {exc}")
            return None

        async with self._lock:
            try:
                if not self._playwright:
                    self._playwright = await async_playwright().start()
                if not self._browser:
                    self._browser = await self._playwright.chromium.launch()
            except Exception as exc:
                logger.warning(f"[Skland Render] 启动浏览器失败，无法截图网页: {exc}")
                return None

        output_path = os.path.join(self._output_dir, f"render_{uuid.uuid4().hex[:8]}.png")
        try:
            context = await self._browser.new_context(
                device_scale_factor=1.5,
                viewport={"width": viewport_width, "height": viewport_height},
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.render_timeout)
            await page.wait_for_timeout(800)
            if selector:
                target = page.locator(selector).first
                await target.wait_for(state="visible", timeout=self.render_timeout)
                await target.screenshot(path=output_path)
            else:
                await page.screenshot(path=output_path, full_page=full_page)
            await context.close()
            return output_path
        except Exception as exc:
            logger.error(f"[Skland Render] 网页截图失败: {exc}")
            return None

    def _inline_css_links(self, html: str, template_name: str) -> str:
        template_dir = os.path.dirname(template_name)

        def repl(match):
            href = match.group(1)
            css_path = os.path.join(self.res_path, template_dir, href)
            if not os.path.exists(css_path):
                return ""
            with open(css_path, "r", encoding="utf-8") as file:
                return f"<style>\n{file.read()}\n</style>"

        return re.sub(
            r'<link\s+rel="stylesheet"\s+href="([^"]+\.css)">',
            repl,
            html,
        )

    async def _screenshot(self, html: str, template_name: str) -> str | None:
        self._cleanup_old_cache()
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.warning(f"[Skland Render] Playwright 不可用，回退文本输出: {exc}")
            return None

        async with self._lock:
            try:
                if not self._playwright:
                    self._playwright = await async_playwright().start()
                if not self._browser:
                    self._browser = await self._playwright.chromium.launch()
            except Exception as exc:
                logger.warning(f"[Skland Render] 启动浏览器失败，回退文本输出: {exc}")
                return None

        output_path = os.path.join(self._output_dir, f"render_{uuid.uuid4().hex[:8]}.png")
        temp_html = os.path.join(self._output_dir, f"tmp_{uuid.uuid4().hex[:8]}.html")
        with open(temp_html, "w", encoding="utf-8") as file:
            file.write(html)

        try:
            context = await self._browser.new_context(
                device_scale_factor=2.0,
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()
            await page.goto(
                f"file:///{temp_html.replace(chr(92), '/')}",
                wait_until="networkidle",
                timeout=self.render_timeout,
            )
            await page.wait_for_timeout(250)
            body = await page.query_selector("body")
            box = await body.bounding_box() if body else None
            if box:
                await page.set_viewport_size(
                    {"width": max(900, int(box["width"]) + 2), "height": int(box["height"]) + 2}
                )
                await page.screenshot(path=output_path, clip=box)
            else:
                await page.screenshot(path=output_path, full_page=True)
            await context.close()
            return output_path
        except Exception as exc:
            logger.error(f"[Skland Render] 截图失败 ({template_name}): {exc}")
            return None
        finally:
            if os.path.exists(temp_html):
                os.remove(temp_html)

    def _cleanup_old_cache(self):
        now = time.time()
        for name in os.listdir(self._output_dir):
            if not (name.startswith("render_") or name.startswith("tmp_")):
                continue
            path = os.path.join(self._output_dir, name)
            try:
                if not os.path.isfile(path):
                    continue
                if now - os.path.getmtime(path) > self.cache_ttl_seconds:
                    os.remove(path)
            except Exception as exc:
                logger.warning(f"[Skland Render] 清理缓存失败 {path}: {exc}")

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
