from __future__ import annotations

import asyncio
import logging
import re
import tarfile
from pathlib import Path
from typing import AsyncIterator

import httpx

from .base import CrawlMode, Document, LanguageCatalog

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
    "guide", "landing-page",
    "javascript-class", "javascript-function", "javascript-global-property",
    "javascript-language-feature", "javascript-operator", "javascript-statement",
    "css-at-rule", "css-property", "css-selector", "css-type",
    "html-element", "html-attribute",
    "web-api-interface", "web-api-static-method", "web-api-instance-method",
    "http-header", "http-method", "http-status-code",
}


class MdnContentSource:
    name = "mdn"

    def __init__(self, *, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "mdn.json"
        self.archive_path = cache_dir / "mdn" / "mdn-content-main.tar.gz"
        self.extracted_root = cache_dir / "mdn" / "content"

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {"slug": slug, "display_name": display, "area": area}
            for slug, (display, area) in AREAS.items()
        ]
        self.catalog_path.write_text(
            __import__("json").dumps({"entries": entries}, indent=2),
            encoding="utf-8",
        )
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
        if marker.exists():
            return self.extracted_root

        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.archive_path.exists():
            LOGGER.info("Downloading MDN content archive (may take a while)")
            async with httpx.AsyncClient(
                timeout=None, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DocIngestBot/1.0)"},
            ) as client:
                async with client.stream("GET", TARBALL_URL) as response:
                    response.raise_for_status()
                    with self.archive_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes(chunk_size=1 << 20):
                            handle.write(chunk)

        self.extracted_root.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Extracting MDN content archive")
        await asyncio.to_thread(_extract_tarball, self.archive_path, self.extracted_root)
        marker.write_text("ok", encoding="utf-8")
        return self.extracted_root

    async def fetch(self, language: LanguageCatalog, mode: CrawlMode) -> AsyncIterator[Document]:
        _display, area = AREAS[language.slug]
        root = await self._ensure_content()
        top = next(root.iterdir(), None)
        if top is None:
            raise RuntimeError("MDN content archive extraction produced no files")
        area_root = top / "files" / "en-us" / area
        if not area_root.exists():
            raise RuntimeError(f"MDN area missing: {area_root}")

        core = {t.lower() for t in language.core_topics}
        files = sorted(area_root.rglob("index.md"))

        for order, md_path in enumerate(files):
            raw = md_path.read_text(encoding="utf-8", errors="ignore")
            meta, body = _parse_frontmatter(raw)
            page_type = (meta.get("page-type") or "").lower()
            if mode == "important" and core and page_type not in core:
                continue

            rel = md_path.relative_to(area_root).parent
            topic_parts = rel.parts[:1] or ("reference",)
            topic = topic_parts[0].replace("_", " ").title() or "Reference"
            title = meta.get("title") or rel.name.replace("_", " ")
            slug_path = "/".join(rel.parts)

            yield Document(
                topic=topic,
                slug=_slug(slug_path),
                title=title,
                markdown=body.strip(),
                source_url=f"https://developer.mozilla.org/en-US/docs/{meta.get('slug', slug_path)}",
                order_hint=order,
            )


def _extract_tarball(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name
            if not any(f"/files/en-us/{area}" in name for area in {a[1] for a in AREAS.values()}):
                if not (name.endswith("/files/en-us") or name.count("/") <= 3):
                    continue
            tar.extract(member, dest)


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
