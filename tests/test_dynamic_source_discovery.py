from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import httpx

from doc_ingest.sources.base import LanguageCatalog
from doc_ingest.sources.dash import CHEATSHEETS_URL, DashFeedSource
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.sources.registry import SourceRegistry


def test_mdn_list_languages_discovers_supported_families_and_cached_fallback(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in {
            "content-main/files/en-us/web/html/index.md": "---\ntitle: HTML\nslug: Web/HTML\npage-type: landing-page\n---\nBody",
            "content-main/files/en-us/web/api/index.md": "---\ntitle: Web APIs\nslug: Web/API\npage-type: landing-page\n---\nBody",
            "content-main/files/en-us/web/svg/index.md": "---\ntitle: SVG\nslug: Web/SVG\npage-type: landing-page\n---\nBody",
        }.items():
            data = payload.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    source.archive_path.parent.mkdir(parents=True, exist_ok=True)
    source.archive_path.write_bytes(buffer.getvalue())

    async def fake_sha() -> str:
        return "sha-html"

    monkeypatch.setattr(source, "_latest_commit_sha", fake_sha)
    entries = asyncio.run(source.list_languages(force_refresh=True))

    by_slug = {entry.slug: entry for entry in entries}
    assert "html" in by_slug
    assert "web-apis" in by_slug
    assert "svg" in by_slug
    assert by_slug["html"].support_level == "supported"
    assert by_slug["web-apis"].aliases[0] == "web-apis"
    assert by_slug["svg"].support_level == "experimental"

    async def fail_ensure(*, area: str | None = None, force_refresh: bool = False):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(source, "_ensure_archive_index", fail_ensure)
    fallback_entries = asyncio.run(source.list_languages(force_refresh=True))
    assert {entry.slug for entry in fallback_entries} >= {"html", "web-apis"}


def test_dash_list_languages_discovers_from_live_index_and_cached_fallback(tmp_path: Path) -> None:
    source = DashFeedSource(cache_dir=tmp_path)
    html = """
    <html><body>
      <a href="/cheat_sheets/Swift.docset/Contents/Resources/Documents/index">Swift</a>
      <a href="/cheat_sheets/FSharp.docset/Contents/Resources/Documents/index">F#</a>
    </body></html>
    """

    async def first_request(*_args, **_kwargs) -> httpx.Response:
        return httpx.Response(200, text=html, request=httpx.Request("GET", CHEATSHEETS_URL))

    source.runtime.request = first_request  # type: ignore[method-assign]
    entries = asyncio.run(source.list_languages(force_refresh=True))

    by_slug = {entry.slug: entry for entry in entries}
    assert by_slug["Swift"].display_name == "Swift"
    assert by_slug["FSharp"].display_name == "F#"
    assert by_slug["FSharp"].discovery_metadata["feed_url"].endswith("/FSharp.tgz")

    async def failing_request(*_args, **_kwargs) -> httpx.Response:
        raise httpx.ConnectError("offline")

    source.runtime.request = failing_request  # type: ignore[method-assign]
    fallback_entries = asyncio.run(source.list_languages(force_refresh=True))
    assert {entry.slug for entry in fallback_entries} == {"Swift", "FSharp"}


def test_registry_resolves_aliases_from_dynamic_catalog_metadata(tmp_path: Path) -> None:
    registry = SourceRegistry(cache_dir=tmp_path)
    registry.sources = [
        _StaticSource(
            "mdn",
            [
                LanguageCatalog(
                    source="mdn",
                    slug="web-apis",
                    display_name="Web APIs",
                    aliases=["api", "web api"],
                )
            ],
        )
    ]

    source, catalog = asyncio.run(registry.resolve("api"))
    assert source.name == "mdn"
    assert catalog.slug == "web-apis"


class _StaticSource:
    def __init__(self, name: str, entries: list[LanguageCatalog]) -> None:
        self.name = name
        self._entries = entries

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return self._entries


def test_devdocs_fragment_references_are_preserved_in_canonical_document(tmp_path: Path) -> None:
    source = DevDocsSource(cache_dir=tmp_path, core_topics_path=tmp_path / "missing.json")
    dataset = tmp_path / "devdocs" / "python"
    dataset.mkdir(parents=True)
    (dataset / "index.json").write_text(
        '{"entries": ['
        '{"name": "Module", "type": "Reference", "path": "module"},'
        '{"name": "alpha", "type": "Reference", "path": "module#alpha"},'
        '{"name": "beta", "type": "Reference", "path": "module#beta"}'
        "]}",
        encoding="utf-8",
    )
    (dataset / "db.json").write_text('{"module":"<main><h1>Module</h1><p>Body</p></main>"}', encoding="utf-8")
    catalog = LanguageCatalog(source="devdocs", slug="python", display_name="Python")

    async def collect() -> list[str]:
        return [doc.markdown async for doc in source.fetch(catalog, "full")]

    [markdown] = asyncio.run(collect())
    assert "Merged Upstream Fragment References" in markdown
    assert "#alpha" in markdown
    assert "#beta" in markdown


def test_dash_fragment_references_are_preserved_in_canonical_document(tmp_path: Path, monkeypatch) -> None:
    source = DashFeedSource(cache_dir=tmp_path)
    docset = tmp_path / "dash" / "Swift" / "Swift.docset"
    docs_root = docset / "Contents" / "Resources" / "Documents"
    docs_root.mkdir(parents=True)
    (docs_root / "module.html").write_text("<main><h1>Module</h1><p>Body</p></main>", encoding="utf-8")
    dsidx = docset / "Contents" / "Resources" / "docSet.dsidx"
    dsidx.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    connection = sqlite3.connect(dsidx)
    try:
        connection.execute("CREATE TABLE searchIndex(name TEXT, type TEXT, path TEXT)")
        connection.executemany(
            "INSERT INTO searchIndex(name, type, path) VALUES (?, ?, ?)",
            [("Module", "Reference", "module.html"), ("alpha", "Reference", "module.html#alpha")],
        )
        connection.commit()
    finally:
        connection.close()

    async def fake_download(_slug: str, *, force_refresh: bool = False) -> Path:
        return docset

    monkeypatch.setattr(source, "_download_docset", fake_download)
    catalog = LanguageCatalog(source="dash", slug="Swift", display_name="Swift")

    async def collect() -> list[str]:
        return [doc.markdown async for doc in source.fetch(catalog, "full")]

    [markdown] = asyncio.run(collect())
    assert "Merged Upstream Fragment References" in markdown
    assert "#alpha" in markdown
