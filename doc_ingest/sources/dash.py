from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import AsyncIterator

import httpx
from markdownify import markdownify as html_to_md

from .base import CrawlMode, Document, LanguageCatalog

LOGGER = logging.getLogger("doc_ingest.sources.dash")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0)"
FEED_BASE = "https://kapeli.com/feeds"


CORE_TYPES = {
    "Class", "Module", "Function", "Method", "Macro", "Guide", "Tutorial",
    "Reference", "Section", "Package", "Trait", "Struct", "Enum", "Protocol",
    "Type", "Keyword", "Builtin", "Library", "Namespace", "Interface",
}


class DashFeedSource:
    name = "dash"

    def __init__(self, *, cache_dir: Path, catalog_seed: Path | None = None) -> None:
        self.cache_dir = cache_dir
        self.catalog_path = cache_dir / "catalogs" / "dash.json"
        self.docsets_dir = cache_dir / "dash"
        self._catalog_seed = catalog_seed

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=300.0,
            follow_redirects=True,
        )

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        if not force_refresh and self.catalog_path.exists():
            try:
                payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                return [self._catalog_from_entry(entry) for entry in payload.get("entries", [])]
            except Exception:
                LOGGER.debug("Falling back to seed catalog", exc_info=True)

        # Dash does not publish an easily-consumable JSON index; use a bundled seed.
        if self._catalog_seed and self._catalog_seed.exists():
            entries = json.loads(self._catalog_seed.read_text(encoding="utf-8"))
        else:
            entries = _DEFAULT_DASH_SEED

        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_path.write_text(json.dumps({"entries": entries}, indent=2), encoding="utf-8")
        return [self._catalog_from_entry(entry) for entry in entries]

    def _catalog_from_entry(self, entry: dict) -> LanguageCatalog:
        return LanguageCatalog(
            source=self.name,
            slug=entry["slug"],
            display_name=entry.get("display_name") or entry["slug"],
            version=entry.get("version", ""),
            core_topics=entry.get("core_topics") or sorted(CORE_TYPES),
            all_topics=[],
            homepage=entry.get("homepage", ""),
        )

    async def _download_docset(self, slug: str) -> Path:
        target_dir = self.docsets_dir / slug
        if any(target_dir.glob("*.docset")):
            return next(target_dir.glob("*.docset"))
        target_dir.mkdir(parents=True, exist_ok=True)

        tarball_url = f"{FEED_BASE}/{slug}.tgz"
        LOGGER.info("Downloading Dash docset %s", tarball_url)
        async with self._client() as client:
            resp = await client.get(tarball_url)
            resp.raise_for_status()
            tar_bytes = resp.content

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as handle:
            handle.write(tar_bytes)
            tar_path = Path(handle.name)

        try:
            try:
                with tarfile.open(tar_path, "r:gz") as archive:
                    archive.extractall(target_dir)
            except tarfile.TarError as exc:
                raise RuntimeError(f"Dash feed for {slug} is not a valid gzip/tar archive") from exc
        finally:
            tar_path.unlink(missing_ok=True)

        matches = list(target_dir.glob("*.docset"))
        if not matches:
            raise RuntimeError(f"No .docset found after extracting {slug}")
        return matches[0]

    async def fetch(self, language: LanguageCatalog, mode: CrawlMode) -> AsyncIterator[Document]:
        docset_path = await self._download_docset(language.slug)
        dsidx = docset_path / "Contents" / "Resources" / "docSet.dsidx"
        docs_root = docset_path / "Contents" / "Resources" / "Documents"

        if not dsidx.exists():
            raise RuntimeError(f"Missing docSet.dsidx for {language.slug}")

        core = {t.lower() for t in (language.core_topics or [])} or {t.lower() for t in CORE_TYPES}

        connection = sqlite3.connect(dsidx)
        try:
            rows = connection.execute("SELECT name, type, path FROM searchIndex ORDER BY type, name").fetchall()
        finally:
            connection.close()

        seen_paths: set[str] = set()
        for order, (name, entry_type, path) in enumerate(rows):
            if not path or not entry_type:
                continue
            entry_type = str(entry_type)
            if mode == "important" and entry_type.lower() not in core:
                continue

            doc_key = path.split("#", 1)[0]
            if doc_key in seen_paths:
                continue
            seen_paths.add(doc_key)

            html_file = docs_root / doc_key
            if not html_file.exists():
                continue

            html = await asyncio.to_thread(html_file.read_text, "utf-8", "ignore")
            markdown = await asyncio.to_thread(_convert_html, html)
            if not markdown.strip():
                continue

            yield Document(
                topic=entry_type,
                slug=_slug(doc_key),
                title=str(name),
                markdown=markdown,
                source_url=f"dash://{language.slug}/{doc_key}",
                order_hint=order,
            )


def _convert_html(html: str) -> str:
    return html_to_md(html, heading_style="ATX", strip=["script", "style"])


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")
    return cleaned.lower() or "index"


_DEFAULT_DASH_SEED: list[dict] = [
    {"slug": "Swift", "display_name": "Swift"},
    {"slug": "Kotlin", "display_name": "Kotlin"},
    {"slug": "Elixir", "display_name": "Elixir"},
    {"slug": "Erlang", "display_name": "Erlang"},
    {"slug": "Julia", "display_name": "Julia"},
    {"slug": "Haskell", "display_name": "Haskell"},
    {"slug": "OCaml", "display_name": "OCaml"},
    {"slug": "Scala", "display_name": "Scala"},
    {"slug": "Clojure", "display_name": "Clojure"},
    {"slug": "Dart", "display_name": "Dart"},
    {"slug": "Groovy", "display_name": "Groovy"},
    {"slug": "Lua", "display_name": "Lua"},
    {"slug": "Perl", "display_name": "Perl"},
    {"slug": "R", "display_name": "R"},
    {"slug": "Crystal", "display_name": "Crystal"},
    {"slug": "Nim", "display_name": "Nim"},
    {"slug": "Raku", "display_name": "Raku"},
    {"slug": "FSharp", "display_name": "F#"},
    {"slug": "Racket", "display_name": "Racket"},
    {"slug": "Common_Lisp", "display_name": "Common Lisp"},
    {"slug": "Fortran", "display_name": "Fortran"},
    {"slug": "Zig", "display_name": "Zig"},
]
