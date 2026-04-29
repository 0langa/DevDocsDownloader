from __future__ import annotations

import asyncio
import sqlite3
import tarfile
from io import BytesIO

import httpx

from doc_ingest.live_probe import (
    _probe_dash_extraction,
    _select_dash_acceptance_entry,
)
from doc_ingest.sources.base import LanguageCatalog
from doc_ingest.sources.dash import CHEATSHEETS_URL, FEED_BASE


def test_select_dash_acceptance_entry_prefers_smallest_bounded_archive() -> None:
    entries = [
        LanguageCatalog(source="dash", slug="Large", display_name="Large"),
        LanguageCatalog(source="dash", slug="Small", display_name="Small"),
        LanguageCatalog(source="dash", slug="Unknown", display_name="Unknown"),
    ]

    async def run() -> LanguageCatalog | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD" and str(request.url) == f"{FEED_BASE}/Large.tgz":
                return httpx.Response(200, headers={"Content-Length": "9000000"})
            if request.method == "HEAD" and str(request.url) == f"{FEED_BASE}/Small.tgz":
                return httpx.Response(200, headers={"Content-Length": "2000000"})
            return httpx.Response(405)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _select_dash_acceptance_entry(
                client,
                entries=entries,
                max_archive_bytes=5_000_000,
                candidate_limit=3,
            )

    chosen = asyncio.run(run())
    assert chosen is not None
    assert chosen.slug == "Small"


def test_probe_dash_extraction_validates_real_docset_archive() -> None:
    tar_bytes = _dash_docset_archive()
    html = """
    <html><body>
      <a href="/cheat_sheets/Swift.docset/Contents/Resources/Documents/index">Swift</a>
    </body></html>
    """

    async def run():
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and str(request.url) == CHEATSHEETS_URL:
                return httpx.Response(200, text=html)
            if request.method == "HEAD" and str(request.url) == f"{FEED_BASE}/Swift.tgz":
                return httpx.Response(200, headers={"Content-Length": str(len(tar_bytes))})
            if request.method == "GET" and str(request.url) == f"{FEED_BASE}/Swift.tgz":
                return httpx.Response(200, content=tar_bytes)
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _probe_dash_extraction(client)

    result = asyncio.run(run())

    assert result.ok is True
    assert result.source == "dash"
    assert result.source_slug == "Swift"
    assert "docset extracted" in result.message
    assert "sqlite ok" in result.message


def _dash_docset_archive() -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        root = "Swift.docset/Contents/Resources/"
        _add_dir(archive, "Swift.docset/")
        _add_dir(archive, "Swift.docset/Contents/")
        _add_dir(archive, root)
        _add_dir(archive, root + "Documents/")
        _add_bytes(
            archive,
            root + "Documents/module.html",
            b"<main><h1>Module</h1><p>Body</p><pre><code>print(1)</code></pre></main>",
        )
        _add_bytes(archive, root + "docSet.dsidx", _dash_sqlite_bytes())
    return buffer.getvalue()


def _dash_sqlite_bytes() -> bytes:
    # sqlite3 needs a real file path, so create a temporary file through NamedTemporaryFile semantics.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "docSet.dsidx"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE searchIndex(name TEXT, type TEXT, path TEXT)")
            connection.execute(
                "INSERT INTO searchIndex(name, type, path) VALUES (?, ?, ?)",
                ("Module", "Reference", "module.html"),
            )
            connection.commit()
        finally:
            connection.close()
        return db_path.read_bytes()


def _add_dir(archive: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    archive.addfile(info)


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, BytesIO(payload))
