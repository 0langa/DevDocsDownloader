from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from doc_ingest.sources.base import LanguageCatalog, SourceError
from doc_ingest.sources.dash import DashFeedSource
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.sources.web_page import WebPageSource


class DummyResponse:
    def __init__(self, *, json_payload=None, text: str = "", content: bytes | None = None) -> None:
        self._json_payload = json_payload
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers: dict[str, str] = {}

    def json(self):
        return self._json_payload


class DummyRuntime:
    def __init__(self, request_impl=None) -> None:
        self.cache_policy = "use-if-present"
        self.cache_ttl_hours = None
        self.cache_root = None
        self.max_cache_size_bytes = None
        self._request_impl = request_impl

    def record_cache_decision(self, decision) -> None:  # pragma: no cover - noop
        _ = decision

    async def request(self, method: str, url: str, profile: str = "default", **kwargs):
        if self._request_impl is None:
            raise AssertionError("unexpected request")
        return await self._request_impl(method, url, profile, **kwargs)

    async def stream_to_file(self, url: str, target: Path, profile: str = "download") -> None:
        raise AssertionError("unexpected stream_to_file")


def _http_404(url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("missing", request=request, response=response)


def test_devdocs_adapter_maps_http_404_to_not_found(tmp_path: Path) -> None:
    async def request_impl(method: str, url: str, profile: str, **kwargs):
        raise _http_404(url)

    source = DevDocsSource(
        cache_dir=tmp_path, core_topics_path=tmp_path / "core.json", runtime=DummyRuntime(request_impl)
    )

    with pytest.raises(SourceError) as excinfo:
        asyncio.run(
            source.preview(LanguageCatalog(source="devdocs", slug="python", display_name="Python"), "important")
        )

    assert excinfo.value.code == "not_found"


def test_devdocs_adapter_rejects_corrupt_catalog_json(tmp_path: Path) -> None:
    async def request_impl(method: str, url: str, profile: str, **kwargs):
        return DummyResponse(json_payload={"unexpected": True})

    source = DevDocsSource(
        cache_dir=tmp_path, core_topics_path=tmp_path / "core.json", runtime=DummyRuntime(request_impl)
    )

    with pytest.raises(SourceError) as excinfo:
        asyncio.run(source.list_languages(force_refresh=True))

    assert excinfo.value.code == "invalid_format"


def test_dash_adapter_rejects_empty_entry_lists(tmp_path: Path) -> None:
    async def request_impl(method: str, url: str, profile: str, **kwargs):
        return DummyResponse(text="<html><body><p>no docsets here</p></body></html>")

    source = DashFeedSource(cache_dir=tmp_path, runtime=DummyRuntime(request_impl))

    with pytest.raises(SourceError) as excinfo:
        asyncio.run(source.list_languages(force_refresh=True))

    assert excinfo.value.code == "invalid_format"


def test_dash_adapter_skips_empty_doc_key_blocks(tmp_path: Path) -> None:
    docset_root = tmp_path / "dash" / "python" / "Python.docset" / "Contents" / "Resources"
    docs_root = docset_root / "Documents"
    docs_root.mkdir(parents=True, exist_ok=True)
    db_path = docset_root / "docSet.dsidx"
    (tmp_path / "dash" / "python" / "_docset.tgz").write_bytes(b"marker")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT)")
        connection.execute("INSERT INTO searchIndex(name, type, path) VALUES ('Bad', 'Guide', '')")
        connection.commit()
    finally:
        connection.close()

    source = DashFeedSource(cache_dir=tmp_path, runtime=DummyRuntime())
    language = LanguageCatalog(source="dash", slug="python", display_name="Python", core_topics=["Guide"])

    documents = list(asyncio.run(_collect(source.fetch(language, "important"))))
    assert documents == []


def test_mdn_adapter_requires_area_metadata(tmp_path: Path) -> None:
    source = MdnContentSource(cache_dir=tmp_path, runtime=DummyRuntime())
    language = LanguageCatalog(source="mdn", slug="javascript", display_name="JavaScript")

    with pytest.raises(SourceError) as excinfo:
        asyncio.run(_collect(source.fetch(language, "important")))

    assert excinfo.value.code == "invalid_format"


async def _collect(iterator) -> list:
    items = []
    async for item in iterator:
        items.append(item)
    return items


def test_web_page_source_discovers_seed_and_emits_documents(tmp_path: Path) -> None:
    source = WebPageSource(cache_dir=tmp_path, runtime=DummyRuntime())
    source.seed_path.write_text(
        '[{"slug":"manual","display_name":"Manual","doc_url":"https://example.org/manual","content_selector":"body","section_selector":"h2"}]',
        encoding="utf-8",
    )

    async def request_impl(method: str, url: str, profile: str, **kwargs):
        _ = (method, profile, kwargs)
        return DummyResponse(text="<html><body><h2>Intro</h2><p>Hello</p><h2>Next</h2><p>World</p></body></html>")

    source.runtime = DummyRuntime(request_impl)
    catalogs = asyncio.run(source.list_languages(force_refresh=True))
    assert catalogs[0].slug == "manual"
    docs = asyncio.run(_collect(source.fetch(catalogs[0], "important")))
    assert len(docs) >= 2
    assert docs[0].title in {"Intro", "Next"}
