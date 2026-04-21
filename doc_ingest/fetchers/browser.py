from __future__ import annotations

import asyncio
from pathlib import Path

from ..errors import OptionalDependencyError
from ..config import AppConfig
from ..models import FetchResult
from ..utils.filesystem import write_bytes
from ..utils.text import stable_hash
from ..utils.urls import normalize_url


class BrowserFetcher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._playwright = None
        self._browser = None
        self._startup_lock = asyncio.Lock()
        self._page_semaphore = asyncio.Semaphore(max(1, min(4, self.config.crawl.max_concurrency)))

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _get_browser(self):
        if self._browser is not None:
            return self._browser
        async with self._startup_lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:  # pragma: no cover - exercised via tests
                raise OptionalDependencyError("playwright", "browser rendering", install_hint="pip install playwright && python -m playwright install chromium") from exc
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            return self._browser

    async def fetch(self, url: str, cache_dir: Path) -> FetchResult:
        normalized = normalize_url(url)
        browser = await self._get_browser()
        cache_key = stable_hash(f"browser:{normalized}")
        cache_path = cache_dir / f"{cache_key}.html"
        if cache_path.exists():
            content_bytes = await asyncio.to_thread(cache_path.read_bytes)
            return FetchResult(
                url=normalized,
                final_url=normalized,
                content_type="text/html; charset=utf-8",
                status_code=200,
                method="cache",
                content=content_bytes,
                history_status_codes=[],
            )

        async with self._page_semaphore:
            page = await browser.new_page(user_agent=self.config.crawl.user_agent)
            try:
                try:
                    await page.goto(normalized, wait_until="domcontentloaded", timeout=int(self.config.crawl.browser_timeout_seconds * 1000))
                except Exception:
                    await page.goto(normalized, wait_until="networkidle", timeout=int(self.config.crawl.browser_timeout_seconds * 1000))
                content = await page.content()
                final_url = page.url
            finally:
                await page.close()

        await asyncio.to_thread(write_bytes, cache_path, content.encode("utf-8"))
        return FetchResult(
            url=normalized,
            final_url=final_url,
            content_type="text/html; charset=utf-8",
            status_code=200,
            method="browser",
            content=content.encode("utf-8"),
            history_status_codes=[],
        )
