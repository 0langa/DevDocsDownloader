from __future__ import annotations

from pathlib import Path

from playwright.async_api import async_playwright

from ..config import AppConfig
from ..models import FetchResult
from ..utils.filesystem import write_bytes
from ..utils.text import stable_hash
from ..utils.urls import normalize_url


class BrowserFetcher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def fetch(self, url: str, cache_dir: Path) -> FetchResult:
        normalized = normalize_url(url)
        cache_key = stable_hash(f"browser:{normalized}")
        cache_path = cache_dir / f"{cache_key}.html"
        if cache_path.exists():
            return FetchResult(
                url=normalized,
                final_url=normalized,
                content_type="text/html; charset=utf-8",
                status_code=200,
                method="cache",
                content=cache_path.read_bytes(),
                history_status_codes=[],
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=self.config.crawl.user_agent)
            await page.goto(normalized, wait_until="networkidle", timeout=int(self.config.crawl.browser_timeout_seconds * 1000))
            content = await page.content()
            final_url = page.url
            await browser.close()

        cache_dir.mkdir(parents=True, exist_ok=True)
        write_bytes(cache_path, content.encode("utf-8"))
        return FetchResult(
            url=normalized,
            final_url=final_url,
            content_type="text/html; charset=utf-8",
            status_code=200,
            method="browser",
            content=content.encode("utf-8"),
            history_status_codes=[],
        )