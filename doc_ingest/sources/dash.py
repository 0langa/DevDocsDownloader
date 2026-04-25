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

from markdownify import markdownify as html_to_md

from ..models import SourceRunDiagnostics
from ..runtime import SourceRuntime
from ..utils.archive import safe_extract_tar
from ..utils.filesystem import write_json
from .base import AdapterEvent, CrawlMode, Document, LanguageCatalog, document_events

LOGGER = logging.getLogger("doc_ingest.sources.dash")

USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0)"
FEED_BASE = "https://kapeli.com/feeds"


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
        self._catalog_seed = catalog_seed
        self.runtime = runtime or SourceRuntime(user_agent=USER_AGENT)

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

        write_json(self.catalog_path, {"entries": entries})
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
        resp = await self.runtime.request("GET", tarball_url, profile="dash")
        resp.raise_for_status()
        tar_bytes = resp.content

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgz") as handle:
            handle.write(tar_bytes)
            tar_path = Path(handle.name)

        try:
            try:
                with tarfile.open(tar_path, "r:gz") as archive:
                    safe_extract_tar(archive, target_dir)
            except tarfile.TarError as exc:
                raise RuntimeError(f"Dash feed for {slug} is not a valid gzip/tar archive") from exc
        finally:
            tar_path.unlink(missing_ok=True)

        matches = list(target_dir.glob("*.docset"))
        if not matches:
            raise RuntimeError(f"No .docset found after extracting {slug}")
        return matches[0]

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[Document]:
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
        if diagnostics is not None:
            diagnostics.discovered += len(rows)

        seen_paths: set[str] = set()
        for order, (name, entry_type, path) in enumerate(rows):
            if not path or not entry_type:
                if diagnostics is not None:
                    diagnostics.skip("missing_path_or_type")
                continue
            entry_type = str(entry_type)
            if mode == "important" and entry_type.lower() not in core:
                if diagnostics is not None:
                    diagnostics.skip("filtered_mode")
                continue

            doc_key = path.split("#", 1)[0]
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
                title=str(name),
                markdown=markdown,
                source_url=f"dash://{language.slug}/{doc_key}",
                order_hint=order,
            )

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics))


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
