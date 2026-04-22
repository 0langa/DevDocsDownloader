from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from ..config import AppConfig
from ..models import FetchResult
from ..utils.filesystem import read_json, write_bytes, write_json
from ..utils.text import stable_hash
from ..utils.urls import normalize_url

_MAX_HOST_ENTRIES = 2000


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
        self._host_state_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._host_next_allowed_at: OrderedDict[str, float] = OrderedDict()
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
<<<<<<< HEAD
            meta, cached_payload = await asyncio.gather(
                asyncio.to_thread(read_json, meta_path, {}),
                asyncio.to_thread(cache_path.read_bytes),
            )
            return FetchResult(
                url=normalized,
                final_url=meta["final_url"],
                content_type=meta["content_type"],
                status_code=meta["status_code"],
                method="cache",
                content=cached_payload,
                history_status_codes=list(meta.get("history_status_codes", [])),
            )
=======
            try:
                meta = read_json(meta_path, {})
                if not isinstance(meta, dict):
                    raise ValueError("cache metadata is malformed")
                final_url = meta.get("final_url")
                content_type = meta.get("content_type")
                status_code = meta.get("status_code")
                if final_url is None or content_type is None or status_code is None:
                    raise ValueError("cache metadata missing required fields")
                return FetchResult(
                    url=normalized,
                    final_url=final_url,
                    content_type=content_type,
                    status_code=int(status_code),
                    method="cache",
                    content=cache_path.read_bytes(),
                    history_status_codes=list(meta.get("history_status_codes", [])),
                )
            except Exception:
                pass
>>>>>>> 687d0a1722f69b8c8aa65dc9d95d1bf8f080b506

        host = httpx.URL(normalized).host or "default"
        await self._wait_for_host_slot(host)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.config.crawl.retries),
            wait=wait_exponential_jitter(initial=self.config.crawl.backoff_base_seconds, max=12, jitter=2),
            retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
            reraise=True,
        ):
            with attempt:
                response = await self._client.get(normalized)
                if response.status_code in {429, 503}:
                    retry_after = self._retry_after_seconds(response)
                    if retry_after > 0:
                        await asyncio.sleep(retry_after)
                    raise httpx.HTTPError(f"Retryable status code: {response.status_code}", request=response.request)
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
                    await asyncio.gather(
                        asyncio.to_thread(write_bytes, cache_path, response.content),
                        asyncio.to_thread(
                            write_json,
                            meta_path,
                            {
                                "final_url": result.final_url,
                                "content_type": result.content_type,
                                "status_code": result.status_code,
                                "history_status_codes": result.history_status_codes,
                            },
                        ),
                    )
                return result

    async def _wait_for_host_slot(self, host: str) -> None:
        delay_seconds = self.config.crawl.per_host_delay_seconds
        if self.adaptive_controller is not None:
            delay_seconds = await self.adaptive_controller.get_per_host_delay()

        if host not in self._host_state_locks:
            self._host_state_locks[host] = asyncio.Lock()
        else:
            self._host_state_locks.move_to_end(host)

        lock = self._host_state_locks[host]
        sleep_for = 0.0
        async with lock:
            now = time.monotonic()
            next_allowed = self._host_next_allowed_at.get(host, now)
            if next_allowed > now:
                sleep_for = next_allowed - now
                now = next_allowed
            self._host_next_allowed_at[host] = now + max(0.0, delay_seconds)
            self._host_next_allowed_at.move_to_end(host)

        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
<<<<<<< HEAD
=======

    def _retry_after_seconds(self, response: httpx.Response) -> float:
        value = response.headers.get("retry-after")
        if not value:
            return 0.0
        try:
            return max(0.0, float(int(value)))
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
                return max(0.0, dt.timestamp() - time.time())
            except Exception:
                return 0.0
>>>>>>> 687d0a1722f69b8c8aa65dc9d95d1bf8f080b506
