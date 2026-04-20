from __future__ import annotations

import logging
import urllib.robotparser
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from .adapters import SiteAdapter, compile_ignored_patterns
from .config import AppConfig
from .models import PlannedSource, UrlRecord
from .utils.urls import is_probably_document_url, normalize_url, same_domain


LOGGER = logging.getLogger("doc_ingest.discovery")


class RobotsCache:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        if not self.config.crawl.respect_robots_txt:
            return True
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._cache:
            robots_url = f"{root}/robots.txt"
            try:
                async with httpx.AsyncClient(timeout=self.config.crawl.request_timeout_seconds, headers={"User-Agent": self.config.crawl.user_agent}) as client:
                    response = await client.get(robots_url)
                parser = urllib.robotparser.RobotFileParser()
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                    self._cache[root] = parser
                else:
                    self._cache[root] = None
            except Exception:
                self._cache[root] = None
        parser = self._cache[root]
        return True if parser is None else bool(parser.can_fetch(self.config.crawl.user_agent, url))


class DiscoveryHelper:
    def __init__(self, config: AppConfig, adapter: SiteAdapter, plan: PlannedSource) -> None:
        self.config = config
        self.adapter = adapter
        self.plan = plan
        self.ignore_patterns = compile_ignored_patterns(config, plan)

    def should_visit(self, url: str) -> bool:
        normalized = normalize_url(
            url,
            drop_query_params=self.config.crawl.drop_query_params,
            keep_query_params=self.config.crawl.keep_query_params,
        )
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not same_domain(normalized, self.plan.allowed_domains):
            return False
        if self.plan.allowed_path_prefixes and not any(
            parsed.path == prefix.rstrip("/") or parsed.path.startswith(prefix.rstrip("/") + "/") or parsed.path.startswith(prefix)
            for prefix in self.plan.allowed_path_prefixes
        ):
            return False
        if any(parsed.path.startswith(prefix) for prefix in self.plan.ignored_path_prefixes):
            return False
        if self.adapter.should_ignore_url(normalized):
            return False
        if any(pattern.search(normalized) for pattern in self.ignore_patterns):
            return False
        if not self.plan.include_changelog and any(token in normalized.lower() for token in ["/changelog", "/release-notes", "/whatsnew", "/what-s-new"]):
            return False
        if any(parsed.path.lower().endswith(ext) for ext in self.config.crawl.ignored_asset_extensions):
            return False
        return is_probably_document_url(normalized) or parsed.path.endswith("/")

    async def load_sitemap_urls(self) -> list[str]:
        if not self.config.crawl.discover_sitemaps:
            return []
        candidates = list(dict.fromkeys([*self.plan.sitemap_urls, *self._default_sitemap_candidates()]))
        discovered: list[str] = []
        seen: set[str] = set()
        for sitemap_url in candidates:
            try:
                async with httpx.AsyncClient(timeout=self.config.crawl.request_timeout_seconds, headers={"User-Agent": self.config.crawl.user_agent}) as client:
                    response = await client.get(sitemap_url)
                if response.status_code >= 400:
                    continue
                root = ElementTree.fromstring(response.content)
            except Exception:
                continue
            queue = deque([root])
            while queue and len(discovered) < self.config.crawl.max_sitemap_urls:
                node = queue.popleft()
                tag = node.tag.rsplit("}", 1)[-1]
                if tag == "loc" and node.text:
                    candidate = normalize_url(node.text)
                    if candidate not in seen and self.should_visit(candidate):
                        seen.add(candidate)
                        discovered.append(candidate)
                for child in list(node):
                    queue.append(child)
        if discovered:
            LOGGER.info("Loaded %s sitemap URLs for %s", len(discovered), self.plan.language.slug)
        return discovered

    def _default_sitemap_candidates(self) -> list[str]:
        urls = []
        for seed in self.plan.start_urls:
            parsed = urlparse(seed)
            root = f"{parsed.scheme}://{parsed.netloc}"
            urls.append(f"{root}/sitemap.xml")
        return urls

    def make_record(self, url: str, *, depth: int = 0, parent_url: str | None = None, discovered_from: str | None = None) -> UrlRecord:
        normalized = normalize_url(
            url,
            drop_query_params=self.config.crawl.drop_query_params,
            keep_query_params=self.config.crawl.keep_query_params,
        )
        return UrlRecord(
            url=url,
            normalized_url=normalized,
            depth=depth,
            parent_url=parent_url,
            discovered_from=discovered_from,
        )
