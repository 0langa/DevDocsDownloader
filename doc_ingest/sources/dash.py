from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from bs4 import BeautifulSoup  # type: ignore[import-untyped]

from ..cache import decide_cache_refresh, write_cache_metadata, write_cache_metadata_for_bytes
from ..conversion import DASH_PROFILE, HtmlCleanupProfile, convert_html_to_markdown_with_diagnostics
from ..models import DryRunResult, ResumeBoundary, SourceRunDiagnostics
from ..runtime import NotModifiedResponse, SourceRuntime
from ..utils.archive import safe_extract_tar
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, SourceError, document_events
from .catalog_manifest import DiscoveryManifest, load_manifest, manifest_languages, save_manifest

LOGGER = logging.getLogger("doc_ingest.sources.dash")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0)"
FEED_BASE = "https://kapeli.com/feeds"
SOURCE_ROOT_URL = "https://kapeli.com"
CHEATSHEETS_URL = "https://kapeli.com/cheatsheets"

CORE_TYPES = {
    "Class",
    "Module",
    "Function",
    "Method",
    "Macro",
    "Guide",
    "Tutorial",
    "Reference",
    "Section",
    "Package",
    "Trait",
    "Struct",
    "Enum",
    "Protocol",
    "Type",
    "Keyword",
    "Builtin",
    "Library",
    "Namespace",
    "Interface",
}


class DashFeedSource:
    name = "dash"

    def __init__(
        self, *, cache_dir: Path, catalog_seed: Path | None = None, runtime: SourceRuntime | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "dash.json"
        self.docsets_dir = cache_dir / "dash"
        self.profile_stats_path = self.docsets_dir / "_profile_stats.json"
        self.quality_stats_path = self.docsets_dir / "_quality_stats.json"
        self.profile_registry_path = Path(__file__).with_name("dash_profiles.json")
        self.runtime = runtime or SourceRuntime(user_agent=USER_AGENT)

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        decision = decide_cache_refresh(
            self.catalog_path,
            source=self.name,
            cache_key="catalog",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
            cache_root=self.runtime.cache_root,
            max_cache_size_bytes=self.runtime.max_cache_size_bytes,
        )
        self.runtime.record_cache_decision(decision)
        if not decision.should_refresh and not self.catalog_path.exists():
            raise SourceError(
                "cache_budget_exceeded",
                "Cache budget prevents refreshing the Dash catalog.",
                hint="Clear cache entries or raise the cache budget in Settings.",
                is_retriable=False,
            )
        if not decision.should_refresh and self.catalog_path.exists():
            cached = manifest_languages(self.catalog_path)
            if cached:
                return await self._enrich_catalog_entries(cached)

        try:
            response = await self.runtime.request("GET", CHEATSHEETS_URL, profile="default")
            if isinstance(response, NotModifiedResponse):
                raise SourceError(
                    "invalid_format", "Unexpected not-modified response for Dash catalog.", is_retriable=True
                )
            catalogs = self._discover_catalog_entries(response.text)
            if not catalogs:
                raise SourceError(
                    "invalid_format",
                    "Kapeli cheat sheets page did not expose any docset entries.",
                    hint="Dash feed page may have changed. Refresh again later.",
                    is_retriable=True,
                )
            catalogs = await self._enrich_catalog_entries(catalogs)
            save_manifest(
                self.catalog_path,
                DiscoveryManifest(
                    source=self.name,
                    source_root_url=SOURCE_ROOT_URL,
                    discovery_strategy="kapeli-cheatsheets-page/v1",
                    entries=catalogs,
                    diagnostics={"entry_count": len(catalogs)},
                ),
            )
            write_cache_metadata(
                self.catalog_path,
                source=self.name,
                cache_key="catalog",
                url=CHEATSHEETS_URL,
                policy=self.runtime.cache_policy,
                response=response,
                refreshed_by_force=force_refresh,
            )
            return catalogs
        except Exception as exc:
            cached_manifest = load_manifest(self.catalog_path)
            if cached_manifest is not None and cached_manifest.entries:
                LOGGER.warning("Falling back to cached Dash catalog after live discovery failure: %s", exc)
                cached_manifest.fallback_used = True
                cached_manifest.fallback_reason = f"{type(exc).__name__}: {exc}"
                save_manifest(self.catalog_path, cached_manifest)
                entries = [entry for entry in cached_manifest.entries if entry.support_level != "ignored"]
                return await self._enrich_catalog_entries(entries)
            raise

    async def _enrich_catalog_entries(self, catalogs: list[LanguageCatalog]) -> list[LanguageCatalog]:
        if not catalogs:
            return catalogs
        sem = asyncio.Semaphore(10)
        quality_stats = self._load_json_map(self.quality_stats_path)

        async def enrich(entry: LanguageCatalog) -> None:
            url = f"{FEED_BASE}/{entry.slug}.tgz"
            async with sem:
                try:
                    response = await self.runtime.request("HEAD", url, profile="default")
                except Exception:
                    response = None
            if response is not None and not isinstance(response, NotModifiedResponse):
                size = int(response.headers.get("content-length") or 0)
                if size > 0:
                    entry.size_hint = size
                    entry.discovery_metadata["tgz_size_bytes"] = size
                last_modified = response.headers.get("last-modified", "")
                if last_modified:
                    entry.discovery_metadata["tgz_last_modified"] = last_modified
            confidence = _quality_confidence(quality_stats.get(entry.slug) or {})
            if confidence:
                entry.discovery_metadata["confidence"] = confidence

        await asyncio.gather(*(enrich(entry) for entry in catalogs))
        return catalogs

    def _discover_catalog_entries(self, html: str) -> list[LanguageCatalog]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        catalogs: list[LanguageCatalog] = []
        for anchor in soup.select('a[href*="/cheat_sheets/"]'):
            href_value = anchor.get("href")
            href = href_value if isinstance(href_value, str) else ""
            match = re.search(r"/cheat_sheets/([^/]+)\.docset", href)
            if not match:
                continue
            slug = match.group(1).strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            display_name = (anchor.get_text(" ", strip=True) or slug).strip()
            clean_display = re.sub(r"\s+", " ", display_name)
            catalogs.append(
                LanguageCatalog(
                    source=self.name,
                    slug=slug,
                    display_name=clean_display,
                    version="live",
                    core_topics=sorted(CORE_TYPES),
                    all_topics=[],
                    homepage=f"{SOURCE_ROOT_URL}{href if href.startswith('/') else '/' + href}",
                    aliases=[clean_display.lower(), slug.replace("_", " ")],
                    support_level="supported",
                    discovery_reason="Discovered from Kapeli cheat sheets index",
                    discovery_metadata={
                        "feed_url": f"{FEED_BASE}/{slug}.tgz",
                        "cheatsheet_url": f"{SOURCE_ROOT_URL}{href if href.startswith('/') else '/' + href}",
                    },
                )
            )
        return sorted(catalogs, key=lambda entry: entry.display_name.lower())

    async def _download_docset(self, slug: str, *, force_refresh: bool = False) -> Path:
        target_dir = self.docsets_dir / slug
        metadata_target = target_dir / "_docset.tgz"
        decision = decide_cache_refresh(
            metadata_target,
            source=self.name,
            cache_key=f"{slug}/docset",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
            cache_root=self.runtime.cache_root,
            max_cache_size_bytes=self.runtime.max_cache_size_bytes,
        )
        self.runtime.record_cache_decision(decision)
        if not decision.should_refresh and not any(target_dir.glob("*.docset")):
            raise SourceError(
                "cache_budget_exceeded",
                f"Cache budget prevents refreshing the Dash docset for {slug}.",
                hint="Clear cache entries or raise the cache budget in Settings.",
                is_retriable=False,
            )
        if not decision.should_refresh and any(target_dir.glob("*.docset")):
            return next(target_dir.glob("*.docset"))
        target_dir.mkdir(parents=True, exist_ok=True)

        tarball_url = f"{FEED_BASE}/{slug}.tgz"
        LOGGER.info("Downloading Dash docset %s", tarball_url)
        use_conditional = metadata_target.exists() and self.runtime.cache_policy in {"ttl", "validate-if-possible"}
        metadata = decision.metadata
        try:
            resp = await self.runtime.request(
                "GET",
                tarball_url,
                profile="dash",
                conditional=use_conditional,
                etag=metadata.etag if metadata is not None else "",
                last_modified=metadata.last_modified if metadata is not None else "",
            )
        except Exception as exc:
            raise _dash_source_error_from_http(exc, slug=slug) from exc
        if isinstance(resp, NotModifiedResponse):
            matches = list(target_dir.glob("*.docset"))
            if not matches:
                raise SourceError(
                    "invalid_format",
                    f"Dash returned not-modified for {slug}, but no extracted .docset exists locally.",
                    hint="Clear cached Dash metadata and retry.",
                    is_retriable=False,
                )
            write_cache_metadata_for_bytes(
                metadata_target,
                metadata_target.read_bytes() if metadata_target.exists() else b"",
                source=self.name,
                cache_key=f"{slug}/docset",
                url=tarball_url,
                policy=self.runtime.cache_policy,
                etag=resp.headers.get("etag") or (metadata.etag if metadata is not None else ""),
                last_modified=resp.headers.get("last-modified")
                or (metadata.last_modified if metadata is not None else ""),
                refreshed_by_force=force_refresh,
            )
            return matches[0]
        tar_bytes = resp.content

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as handle:
            handle.write(tar_bytes)
            tar_path = Path(handle.name)
        try:
            try:
                with tarfile.open(tar_path, "r:gz") as archive:
                    safe_extract_tar(archive, target_dir)
            except tarfile.TarError as exc:
                raise SourceError(
                    "invalid_format",
                    f"Dash feed for {slug} is not a valid gzip/tar archive.",
                    hint="Dash docset archive is corrupt — clear cache and retry.",
                    is_retriable=False,
                ) from exc
        finally:
            tar_path.unlink(missing_ok=True)

        matches = list(target_dir.glob("*.docset"))
        if not matches:
            raise SourceError(
                "invalid_format",
                f"No .docset found after extracting {slug}.",
                hint="Dash docset archive is corrupt — clear cache and retry.",
                is_retriable=False,
            )
        metadata_target.write_bytes(tar_bytes)
        write_cache_metadata_for_bytes(
            metadata_target,
            tar_bytes,
            source=self.name,
            cache_key=f"{slug}/docset",
            url=tarball_url,
            policy=self.runtime.cache_policy,
            response=resp,
            refreshed_by_force=force_refresh,
        )
        return matches[0]

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]:
        docset_path = await self._download_docset(language.slug, force_refresh=force_refresh)
        dsidx = docset_path / "Contents" / "Resources" / "docSet.dsidx"
        docs_root = docset_path / "Contents" / "Resources" / "Documents"
        if not dsidx.exists():
            raise SourceError(
                "invalid_format",
                f"Missing docSet.dsidx for {language.slug}.",
                hint="Dash docset archive is corrupt — clear cache and retry.",
                is_retriable=False,
            )

        core = {t.lower() for t in (language.core_topics or [])} or {t.lower() for t in CORE_TYPES}
        connection = sqlite3.connect(dsidx)
        try:
            rows = connection.execute("SELECT name, type, path FROM searchIndex ORDER BY type, name").fetchall()
        finally:
            connection.close()
        if diagnostics is not None:
            diagnostics.discovered += len(rows)
        total_indexed = len(rows)
        fragment_refs = _dash_fragment_references(rows)
        profile = self._resolve_profile(language)
        selector_hits: dict[str, int] = {}
        conversion_successes = 0
        emitted_documents = 0
        seen_paths: set[str] = set()
        for order, (name, entry_type, path) in enumerate(rows):
            if order and order % 50 == 0:
                await asyncio.sleep(0)
            doc_key = str(path).split("#", 1)[0] if path else ""
            if resume_boundary is not None and order <= resume_boundary.document_inventory_position:
                if doc_key:
                    seen_paths.add(doc_key)
                if diagnostics is not None:
                    diagnostics.skip("checkpoint_resume_skip")
                continue
            if not path or not entry_type:
                if diagnostics is not None:
                    diagnostics.skip("missing_path_or_type")
                continue
            entry_type = str(entry_type)
            if mode == "important" and entry_type.lower() not in core:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue
            if doc_key in seen_paths:
                if diagnostics is not None:
                    diagnostics.skip("duplicate_path")
                continue
            seen_paths.add(doc_key)
            html_file = docs_root / doc_key
            if not html_file.exists():
                if diagnostics is not None:
                    diagnostics.skip("missing_file")
                continue
            html = await asyncio.to_thread(html_file.read_text, "utf-8", "ignore")
            source_url = f"dash://{language.slug}/{doc_key}"
            markdown, matched_selector = await asyncio.to_thread(_convert_html_with_selector, html, source_url, profile)
            selector_hits[matched_selector] = selector_hits.get(matched_selector, 0) + 1
            markdown = _append_fragment_reference_notes(markdown, fragment_refs.get(doc_key, []))
            if not markdown.strip():
                if diagnostics is not None:
                    diagnostics.skip("empty_markdown")
                continue
            conversion_successes += 1
            emitted_documents += 1
            if diagnostics is not None:
                diagnostics.emitted += 1
            yield Document(
                topic=entry_type,
                slug=_slug(doc_key),
                title=str(name),
                markdown=markdown,
                source_url=source_url,
                order_hint=order,
            )
        self._persist_profile_learning(language.slug, selector_hits)
        self._persist_quality_stats(
            language.slug,
            indexed_entry_count=total_indexed,
            emitted_document_count=emitted_documents,
            conversion_success_rate=(conversion_successes / total_indexed) if total_indexed else 0.0,
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
        topics = list(language.core_topics or sorted(CORE_TYPES))
        include_topics = include_topics or set()
        exclude_topics = exclude_topics or set()
        if include_topics:
            topics = [topic for topic in topics if topic.lower() in include_topics]
        if exclude_topics:
            topics = [topic for topic in topics if topic.lower() not in exclude_topics]
        target_dir = self.docsets_dir / language.slug
        matches = list(target_dir.glob("*.docset"))
        if matches:
            count = await asyncio.to_thread(
                _count_dash_entries, matches[0], mode, include_topics, exclude_topics, topics
            )
            return DryRunResult(
                language=language.display_name,
                source=self.name,
                slug=language.slug,
                estimated_document_count=count,
                estimated_size_hint=language.size_hint or None,
                topics=sorted(set(topics)),
            )
        return DryRunResult(
            language=language.display_name,
            source=self.name,
            slug=language.slug,
            estimated_document_count=None,
            estimated_size_hint=language.size_hint or None,
            topics=sorted(set(topics)),
            notes=["Dash previews use cached docset metadata when available; no cached docset exists yet."],
        )

    def _resolve_profile(self, language: LanguageCatalog) -> HtmlCleanupProfile:
        bundled = self._load_json_map(self.profile_registry_path)
        learned = self._load_json_map(self.profile_stats_path)
        learned_entry = learned.get(language.slug) or {}
        bundled_entry = bundled.get(language.slug) or bundled.get(language.display_name) or {}
        learned_selectors = tuple(str(v) for v in learned_entry.get("content_selectors", []) if str(v).strip())
        bundled_selectors = tuple(str(v) for v in bundled_entry.get("content_selectors", []) if str(v).strip())
        bundled_noise = tuple(str(v) for v in bundled_entry.get("noise_selectors", []) if str(v).strip())
        content_selectors = learned_selectors or bundled_selectors or DASH_PROFILE.content_selectors
        noise_selectors = bundled_noise or DASH_PROFILE.noise_selectors
        return HtmlCleanupProfile(content_selectors=content_selectors, noise_selectors=noise_selectors)

    def _persist_profile_learning(self, slug: str, selector_hits: dict[str, int]) -> None:
        if not selector_hits:
            return
        ordered = [k for k, _v in sorted(selector_hits.items(), key=lambda item: -item[1])]
        payload = self._load_json_map(self.profile_stats_path)
        payload[slug] = {"content_selectors": ordered}
        self.profile_stats_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_stats_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _persist_quality_stats(
        self, slug: str, *, indexed_entry_count: int, emitted_document_count: int, conversion_success_rate: float
    ) -> None:
        payload = self._load_json_map(self.quality_stats_path)
        payload[slug] = {
            "indexed_entry_count": indexed_entry_count,
            "emitted_document_count": emitted_document_count,
            "conversion_success_rate": round(conversion_success_rate, 4),
        }
        self.quality_stats_path.parent.mkdir(parents=True, exist_ok=True)
        self.quality_stats_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_json_map(self, path: Path) -> dict[str, dict]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}


def _convert_html(
    html: str, base_url: str = "dash://docset/index.html", profile: HtmlCleanupProfile = DASH_PROFILE
) -> str:
    markdown, _matched = _convert_html_with_selector(html, base_url, profile)
    return markdown


def _convert_html_with_selector(
    html: str, base_url: str = "dash://docset/index.html", profile: HtmlCleanupProfile = DASH_PROFILE
) -> tuple[str, str]:
    markdown, diagnostics = convert_html_to_markdown_with_diagnostics(html, base_url=base_url, profile=profile)
    return markdown, diagnostics.matched_selector


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")
    return cleaned.lower() or "index"


def _dash_fragment_references(rows: list[tuple[str, str, str]]) -> dict[str, list[tuple[str, str]]]:
    refs: dict[str, list[tuple[str, str]]] = {}
    for name, _entry_type, path in rows:
        doc_key, fragment = str(path).split("#", 1) if path and "#" in str(path) else (str(path), "")
        if not doc_key or not fragment:
            continue
        refs.setdefault(doc_key, []).append((str(name), fragment))
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


def _dash_source_error_from_http(exc: Exception, *, slug: str) -> SourceError:
    if isinstance(exc, httpx.TimeoutException):
        return SourceError(
            "network_timeout",
            f"Dash request timed out for {slug}.",
            hint="Check your internet connection.",
            is_retriable=True,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 404:
            return SourceError(
                "not_found",
                f"Dash docset was not found for {slug}.",
                hint="The docset may have been removed upstream.",
                is_retriable=False,
            )
        if status == 429:
            return SourceError(
                "rate_limited",
                f"Dash rate limit hit while fetching {slug}.",
                hint="Dash source rate limit hit — wait 60 seconds.",
                is_retriable=True,
            )
    return SourceError(
        "network_timeout",
        f"Dash request failed for {slug}: {type(exc).__name__}: {exc}",
        hint="Check your internet connection.",
        is_retriable=True,
    )


def _count_dash_entries(
    docset_path: Path,
    mode: CrawlMode,
    include_topics: set[str],
    exclude_topics: set[str],
    topics: list[str],
) -> int:
    dsidx = docset_path / "Contents" / "Resources" / "docSet.dsidx"
    if not dsidx.exists():
        return 0
    core = {topic.lower() for topic in topics} or {topic.lower() for topic in CORE_TYPES}
    connection = sqlite3.connect(dsidx)
    try:
        rows = connection.execute("SELECT type, path FROM searchIndex ORDER BY type, name").fetchall()
    finally:
        connection.close()
    seen_paths: set[str] = set()
    count = 0
    for entry_type, path in rows:
        doc_key = str(path).split("#", 1)[0] if path else ""
        if not path or not entry_type or doc_key in seen_paths:
            continue
        topic = str(entry_type).lower()
        if mode == "important" and topic not in core:
            continue
        if include_topics and topic not in include_topics:
            continue
        if exclude_topics and topic in exclude_topics:
            continue
        seen_paths.add(doc_key)
        count += 1
    return count


def _quality_confidence(stats: dict) -> str:
    try:
        indexed = int(stats.get("indexed_entry_count") or 0)
        success = float(stats.get("conversion_success_rate") or 0.0)
    except Exception:
        return ""
    if indexed >= 200 and success >= 0.9:
        return "high"
    if indexed >= 50 and success >= 0.7:
        return "medium"
    if indexed > 0:
        return "low"
    return ""
