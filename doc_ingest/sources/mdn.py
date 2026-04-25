from __future__ import annotations

import asyncio
import logging
import re
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path

from ..models import SourceRunDiagnostics
from ..runtime import SourceRuntime
from ..utils.archive import safe_extract_tar
from ..utils.filesystem import write_json, write_text
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

    async def _ensure_content(self) -> Path:
        marker = self.extracted_root / ".ready"
        if marker.exists() and self._has_expected_tree(self.extracted_root):
            return self.extracted_root
        if marker.exists() and not self._has_expected_tree(self.extracted_root):
            LOGGER.warning("MDN ready marker exists but extracted tree is incomplete; rebuilding cache")
            marker.unlink(missing_ok=True)

        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.archive_path.exists():
            LOGGER.info("Downloading MDN content archive (may take a while)")
            await self.runtime.stream_to_file(TARBALL_URL, self.archive_path, profile="download")

        self.extracted_root.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Extracting MDN content archive")
        await asyncio.to_thread(_extract_tarball, self.archive_path, self.extracted_root)
        if not self._has_expected_tree(self.extracted_root):
            raise RuntimeError("MDN content archive extracted without required documentation tree")
        write_text(marker, "ok")
        return self.extracted_root

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
    ) -> AsyncIterator[Document]:
        _display, area = AREAS[language.slug]
        root = await self._ensure_content()
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
            raw = md_path.read_text(encoding="utf-8", errors="ignore")
            meta, body = _parse_frontmatter(raw)
            page_type = (meta.get("page-type") or "").lower()
            if mode == "important" and core and page_type not in core:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

            rel = md_path.relative_to(area_root).parent
            topic_parts = rel.parts[:1] or ("reference",)
            topic = topic_parts[0].replace("_", " ").title() or "Reference"
            title = meta.get("title") or rel.name.replace("_", " ")
            slug_path = "/".join(rel.parts)

            if diagnostics is not None:
                diagnostics.emitted += 1
            yield Document(
                topic=topic,
                slug=_slug(slug_path),
                title=title,
                markdown=body.strip(),
                source_url=f"https://developer.mozilla.org/en-US/docs/{meta.get('slug', slug_path)}",
                order_hint=order,
            )

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics))


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


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta_block, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return cleaned or "index"
