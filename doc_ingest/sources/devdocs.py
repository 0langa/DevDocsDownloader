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
from ..utils.filesystem import write_bytes
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, document_events
from .catalog_manifest import DiscoveryManifest, load_manifest, manifest_languages, save_manifest

LOGGER = logging.getLogger("doc_ingest.sources.devdocs")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0; +https://devdocs.io)"
DOCS_INDEX_URL = "https://devdocs.io/docs.json"
DOCUMENTS_BASE = "https://documents.devdocs.io"
SOURCE_ROOT_URL = "https://devdocs.io"


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
        self.runtime.record_cache_decision(decision)
        if not decision.should_refresh and self.catalog_path.exists():
            cached = manifest_languages(self.catalog_path)
            if cached:
                return cached

        try:
            response = await self.runtime.request("GET", DOCS_INDEX_URL, profile="default")
            response.raise_for_status()
            entries = response.json()
            if not isinstance(entries, list):
                raise ValueError("DevDocs catalog did not return a list")
            catalogs = [self._catalog_from_entry(entry) for entry in entries if isinstance(entry, dict)]
            if not catalogs:
                raise ValueError("DevDocs catalog returned no valid entries")
            save_manifest(
                self.catalog_path,
                DiscoveryManifest(
                    source=self.name,
                    source_root_url=SOURCE_ROOT_URL,
                    discovery_strategy="docs.json/v1",
                    entries=catalogs,
                    diagnostics={"entry_count": len(catalogs)},
                ),
            )
            write_cache_metadata(
                self.catalog_path,
                source=self.name,
                cache_key="catalog",
                url=DOCS_INDEX_URL,
                policy=self.runtime.cache_policy,
                response=response,
                refreshed_by_force=force_refresh,
            )
            return catalogs
        except Exception as exc:
            cached_manifest = load_manifest(self.catalog_path)
            if cached_manifest is not None and cached_manifest.entries:
                LOGGER.warning("Falling back to cached DevDocs catalog after live discovery failure: %s", exc)
                cached_manifest.fallback_used = True
                cached_manifest.fallback_reason = f"{type(exc).__name__}: {exc}"
                save_manifest(self.catalog_path, cached_manifest)
                return [entry for entry in cached_manifest.entries if entry.support_level != "ignored"]
            raise

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
            aliases=[family] if family and family != slug else [],
            support_level="supported",
            discovery_reason="Listed in DevDocs docs.json catalog",
            discovery_metadata={"family": family, "index_url": DOCS_INDEX_URL},
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
        self.runtime.record_cache_decision(decision)
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
        fragment_refs = _fragment_references(entries)

        seen_doc_keys: set[str] = set()
        for order, entry in enumerate(entries):
            if order and order % 50 == 0:
                await asyncio.sleep(0)
            raw_path = entry.get("path") or ""
            doc_key = raw_path.split("#", 1)[0]
            if resume_boundary is not None and order <= resume_boundary.document_inventory_position:
                seen_doc_keys.add(doc_key)
                if diagnostics is not None:
                    diagnostics.skip("checkpoint_resume_skip")
                continue

            entry_type = entry.get("type") or "Documentation"
            if mode == "important" and core_topics and entry_type.lower() not in core_topics:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

            if doc_key in seen_doc_keys:
                if diagnostics is not None:
                    diagnostics.skip("duplicate_path")
                continue
            seen_doc_keys.add(doc_key)

            html = db.get(doc_key)
            if not html:
                if diagnostics is not None:
                    diagnostics.skip("missing_content")
                continue

            source_url = (
                f"https://devdocs.io/{language.slug}/{doc_key}" if doc_key else f"https://devdocs.io/{language.slug}/"
            )
            markdown = await asyncio.to_thread(_convert_html, html, source_url)
            markdown = _append_fragment_reference_notes(markdown, fragment_refs.get(doc_key, []))
            if not markdown.strip():
                if diagnostics is not None:
                    diagnostics.skip("empty_markdown")
                continue

            if diagnostics is not None:
                diagnostics.emitted += 1
            yield Document(
                topic=entry_type,
                slug=_slug(doc_key),
                title=entry.get("name") or doc_key or language.display_name,
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


def _fragment_references(entries: list[dict]) -> dict[str, list[tuple[str, str]]]:
    refs: dict[str, list[tuple[str, str]]] = {}
    for entry in entries:
        raw_path = str(entry.get("path") or "")
        doc_key, fragment = raw_path.split("#", 1) if "#" in raw_path else (raw_path, "")
        if not doc_key or not fragment:
            continue
        refs.setdefault(doc_key, []).append((str(entry.get("name") or fragment), fragment))
    return refs


def _append_fragment_reference_notes(markdown: str, fragment_refs: list[tuple[str, str]]) -> str:
    if not fragment_refs:
        return markdown
    lines = [markdown.rstrip(), "", "## Merged Upstream Fragment References", ""]
    seen: set[tuple[str, str]] = set()
    for title, fragment in fragment_refs:
        key = (title, fragment)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {title} (`#{fragment}`)")
    lines.append("")
    return "\n".join(lines)
