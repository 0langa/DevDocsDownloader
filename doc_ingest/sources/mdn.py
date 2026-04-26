from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import tarfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ..cache import decide_cache_refresh, write_cache_metadata
from ..conversion import rewrite_markdown_links
from ..models import ResumeBoundary, SourceRunDiagnostics
from ..runtime import SourceRuntime
from ..utils.archive import safe_extract_tar
from ..utils.filesystem import read_json, write_json
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, document_events

LOGGER = logging.getLogger("doc_ingest.sources.mdn")

TARBALL_URL = "https://codeload.github.com/mdn/content/tar.gz/refs/heads/main"

AREAS = {
    "javascript": ("JavaScript", "web/javascript"),
    "html": ("HTML", "web/html"),
    "css": ("CSS", "web/css"),
    "web-apis": ("Web APIs", "web/api"),
    "http": ("HTTP", "web/http"),
    "webassembly": ("WebAssembly", "webassembly"),
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


class MdnContentSource:
    name = "mdn"

    def __init__(self, *, cache_dir: Path, runtime: SourceRuntime | None = None) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "mdn.json"
        self.archive_path = cache_dir / "mdn" / "mdn-content-main.tar.gz"
        self.extracted_root = cache_dir / "mdn" / "content"
        self.metadata_path = cache_dir / "mdn" / "cache_meta.json"
        self.runtime = runtime or SourceRuntime()

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"slug": slug, "display_name": display, "area": area} for slug, (display, area) in AREAS.items()]
        write_json(self.catalog_path, {"entries": entries})
        return [
            LanguageCatalog(
                source=self.name,
                slug=slug,
                display_name=display,
                version="main",
                core_topics=sorted(CORE_PAGE_TYPES),
                all_topics=[],
                homepage=f"https://developer.mozilla.org/en-US/docs/{area.title().replace('/', '/')}",
            )
            for slug, (display, area) in AREAS.items()
        ]

    async def _ensure_content(self, *, area: str | None = None, force_refresh: bool = False) -> Path:
        decision = decide_cache_refresh(
            self.archive_path,
            source=self.name,
            cache_key="content-archive",
            policy=self.runtime.cache_policy,
            ttl_hours=self.runtime.cache_ttl_hours,
            force_refresh=force_refresh,
        )
        self.runtime.record_cache_decision(decision)
        refresh_requested = force_refresh or decision.should_refresh
        if not refresh_requested and self.archive_path.exists() and self._metadata_matches(area):
            return self.extracted_root

        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        if refresh_requested or not self.archive_path.exists():
            LOGGER.info("Downloading MDN content archive (may take a while)")
            await self.runtime.stream_to_file(TARBALL_URL, self.archive_path, profile="download")

        self.extracted_root.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Extracting MDN content archive")
        await asyncio.to_thread(_extract_tarball, self.archive_path, self.extracted_root)
        if not self._has_expected_tree(self.extracted_root):
            raise RuntimeError("MDN content archive extracted without required documentation tree")
        self._write_cache_metadata()
        return self.extracted_root

    def _metadata_matches(self, area: str | None) -> bool:
        metadata = read_json(self.metadata_path, {})
        if not isinstance(metadata, dict):
            return False
        try:
            stat = self.archive_path.stat()
        except OSError:
            return False
        if metadata.get("archive_url") != TARBALL_URL:
            return False
        if metadata.get("archive_size") != stat.st_size:
            return False
        if metadata.get("archive_mtime_ns") != stat.st_mtime_ns:
            return False
        if metadata.get("archive_sha256") != _sha256_file(self.archive_path):
            return False
        ready_areas = set(metadata.get("ready_areas") or [])
        required = {area} if area else {area_value for _display, area_value in AREAS.values()}
        if not required.issubset(ready_areas):
            return False
        top = self._find_content_root(self.extracted_root)
        if top is None:
            return False
        return all((top / "files" / "en-us" / item).exists() for item in required)

    def _write_cache_metadata(self) -> None:
        stat = self.archive_path.stat()
        top = self._find_content_root(self.extracted_root)
        ready_areas = []
        if top is not None:
            ready_areas = [area for _display, area in AREAS.values() if (top / "files" / "en-us" / area).exists()]
        checksum = _sha256_file(self.archive_path)
        write_json(
            self.metadata_path,
            {
                "archive_url": TARBALL_URL,
                "archive_size": stat.st_size,
                "archive_mtime_ns": stat.st_mtime_ns,
                "archive_sha256": checksum,
                "extracted_checksum": checksum,
                "ready_areas": sorted(ready_areas),
                "generated_at": datetime.now(UTC).isoformat(),
                "source": self.name,
                "cache_key": "content-archive",
                "url": TARBALL_URL,
                "policy": self.runtime.cache_policy,
            },
        )
        write_cache_metadata(
            self.archive_path,
            source=self.name,
            cache_key="content-archive",
            url=TARBALL_URL,
            policy=self.runtime.cache_policy,
        )

    def _has_expected_tree(self, root: Path) -> bool:
        top = self._find_content_root(root)
        if top is None:
            return False
        return any((top / "files" / "en-us" / area).exists() for _display, area in AREAS.values())

    def _find_content_root(self, root: Path) -> Path | None:
        direct = root / "files" / "en-us"
        if direct.exists():
            return root
        for candidate in sorted(root.iterdir()):
            if candidate.is_dir() and (candidate / "files" / "en-us").exists():
                return candidate
        return None

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]:
        _display, area = AREAS[language.slug]
        root = await self._ensure_content(area=area, force_refresh=force_refresh)
        top = self._find_content_root(root)
        if top is None:
            raise RuntimeError("MDN content archive extraction produced no files")
        area_root = top / "files" / "en-us" / area
        if not area_root.exists():
            raise RuntimeError(f"MDN area missing: {area_root}")

        core = {t.lower() for t in language.core_topics}
        files = sorted(area_root.rglob("index.md"))
        if diagnostics is not None:
            diagnostics.discovered += len(files)

        for order, md_path in enumerate(files):
            if resume_boundary is not None and order <= resume_boundary.document_inventory_position:
                if diagnostics is not None:
                    diagnostics.skip("checkpoint_resume_skip")
                continue
            raw = md_path.read_text(encoding="utf-8", errors="ignore")
            meta, body, parse_warning = _parse_frontmatter(raw)
            if parse_warning and diagnostics is not None:
                diagnostics.skip("malformed_frontmatter")
            page_types = _metadata_strings(meta.get("page-type"))
            if mode == "important" and core and not any(page_type.lower() in core for page_type in page_types):
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

            rel = md_path.relative_to(area_root).parent
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


def _extract_tarball(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:

        def _keep_member(member: tarfile.TarInfo) -> bool:
            name = member.name
            normalized = name.rstrip("/")
            if not any(f"/files/en-us/{area}" in normalized for area in {a[1] for a in AREAS.values()}):
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
