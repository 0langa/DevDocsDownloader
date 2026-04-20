from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import psutil

from .config import AppConfig


@dataclass
class AdaptiveSnapshot:
    cpu_percent: float
    memory_percent: float
    disk_percent: float


class AdaptiveRuntimeController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.enabled = bool(config.crawl.smart_mode)
        self._lock = asyncio.Lock()
        self.page_concurrency = max(1, config.crawl.max_concurrency)
        self.language_concurrency = max(1, config.crawl.language_concurrency)
        self.per_host_delay_seconds = max(0.0, config.crawl.per_host_delay_seconds)
        self.max_pages_per_language = max(1, config.crawl.max_pages_per_language)
        self.max_discovered_urls_per_language = max(1, config.crawl.max_discovered_urls_per_language)

    async def tune(self, *, queue_fill_ratio: float = 0.0, limit_hit: bool = False) -> None:
        if not self.enabled:
            return
        snapshot = self._snapshot()
        async with self._lock:
            pressure_high = snapshot.cpu_percent >= 88 or snapshot.memory_percent >= 88 or snapshot.disk_percent >= 95
            pressure_low = snapshot.cpu_percent <= 65 and snapshot.memory_percent <= 70 and snapshot.disk_percent <= 85

            if pressure_high:
                self.page_concurrency = max(self.config.crawl.smart_min_page_concurrency, self.page_concurrency - 1)
                self.language_concurrency = max(self.config.crawl.smart_min_language_concurrency, self.language_concurrency - 1)
                self.per_host_delay_seconds = min(self.config.crawl.smart_max_per_host_delay_seconds, self.per_host_delay_seconds * 1.2 + 0.01)
            elif pressure_low and (limit_hit or queue_fill_ratio > 0.6):
                self.page_concurrency = min(self.config.crawl.smart_max_page_concurrency, self.page_concurrency + 1)
                self.language_concurrency = min(self.config.crawl.smart_max_language_concurrency, self.language_concurrency + 1)
                self.per_host_delay_seconds = max(self.config.crawl.smart_min_per_host_delay_seconds, self.per_host_delay_seconds * 0.9)
                self.max_pages_per_language = min(self.config.crawl.smart_max_pages_per_language, max(self.max_pages_per_language + 250, int(self.max_pages_per_language * 1.1)))
                self.max_discovered_urls_per_language = min(self.config.crawl.smart_max_discovered_urls_per_language, max(self.max_discovered_urls_per_language + 500, int(self.max_discovered_urls_per_language * 1.1)))

    async def get_page_concurrency(self) -> int:
        async with self._lock:
            return self.page_concurrency

    async def get_language_concurrency(self) -> int:
        async with self._lock:
            return self.language_concurrency

    async def get_per_host_delay(self) -> float:
        async with self._lock:
            return self.per_host_delay_seconds

    async def get_max_pages(self) -> int:
        async with self._lock:
            return self.max_pages_per_language

    async def get_max_discovered(self) -> int:
        async with self._lock:
            return self.max_discovered_urls_per_language

    def _snapshot(self) -> AdaptiveSnapshot:
        disk = psutil.disk_usage(str(self.config.paths.root if Path(self.config.paths.root).exists() else Path.cwd()))
        return AdaptiveSnapshot(
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=psutil.virtual_memory().percent,
            disk_percent=disk.percent,
        )