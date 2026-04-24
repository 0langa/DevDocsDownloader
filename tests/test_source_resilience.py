from __future__ import annotations

import asyncio
import tarfile
from pathlib import Path

import pytest

from doc_ingest.compiler import LanguageOutputBuilder
from doc_ingest.config import load_config
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.dash import DashFeedSource
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.sources.base import Document
from doc_ingest.utils.text import slugify


def test_run_many_propagates_force_refresh(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    seen: list[bool] = []

    async def fake_run(self, **kwargs):
        seen.append(kwargs["force_refresh"])
        from doc_ingest.models import RunSummary

        return RunSummary()

    monkeypatch.setattr(DocumentationPipeline, "run", fake_run)

    asyncio.run(pipeline.run_many(language_names=["python", "rust"], force_refresh=True))
    assert seen == [True, True]


def test_devdocs_reloads_invalid_cached_json(tmp_path: Path) -> None:
    source = DevDocsSource(cache_dir=tmp_path, core_topics_path=tmp_path / "missing.json")
    dataset_dir = tmp_path / "devdocs" / "python~3.14"
    dataset_dir.mkdir(parents=True)
    bad = dataset_dir / "db.json"
    bad.write_text("not json", encoding="utf-8")

    assert source._is_valid_json_file(bad) is False


def test_mdn_find_content_root_handles_direct_layout(tmp_path: Path) -> None:
    root = tmp_path / "content"
    (root / "files" / "en-us" / "web" / "html").mkdir(parents=True)
    source = MdnContentSource(cache_dir=tmp_path)

    found = source._find_content_root(root)

    assert found == root
    assert source._has_expected_tree(root) is True


def test_mdn_extract_tarball_keeps_files_root(tmp_path: Path) -> None:
    archive = tmp_path / "mdn.tar.gz"
    source_root = tmp_path / "src"
    file_dir = source_root / "content-main" / "files" / "en-us" / "web" / "html"
    file_dir.mkdir(parents=True)
    (file_dir / "index.md").write_text("---\ntitle: HTML\npage-type: guide\nslug: Web/HTML\n---\nBody", encoding="utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source_root / "content-main", arcname="content-main")

    dest = tmp_path / "out"
    dest.mkdir()
    from doc_ingest.sources.mdn import _extract_tarball

    _extract_tarball(archive, dest)

    assert (dest / "content-main" / "files" / "en-us" / "web" / "html" / "index.md").exists()


def test_dash_invalid_archive_raises_runtime_error(tmp_path: Path) -> None:
    source = DashFeedSource(cache_dir=tmp_path)

    class FakeResponse:
        content = b"not gzip"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url: str) -> FakeResponse:
            return FakeResponse()

    source._client = lambda: FakeClient()  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="not a valid gzip/tar archive"):
        asyncio.run(source._download_docset("Raku"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("std::vector", "std-vector"),
        ("file.name", "file-name"),
        ("CON", "con-item"),
        ("aux", "aux-item"),
    ],
)
def test_slugify_returns_windows_safe_names(value: str, expected: str) -> None:
    assert slugify(value) == expected


def test_language_output_builder_writes_windows_safe_paths(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="C++",
        language_slug=slugify("C++"),
        source="devdocs",
        source_slug="cpp",
        source_url="https://example.invalid/cpp",
        mode="important",
        output_root=tmp_path,
    )

    builder.add(
        Document(
            topic="std::filesystem",
            slug="std::filesystem::path",
            title="std::filesystem::path",
            markdown="Path docs",
        )
    )
    builder.add(
        Document(
            topic="CON",
            slug="aux",
            title="AUX",
            markdown="Reserved name docs",
        )
    )

    result = builder.finalize()

    assert result.total_documents == 2
    assert (tmp_path / "c" / "std-filesystem" / "std-filesystem-path.md").exists()
    assert (tmp_path / "c" / "con-item" / "aux-item.md").exists()