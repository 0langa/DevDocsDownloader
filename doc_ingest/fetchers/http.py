from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import AppConfig
from ..models import FetchResult
from ..utils.filesystem import read_json, write_bytes, write_json
from ..utils.text import stable_hash
from ..utils.urls import normalize_url


class HttpFetcher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(
                self.config.crawl.request_timeout_seconds,
                connect=self.config.crawl.request_timeout_seconds,
                read=self.config.crawl.total_timeout_seconds,
            ),
            headers={"User-Agent": self.config.crawl.user_agent},
        )
        self._host_locks: dict[str, asyncio.Lock] = {}
        self.adaptive_controller = None

    def set_adaptive_controller(self, controller) -> None:
        self.adaptive_controller = controller

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str, cache_dir: Path) -> FetchResult:
        normalized = normalize_url(url)
        cache_key = stable_hash(normalized)
        cache_path = cache_dir / f"{cache_key}.bin"
        meta_path = cache_dir / f"{cache_key}.json"

        if cache_path.exists() and meta_path.exists():
            meta = read_json(meta_path, {})
            return FetchResult(
                url=normalized,
                final_url=meta["final_url"],
                content_type=meta["content_type"],
                status_code=meta["status_code"],
                method="cache",
                content=cache_path.read_bytes(),
                history_status_codes=list(meta.get("history_status_codes", [])),
            )

        host = httpx.URL(normalized).host or "default"
        lock = self._host_locks.setdefault(host, asyncio.Lock())

        async with lock:
            delay_seconds = self.config.crawl.per_host_delay_seconds
            if self.adaptive_controller is not None:
                delay_seconds = await self.adaptive_controller.get_per_host_delay()
            await asyncio.sleep(delay_seconds)
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.config.crawl.retries),
                wait=wait_exponential(multiplier=self.config.crawl.backoff_base_seconds, min=1, max=12),
                retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.get(normalized)
                    result = FetchResult(
                        url=normalized,
                        final_url=str(response.url),
                        content_type=response.headers.get("content-type", "application/octet-stream"),
                        status_code=response.status_code,
                        method="http",
                        content=response.content,
                        history_status_codes=[item.status_code for item in response.history],
                    )
                    if response.is_success:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        write_bytes(cache_path, response.content)
                        write_json(
                            meta_path,
                            {
                                "final_url": result.final_url,
                                "content_type": result.content_type,
                                "status_code": result.status_code,
                                "history_status_codes": result.history_status_codes,
                            },
                        )
                    return result