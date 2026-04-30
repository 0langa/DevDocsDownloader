from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup  # type: ignore[import-untyped]

from ..cache import decide_cache_refresh, write_cache_metadata_for_bytes
from ..conversion import DEVDOCS_PROFILE, convert_html_to_markdown
from ..models import DryRunResult, ResumeBoundary, SourceRunDiagnostics
from ..runtime import NotModifiedResponse, SourceRuntime
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, SourceError, document_events
from .catalog_manifest import DiscoveryManifest, manifest_languages, save_manifest

SOURCE_ROOT_URL = "https://web-page.local"


class WebPageSource:
    name = "web_page"

    def __init__(self, *, cache_dir: Path, runtime: SourceRuntime | None = None) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "web_page.json"
        self.pages_root = cache_dir / "web_page"
        self.seed_path = Path(__file__).with_name("web_sources.json")
        self.runtime = runtime or SourceRuntime()

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        seed = self._load_seed()
        entries: list[LanguageCatalog] = []
        for row in seed:
            entries.append(
                LanguageCatalog(
                    source=self.name,
                    slug=str(row.get("slug") or ""),
                    display_name=str(row.get("display_name") or row.get("slug") or ""),
                    version="live",
                    core_topics=[str(x) for x in row.get("core_topics") or []],
                    all_topics=[],
                    homepage=str(row.get("homepage") or row.get("doc_url") or ""),
                    aliases=[str(row.get("family") or ""), str(row.get("slug") or "").replace("-", " ")],
                    support_level="supported",
                    discovery_reason="Configured in web_sources.json",
                    discovery_metadata={
                        "doc_url": str(row.get("doc_url") or ""),
                        "content_selector": str(row.get("content_selector") or "body"),
                        "section_selector": str(row.get("section_selector") or "h2, h3"),
                        "crawl_links": bool(row.get("crawl_links", False)),
                        "allowed_path_prefix": str(row.get("allowed_path_prefix") or ""),
                        "max_pages": int(row.get("max_pages") or 200),
                    },
                )
            )
        save_manifest(
            self.catalog_path,
            DiscoveryManifest(
                source=self.name,
                source_root_url=SOURCE_ROOT_URL,
                discovery_strategy="web_sources.json/v1",
                entries=entries,
                diagnostics={"entry_count": len(entries)},
            ),
        )
        return manifest_languages(self.catalog_path)

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]:
        _ = mode
        pages = await self._resolve_pages(language, force_refresh=force_refresh)
        emitted = 0
        for page_url in pages:
            html = await self._fetch_page(language.slug, page_url, force_refresh=force_refresh)
            sections = self._extract_sections(
                html,
                page_url=page_url,
                content_selector=str(language.discovery_metadata.get("content_selector") or "body"),
                section_selector=str(language.discovery_metadata.get("section_selector") or "h2, h3"),
            )
            if diagnostics is not None:
                diagnostics.discovered += len(sections)
            for section_title, section_html, source_url in sections:
                emitted += 1
                if resume_boundary is not None and emitted <= resume_boundary.document_inventory_position:
                    if diagnostics is not None:
                        diagnostics.skip("checkpoint_resume_skip")
                    continue
                markdown = convert_html_to_markdown(section_html, base_url=source_url, profile=DEVDOCS_PROFILE)
                if not markdown.strip():
                    if diagnostics is not None:
                        diagnostics.skip("empty_markdown")
                    continue
                if diagnostics is not None:
                    diagnostics.emitted += 1
                yield Document(
                    topic="Section",
                    slug=_slugify(section_title),
                    title=section_title,
                    markdown=markdown,
                    source_url=source_url,
                    order_hint=emitted,
                )

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics, resume_boundary=resume_boundary))

    async def preview(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        *,
        force_refresh: bool = False,
        include_topics: set[str] | None = None,
        exclude_topics: set[str] | None = None,
    ) -> DryRunResult:
        _ = (mode, force_refresh, include_topics, exclude_topics)
        pages = await self._resolve_pages(language, force_refresh=False)
        return DryRunResult(
            language=language.display_name,
            source=self.name,
            slug=language.slug,
            estimated_document_count=max(1, len(pages) * 5),
            estimated_size_hint=None,
            topics=language.core_topics,
        )

    async def _resolve_pages(self, language: LanguageCatalog, *, force_refresh: bool) -> list[str]:
        doc_url = str(language.discovery_metadata.get("doc_url") or "")
        if not doc_url:
            raise SourceError("invalid_format", f"Missing doc_url for {language.slug}", is_retriable=False)
        crawl_links = bool(language.discovery_metadata.get("crawl_links", False))
        if not crawl_links:
            return [doc_url]
        html = await self._fetch_page(language.slug, doc_url, force_refresh=force_refresh)
        soup = BeautifulSoup(html, "lxml")
        allowed_prefix = str(language.discovery_metadata.get("allowed_path_prefix") or "")
        max_pages = int(language.discovery_metadata.get("max_pages") or 200)
        pages = [doc_url]
        seen = {doc_url}
        for a in soup.select("a[href]"):
            href = str(a.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(doc_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if allowed_prefix and not parsed.path.startswith(allowed_prefix):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            pages.append(absolute)
            if len(pages) >= max_pages:
                break
        return pages

    async def _fetch_page(self, slug: str, url: str, *, force_refresh: bool) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-").lower() or "page"
        page_path = self.pages_root / slug / f"{safe_name}.html"
        decision = decide_cache_refresh(
            page_path,
            source=self.name,
            cache_key=f"{slug}/{safe_name}",
            policy=self.runtime.cache_policy,
            ttl_hours=(self.runtime.cache_ttl_hours if self.runtime.cache_ttl_hours is not None else 24 * 7),
            force_refresh=force_refresh,
            cache_root=self.runtime.cache_root,
            max_cache_size_bytes=self.runtime.max_cache_size_bytes,
        )
        self.runtime.record_cache_decision(decision)
        metadata = decision.metadata
        if not decision.should_refresh and page_path.exists():
            return page_path.read_text(encoding="utf-8", errors="ignore")
        page_path.parent.mkdir(parents=True, exist_ok=True)
        response = await self.runtime.request(
            "GET",
            url,
            conditional=page_path.exists() and self.runtime.cache_policy in {"ttl", "validate-if-possible"},
            etag=metadata.etag if metadata is not None else "",
            last_modified=metadata.last_modified if metadata is not None else "",
        )
        if isinstance(response, NotModifiedResponse):
            return page_path.read_text(encoding="utf-8", errors="ignore")
        page_path.write_text(response.text, encoding="utf-8")
        write_cache_metadata_for_bytes(
            page_path,
            response.content,
            source=self.name,
            cache_key=f"{slug}/{safe_name}",
            url=url,
            policy=self.runtime.cache_policy,
            response=response,
            refreshed_by_force=force_refresh,
        )
        return response.text

    def _extract_sections(
        self, html: str, *, page_url: str, content_selector: str, section_selector: str
    ) -> list[tuple[str, str, str]]:
        soup = BeautifulSoup(html, "lxml")
        root = soup.select_one(content_selector) or soup
        headings = root.select(section_selector)
        if not headings:
            title = soup.title.string.strip() if soup.title and soup.title.string else page_url
            return [(title, str(root), page_url)]
        out: list[tuple[str, str, str]] = []
        for heading in headings:
            title = heading.get_text(" ", strip=True) or "Section"
            fragments = [str(heading)]
            node = heading.next_sibling
            while node is not None:
                if getattr(node, "name", "") and node in headings:
                    break
                fragments.append(str(node))
                node = node.next_sibling
            out.append((title, "".join(fragments), page_url))
        return out

    def _load_seed(self) -> list[dict]:
        if not self.seed_path.exists():
            return []
        payload = json.loads(self.seed_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "section"
