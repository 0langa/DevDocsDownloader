from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import tarfile
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from ..cache import decide_cache_refresh, read_cache_metadata, write_cache_metadata
from ..conversion import rewrite_markdown_links
from ..models import DryRunResult, ResumeBoundary, SourceRunDiagnostics
from ..runtime import NotModifiedResponse, SourceRuntime
from ..utils.archive import safe_extract_tar
from ..utils.filesystem import read_json, write_json
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, SourceError, document_events
from .catalog_manifest import DiscoveryManifest, load_manifest, manifest_languages, save_manifest

LOGGER = logging.getLogger("doc_ingest.sources.mdn")

TARBALL_URL = "https://codeload.github.com/mdn/content/tar.gz/refs/heads/main"
COMMITS_API_URL = "https://api.github.com/repos/mdn/content/commits/main"
SOURCE_ROOT_URL = "https://developer.mozilla.org/en-US/docs"
CONTENT_ROOT_URL = "https://raw.githubusercontent.com/mdn/content/main/files/en-us"
SUPPORTED_MDN_AREAS = {
    "web/javascript",
    "web/html",
    "web/css",
    "web/http",
    "web/api",
    "webassembly",
}
AREA_SLUG_ALIASES = {
    "web/javascript": ["javascript", "js"],
    "web/html": ["html"],
    "web/css": ["css"],
    "web/http": ["http"],
    "web/api": ["web-apis", "web api", "api"],
    "webassembly": ["webassembly", "wasm"],
}

CORE_PAGE_TYPES = {
    "guide",
    "landing-page",
    "javascript-class",
    "javascript-function",
    "javascript-global-property",
    "javascript-language-feature",
    "javascript-operator",
    "javascript-statement",
    "css-at-rule",
    "css-property",
    "css-selector",
    "css-type",
    "html-element",
    "html-attribute",
    "web-api-interface",
    "web-api-static-method",
    "web-api-instance-method",
    "http-header",
    "http-method",
    "http-status-code",
}


@dataclass(slots=True)
class MdnArchiveIndex:
    archive_size: int
    archive_mtime_ns: int
    archive_sha256: str
    root_prefix: str
    mdn_commit_sha: str = ""
    ready_areas: dict[str, list[str]] = field(default_factory=dict)
    area_root_members: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ready_areas = {key: sorted(value) for key, value in self.ready_areas.items()}
        self.area_root_members = dict(self.area_root_members)


class MdnContentSource:
    name = "mdn"

    def __init__(self, *, cache_dir: Path, runtime: SourceRuntime | None = None) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "mdn.json"
        self.archive_path = cache_dir / "mdn" / "mdn-content-main.tar.gz"
        self.extracted_root = cache_dir / "mdn" / "content"
        self.metadata_path = cache_dir / "mdn" / "cache_meta.json"
        self.index_path = cache_dir / "mdn" / "archive_index.json"
        self.runtime = runtime or SourceRuntime()

    def _find_content_root(self, root: Path) -> Path | None:
        direct = root / "files" / "en-us"
        if direct.exists():
            return root
        for candidate in sorted(root.iterdir()):
            if candidate.is_dir() and (candidate / "files" / "en-us").exists():
                return candidate
        return None

    def _has_expected_tree(self, root: Path) -> bool:
        top = self._find_content_root(root)
        if top is None:
            return False
        return any((top / "files" / "en-us" / area).exists() for area in SUPPORTED_MDN_AREAS)

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
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
                "Cache budget prevents refreshing the MDN catalog.",
                hint="Clear cache entries or raise the cache budget in Settings.",
                is_retriable=False,
            )
        if not decision.should_refresh and self.catalog_path.exists():
            cached = manifest_languages(self.catalog_path)
            if cached:
                return cached

        try:
            index = await self._ensure_archive_index(force_refresh=force_refresh)
            catalogs = await asyncio.to_thread(self._discover_catalog_entries_from_archive, index)
            if not catalogs:
                raise RuntimeError("MDN discovery found no documentation areas")
            save_manifest(
                self.catalog_path,
                DiscoveryManifest(
                    source=self.name,
                    source_root_url=SOURCE_ROOT_URL,
                    discovery_strategy="content-archive-scan/v2",
                    entries=catalogs,
                    diagnostics={
                        "entry_count": len(catalogs),
                        "supported_count": sum(1 for entry in catalogs if entry.support_level == "supported"),
                        "mdn_commit_sha": index.mdn_commit_sha,
                    },
                ),
            )
            write_cache_metadata(
                self.catalog_path,
                source=self.name,
                cache_key="catalog",
                url=TARBALL_URL,
                policy=self.runtime.cache_policy,
                refreshed_by_force=force_refresh,
                mdn_commit_sha=index.mdn_commit_sha,
            )
            return [entry for entry in catalogs if entry.support_level != "ignored"]
        except Exception as exc:
            cached_manifest = load_manifest(self.catalog_path)
            if cached_manifest is not None and cached_manifest.entries:
                LOGGER.warning("Falling back to cached MDN catalog after live discovery failure: %s", exc)
                cached_manifest.fallback_used = True
                cached_manifest.fallback_reason = f"{type(exc).__name__}: {exc}"
                save_manifest(self.catalog_path, cached_manifest)
                return [entry for entry in cached_manifest.entries if entry.support_level != "ignored"]
            raise

    async def _ensure_archive_index(self, *, area: str | None = None, force_refresh: bool = False) -> MdnArchiveIndex:
        decision = decide_cache_refresh(
            self.archive_path,
            source=self.name,
            cache_key="content-archive",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
            cache_root=self.runtime.cache_root,
            max_cache_size_bytes=self.runtime.max_cache_size_bytes,
        )
        self.runtime.record_cache_decision(decision)
        if not decision.should_refresh and not self.archive_path.exists():
            raise SourceError(
                "cache_budget_exceeded",
                "Cache budget prevents refreshing the MDN content archive.",
                hint="Clear cache entries or raise the cache budget in Settings.",
                is_retriable=False,
            )
        latest_commit_sha = await self._latest_commit_sha()
        refresh_requested = force_refresh or decision.should_refresh or not self.archive_path.exists()

        if refresh_requested:
            archive_metadata = read_cache_metadata(self.archive_path)
            if (
                not force_refresh
                and self.archive_path.exists()
                and latest_commit_sha
                and archive_metadata is not None
                and archive_metadata.mdn_commit_sha == latest_commit_sha
            ):
                write_cache_metadata(
                    self.archive_path,
                    source=self.name,
                    cache_key="content-archive",
                    url=TARBALL_URL,
                    policy=self.runtime.cache_policy,
                    source_version=latest_commit_sha,
                    mdn_commit_sha=latest_commit_sha,
                )
                refresh_requested = False
            else:
                self.archive_path.parent.mkdir(parents=True, exist_ok=True)
                LOGGER.info("Downloading MDN content archive (may take a while)")
                await self.runtime.stream_to_file(TARBALL_URL, self.archive_path, profile="download")
                write_cache_metadata(
                    self.archive_path,
                    source=self.name,
                    cache_key="content-archive",
                    url=TARBALL_URL,
                    policy=self.runtime.cache_policy,
                    source_version=latest_commit_sha,
                    refreshed_by_force=force_refresh,
                    mdn_commit_sha=latest_commit_sha,
                )

        index = self._load_archive_index(area=area)
        if index is not None:
            return index

        index = await asyncio.to_thread(self._scan_archive_index)
        if latest_commit_sha:
            index.mdn_commit_sha = latest_commit_sha
        self._write_archive_index(index)
        if area is not None and area not in index.ready_areas:
            raise RuntimeError(f"MDN area missing from archive index: {area}")
        return index

    async def _latest_commit_sha(self) -> str:
        try:
            response = await self.runtime.request("GET", COMMITS_API_URL)
            if isinstance(response, NotModifiedResponse):
                return ""
            payload = response.json()
        except Exception as exc:
            LOGGER.warning("Failed to query MDN commit SHA: %s", exc)
            metadata = read_cache_metadata(self.archive_path)
            return metadata.mdn_commit_sha if metadata is not None else ""
        if isinstance(payload, dict):
            return str(payload.get("sha") or "").strip()
        return ""

    def _load_archive_index(self, *, area: str | None = None) -> MdnArchiveIndex | None:
        try:
            payload = read_json(self.index_path, {})
            if not isinstance(payload, dict) or not payload:
                return None
            index = MdnArchiveIndex(
                archive_size=int(payload.get("archive_size") or 0),
                archive_mtime_ns=int(payload.get("archive_mtime_ns") or 0),
                archive_sha256=str(payload.get("archive_sha256") or ""),
                root_prefix=str(payload.get("root_prefix") or ""),
                mdn_commit_sha=str(payload.get("mdn_commit_sha") or ""),
                ready_areas={
                    str(key): [str(item) for item in value]
                    for key, value in (payload.get("ready_areas") or {}).items()
                    if isinstance(value, list)
                },
                area_root_members={
                    str(key): str(value) for key, value in (payload.get("area_root_members") or {}).items()
                },
            )
        except Exception:
            return None

        try:
            stat = self.archive_path.stat()
        except OSError:
            return None
        if index.archive_size != stat.st_size or index.archive_mtime_ns != stat.st_mtime_ns:
            return None
        archive_metadata = read_cache_metadata(self.archive_path)
        checksum = archive_metadata.checksum if archive_metadata is not None else _sha256_file(self.archive_path)
        if index.archive_sha256 != checksum:
            return None
        if area is not None and area not in index.ready_areas:
            return None
        return index

    def _write_archive_index(self, index: MdnArchiveIndex) -> None:
        write_json(
            self.index_path,
            {
                "archive_size": index.archive_size,
                "archive_mtime_ns": index.archive_mtime_ns,
                "archive_sha256": index.archive_sha256,
                "root_prefix": index.root_prefix,
                "mdn_commit_sha": index.mdn_commit_sha,
                "ready_areas": index.ready_areas,
                "area_root_members": index.area_root_members,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )
        write_json(
            self.metadata_path,
            {
                "archive_url": TARBALL_URL,
                "archive_size": index.archive_size,
                "archive_mtime_ns": index.archive_mtime_ns,
                "archive_sha256": index.archive_sha256,
                "mdn_commit_sha": index.mdn_commit_sha,
                "ready_areas": sorted(index.ready_areas),
                "generated_at": datetime.now(UTC).isoformat(),
                "source": self.name,
                "cache_key": "content-archive",
                "url": TARBALL_URL,
                "policy": self.runtime.cache_policy,
            },
        )

    def _scan_archive_index(self) -> MdnArchiveIndex:
        stat = self.archive_path.stat()
        checksum = _sha256_file(self.archive_path)
        ready_areas: dict[str, list[str]] = defaultdict(list)
        area_root_members: dict[str, str] = {}
        root_prefix = ""
        with tarfile.open(self.archive_path, "r:gz") as archive:
            for member in archive:
                if not member.isfile() or not member.name.endswith("/index.md"):
                    continue
                relative = _relative_member_path(member.name)
                if relative is None:
                    continue
                if not root_prefix:
                    root_prefix = member.name[: -len(relative)].rstrip("/")
                area = _member_area(relative)
                if area is None:
                    continue
                ready_areas[area].append(member.name)
                if relative == f"{area}/index.md":
                    area_root_members[area] = member.name
        return MdnArchiveIndex(
            archive_size=stat.st_size,
            archive_mtime_ns=stat.st_mtime_ns,
            archive_sha256=checksum,
            root_prefix=root_prefix,
            ready_areas=dict(ready_areas),
            area_root_members=area_root_members,
        )

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]:
        area = str(language.discovery_metadata.get("area") or "")
        if not area:
            raise SourceError(
                "invalid_format",
                f"MDN catalog entry for {language.slug} is missing discovery area metadata.",
                hint="Refresh catalogs and retry.",
                is_retriable=False,
            )
        index = await self._ensure_archive_index(area=area, force_refresh=force_refresh)
        member_names = list(index.ready_areas.get(area) or [])
        if not member_names:
            raise SourceError(
                "not_found",
                f"MDN area missing from archive: {area}.",
                hint="Refresh the MDN cache and retry.",
                is_retriable=True,
            )

        if diagnostics is not None:
            diagnostics.discovered += len(member_names)

        core = {t.lower() for t in language.core_topics}
        order_lookup = {name: position for position, name in enumerate(sorted(member_names))}
        pending = set(order_lookup)
        with tarfile.open(self.archive_path, "r:gz") as archive:
            for member in archive:
                if not member.isfile() or member.name not in pending:
                    continue
                order = order_lookup[member.name]
                if order and order % 50 == 0:
                    await asyncio.sleep(0)
                if resume_boundary is not None and order <= resume_boundary.document_inventory_position:
                    if diagnostics is not None:
                        diagnostics.skip("checkpoint_resume_skip")
                    pending.remove(member.name)
                    continue

                handle = archive.extractfile(member)
                if handle is None:
                    pending.remove(member.name)
                    continue
                raw = handle.read().decode("utf-8", errors="ignore")
                meta, body, parse_warning = _parse_frontmatter(raw)
                if parse_warning and diagnostics is not None:
                    diagnostics.skip("malformed_frontmatter")
                page_types = _metadata_strings(meta.get("page-type"))
                if mode == "important" and core and not any(page_type.lower() in core for page_type in page_types):
                    if diagnostics is not None:
                        diagnostics.skip("filtered_mode")
                    pending.remove(member.name)
                    continue

                relative_doc = Path(_relative_member_path(member.name) or "index.md")
                doc_relative = relative_doc.relative_to(Path(area))
                rel = doc_relative.parent
                topic_parts = rel.parts[:1] or ("reference",)
                topic = topic_parts[0].replace("_", " ").title() or "Reference"
                title = _metadata_text(meta.get("title")) or rel.name.replace("_", " ")
                slug_path = "/".join(rel.parts)
                source_slug = _metadata_text(meta.get("slug")) or slug_path
                source_url = f"https://developer.mozilla.org/en-US/docs/{source_slug}"
                markdown = rewrite_markdown_links(body.strip(), base_url=source_url)

                if diagnostics is not None:
                    diagnostics.emitted += 1
                yield Document(
                    topic=topic,
                    slug=_slug(slug_path),
                    title=title,
                    markdown=markdown,
                    source_url=source_url,
                    order_hint=order,
                )
                pending.remove(member.name)
                if not pending:
                    break

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(
            self.fetch(
                language,
                mode,
                diagnostics=diagnostics,
                resume_boundary=resume_boundary,
                force_refresh=force_refresh,
            )
        )

    async def preview(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        *,
        force_refresh: bool = False,
        include_topics: set[str] | None = None,
        exclude_topics: set[str] | None = None,
    ) -> DryRunResult:
        area = str(language.discovery_metadata.get("area") or "")
        estimated_count = int(language.discovery_metadata.get("document_count") or 0) or None
        notes: list[str] = []
        if force_refresh or estimated_count is None:
            index = await self._ensure_archive_index(area=area or None, force_refresh=force_refresh)
            if area and area in index.ready_areas:
                estimated_count = len(index.ready_areas[area])
        topics = list(language.core_topics)
        include_topics = include_topics or set()
        exclude_topics = exclude_topics or set()
        if include_topics:
            topics = [topic for topic in topics if topic.lower() in include_topics]
        if exclude_topics:
            topics = [topic for topic in topics if topic.lower() not in exclude_topics]
        if estimated_count is None:
            notes.append("Document count estimate unavailable until the MDN archive index is refreshed.")
        return DryRunResult(
            language=language.display_name,
            source=self.name,
            slug=language.slug,
            estimated_document_count=estimated_count,
            estimated_size_hint=language.size_hint or None,
            topics=sorted(set(topics)),
            notes=notes,
        )

    def _discover_catalog_entries_from_archive(self, index: MdnArchiveIndex) -> list[LanguageCatalog]:
        root_members = {member for member in index.area_root_members.values()}
        payloads = _read_selected_archive_texts(self.archive_path, root_members)
        catalogs: list[LanguageCatalog] = []
        for relative_area in sorted(index.ready_areas):
            root_member = index.area_root_members.get(relative_area)
            if not root_member:
                continue
            raw = payloads.get(root_member, "")
            meta, _body, _warning = _parse_frontmatter(raw)
            title = _metadata_text(meta.get("title")) or _display_from_area(relative_area)
            slug = _slug_for_area(relative_area)
            aliases = AREA_SLUG_ALIASES.get(relative_area, [slug])
            support_level: Literal["supported", "experimental", "ignored"]
            support_level = "supported" if relative_area in SUPPORTED_MDN_AREAS else "experimental"
            reason = (
                "Recognized stable MDN documentation family"
                if support_level == "supported"
                else "Discovered from MDN content tree; not yet part of the stable quality set"
            )
            source_slug = _metadata_text(meta.get("slug")) or relative_area
            catalogs.append(
                LanguageCatalog(
                    source=self.name,
                    slug=slug,
                    display_name=title,
                    version="main",
                    core_topics=sorted(CORE_PAGE_TYPES),
                    all_topics=[],
                    homepage=f"{SOURCE_ROOT_URL}/{source_slug}",
                    aliases=aliases,
                    support_level=support_level,
                    discovery_reason=reason,
                    discovery_metadata={
                        "area": relative_area,
                        "mdn_slug": source_slug,
                        "content_url": f"{CONTENT_ROOT_URL}/{relative_area}/index.md",
                        "mdn_commit_sha": index.mdn_commit_sha,
                        "document_count": len(index.ready_areas.get(relative_area) or []),
                    },
                )
            )
        return catalogs


def _read_selected_archive_texts(archive_path: Path, members: set[str]) -> dict[str, str]:
    remaining = set(members)
    payloads: dict[str, str] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if not remaining:
                break
            if not member.isfile() or member.name not in remaining:
                continue
            handle = archive.extractfile(member)
            if handle is None:
                remaining.remove(member.name)
                continue
            payloads[member.name] = handle.read().decode("utf-8", errors="ignore")
            remaining.remove(member.name)
    return payloads


def _relative_member_path(member_name: str) -> str | None:
    marker = "/files/en-us/"
    if marker not in member_name:
        return None
    return member_name.split(marker, 1)[1]


def _member_area(relative_path: str) -> str | None:
    parts = Path(relative_path).parts
    if not parts or parts[-1] != "index.md":
        return None
    if parts[0] == "web" and len(parts) >= 3:
        return "/".join(parts[:2])
    if len(parts) >= 2:
        return parts[0]
    return None


def _extract_tarball(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:

        def _keep_member(member: tarfile.TarInfo) -> bool:
            name = member.name
            normalized = name.rstrip("/")
            if not any(f"/files/en-us/{area}" in normalized for area in SUPPORTED_MDN_AREAS):
                if not (
                    normalized.endswith("/files") or normalized.endswith("/files/en-us") or normalized.count("/") <= 3
                ):
                    return False
            return True

        safe_extract_tar(tar, dest, member_filter=_keep_member)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, None
    meta_block, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(meta_block) or {}
    except yaml.YAMLError as exc:
        return {}, text, f"Failed to parse MDN frontmatter: {exc}"
    if not isinstance(parsed, dict):
        return {}, body, "MDN frontmatter is not a mapping"
    return parsed, body, None


def _metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _metadata_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [_metadata_text(item) for item in value if _metadata_text(item)]
    return [_metadata_text(value)] if _metadata_text(value) else []


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return cleaned or "index"


def _slug_for_area(area: str) -> str:
    if area == "web/api":
        return "web-apis"
    parts = area.split("/")
    if parts[:1] == ["web"] and len(parts) == 2:
        return parts[1]
    return _slug(area)


def _display_from_area(area: str) -> str:
    if area == "web/api":
        return "Web APIs"
    parts = area.split("/")
    label = parts[-1].replace("_", " ").replace("-", " ").strip()
    return " ".join(piece.capitalize() for piece in label.split()) or area


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
