from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx
from markdownify import markdownify as html_to_md

from ..models import SourceRunDiagnostics
from .base import CrawlMode, Document, LanguageCatalog
from ..utils.filesystem import write_bytes, write_json
from ..utils.http import request_with_retries

LOGGER = logging.getLogger("doc_ingest.sources.devdocs")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0; +https://devdocs.io)"
DOCS_INDEX_URL = "https://devdocs.io/docs.json"
DOCUMENTS_BASE = "https://documents.devdocs.io"


class DevDocsSource:
    name = "devdocs"

    def __init__(self, *, cache_dir: Path, core_topics_path: Path) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "devdocs.json"
        self.data_cache = cache_dir / "devdocs"
        self._core_topics = self._load_core_topics(core_topics_path)

    @staticmethod
    def _load_core_topics(path: Path) -> dict[str, list[str]]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            LOGGER.warning("Failed to parse devdocs core topics file %s", path)
            return {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"},
            timeout=60.0,
            follow_redirects=True,
        )

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        if not force_refresh and self.catalog_path.exists():
            try:
                payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                return [self._catalog_from_entry(entry) for entry in payload.get("entries", [])]
            except Exception:
                LOGGER.debug("Re-fetching devdocs catalog due to cache read failure", exc_info=True)

        async with self._client() as client:
            response = await request_with_retries(client, "GET", DOCS_INDEX_URL)
            response.raise_for_status()
            entries = response.json()

        write_json(self.catalog_path, {"entries": entries})
        return [self._catalog_from_entry(entry) for entry in entries]

    def _catalog_from_entry(self, entry: dict) -> LanguageCatalog:
        slug = entry.get("slug") or entry.get("name", "").lower()
        family = entry.get("type") or slug.split("~", 1)[0]
        core = self._core_topics.get(slug) or self._core_topics.get(family, [])
        return LanguageCatalog(
            source=self.name,
            slug=slug,
            display_name=entry.get("name") or slug,
            version=entry.get("version") or entry.get("release") or "",
            core_topics=list(core),
            all_topics=[],
            size_hint=int(entry.get("db_size") or 0),
            homepage=entry.get("links", {}).get("home", "") if isinstance(entry.get("links"), dict) else "",
        )

    async def _download_dataset(self, slug: str) -> tuple[dict, dict]:
        dataset_dir = self.data_cache / slug
        dataset_dir.mkdir(parents=True, exist_ok=True)
        index_path = dataset_dir / "index.json"
        db_path = dataset_dir / "db.json"

        async with self._client() as client:
            await self._ensure_json_dataset(client, slug, index_path, "index.json")
            await self._ensure_json_dataset(client, slug, db_path, "db.json")

        index = self._load_json_cache(index_path, slug=slug, label="index")
        db = self._load_json_cache(db_path, slug=slug, label="db")
        return index, db

    async def _ensure_json_dataset(
        self,
        client: httpx.AsyncClient,
        slug: str,
        path: Path,
        filename: str,
    ) -> None:
        if path.exists() and self._is_valid_json_file(path):
            return
        if path.exists():
            LOGGER.warning("Refreshing corrupt DevDocs %s cache for %s", filename, slug)
        LOGGER.info("Downloading DevDocs %s for %s", filename.replace('.json', ''), slug)
        resp = await request_with_retries(client, "GET", f"{DOCUMENTS_BASE}/{slug}/{filename}")
        resp.raise_for_status()
        write_bytes(path, resp.content)

    def _is_valid_json_file(self, path: Path) -> bool:
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return True
        except Exception:
            return False

    def _load_json_cache(self, path: Path, *, slug: str, label: str) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"DevDocs {label} cache is invalid for {slug}: {path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"DevDocs {label} cache has unexpected format for {slug}: {path}")
        return payload

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[Document]:
        index, db = await self._download_dataset(language.slug)

        entries = index.get("entries", [])
        if diagnostics is not None:
            diagnostics.discovered += len(entries)
        core_topics = {topic.lower() for topic in language.core_topics}

        seen_doc_keys: set[str] = set()
        for order, entry in enumerate(entries):
            entry_type = entry.get("type") or "Documentation"
            if mode == "important" and core_topics and entry_type.lower() not in core_topics:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

            raw_path = entry.get("path") or ""
            doc_key = raw_path.split("#", 1)[0]
            if not doc_key or doc_key in seen_doc_keys:
                if diagnostics is not None:
                    diagnostics.skip("duplicate_or_empty_path")
                continue
            seen_doc_keys.add(doc_key)

            html = db.get(doc_key)
            if not html:
                if diagnostics is not None:
                    diagnostics.skip("missing_content")
                continue

            markdown = await asyncio.to_thread(_convert_html, html)
            if not markdown.strip():
                if diagnostics is not None:
                    diagnostics.skip("empty_markdown")
                continue

            if diagnostics is not None:
                diagnostics.emitted += 1
            yield Document(
                topic=entry_type,
                slug=_slug(doc_key),
                title=entry.get("name") or doc_key,
                markdown=markdown,
                source_url=f"https://devdocs.io/{language.slug}/{doc_key}",
                order_hint=order,
            )


def _convert_html(html: str) -> str:
    return html_to_md(html, heading_style="ATX", strip=["script", "style"])


def _slug(path: str) -> str:
    cleaned = path.replace("/", "-").strip("-") or "index"
    return cleaned
