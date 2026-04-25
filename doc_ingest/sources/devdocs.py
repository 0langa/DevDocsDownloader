from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from ..cache import decide_cache_refresh, write_cache_metadata
from ..conversion import DEVDOCS_PROFILE, convert_html_to_markdown
from ..models import ResumeBoundary, SourceRunDiagnostics
from ..runtime import SourceRuntime
from ..utils.filesystem import write_bytes, write_json
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, document_events

LOGGER = logging.getLogger("doc_ingest.sources.devdocs")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0; +https://devdocs.io)"
DOCS_INDEX_URL = "https://devdocs.io/docs.json"
DOCUMENTS_BASE = "https://documents.devdocs.io"


class DevDocsSource:
    name = "devdocs"

    def __init__(self, *, cache_dir: Path, core_topics_path: Path, runtime: SourceRuntime | None = None) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "devdocs.json"
        self.data_cache = cache_dir / "devdocs"
        self.runtime = runtime or SourceRuntime(user_agent=USER_AGENT)
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

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        decision = decide_cache_refresh(
            self.catalog_path,
            source=self.name,
            cache_key="catalog",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
        )
        if not decision.should_refresh and self.catalog_path.exists():
            try:
                payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                return [self._catalog_from_entry(entry) for entry in payload.get("entries", [])]
            except Exception:
                LOGGER.debug("Re-fetching devdocs catalog due to cache read failure", exc_info=True)

        response = await self.runtime.request("GET", DOCS_INDEX_URL, profile="default")
        response.raise_for_status()
        entries = response.json()

        write_json(self.catalog_path, {"entries": entries})
        write_cache_metadata(
            self.catalog_path,
            source=self.name,
            cache_key="catalog",
            url=DOCS_INDEX_URL,
            policy=self.runtime.cache_policy,
            response=response,
            refreshed_by_force=force_refresh,
        )
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

    async def _download_dataset(self, slug: str, *, force_refresh: bool = False) -> tuple[dict, dict]:
        dataset_dir = self.data_cache / slug
        dataset_dir.mkdir(parents=True, exist_ok=True)
        index_path = dataset_dir / "index.json"
        db_path = dataset_dir / "db.json"

        await self._ensure_json_dataset(slug, index_path, "index.json", force_refresh=force_refresh)
        await self._ensure_json_dataset(slug, db_path, "db.json", force_refresh=force_refresh)

        index = self._load_json_cache(index_path, slug=slug, label="index")
        db = self._load_json_cache(db_path, slug=slug, label="db")
        return index, db

    async def _ensure_json_dataset(
        self,
        slug: str,
        path: Path,
        filename: str,
        force_refresh: bool = False,
    ) -> None:
        decision = decide_cache_refresh(
            path,
            source=self.name,
            cache_key=f"{slug}/{filename}",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
        )
        if not decision.should_refresh and path.exists() and self._is_valid_json_file(path):
            return
        if path.exists():
            LOGGER.warning("Refreshing corrupt DevDocs %s cache for %s", filename, slug)
        LOGGER.info("Downloading DevDocs %s for %s", filename.replace(".json", ""), slug)
        url = f"{DOCUMENTS_BASE}/{slug}/{filename}"
        resp = await self.runtime.request("GET", url, profile="default")
        resp.raise_for_status()
        write_bytes(path, resp.content)
        write_cache_metadata(
            path,
            source=self.name,
            cache_key=f"{slug}/{filename}",
            url=url,
            policy=self.runtime.cache_policy,
            response=resp,
            refreshed_by_force=force_refresh,
        )

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
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]:
        index, db = await self._download_dataset(language.slug, force_refresh=force_refresh)

        entries = index.get("entries", [])
        if diagnostics is not None:
            diagnostics.discovered += len(entries)
        core_topics = {topic.lower() for topic in language.core_topics}

        seen_doc_keys: set[str] = set()
        for order, entry in enumerate(entries):
            raw_path = entry.get("path") or ""
            doc_key = raw_path.split("#", 1)[0]
            if resume_boundary is not None and order <= resume_boundary.document_inventory_position:
                if doc_key:
                    seen_doc_keys.add(doc_key)
                if diagnostics is not None:
                    diagnostics.skip("checkpoint_resume_skip")
                continue

            entry_type = entry.get("type") or "Documentation"
            if mode == "important" and core_topics and entry_type.lower() not in core_topics:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

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

            source_url = f"https://devdocs.io/{language.slug}/{doc_key}"
            markdown = await asyncio.to_thread(_convert_html, html, source_url)
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
                source_url=source_url,
                order_hint=order,
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


def _convert_html(html: str, base_url: str = "https://devdocs.io/") -> str:
    return convert_html_to_markdown(html, base_url=base_url, profile=DEVDOCS_PROFILE)


def _slug(path: str) -> str:
    cleaned = path.replace("/", "-").strip("-") or "index"
    return cleaned
