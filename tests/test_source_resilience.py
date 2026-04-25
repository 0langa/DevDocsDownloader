from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import pytest
import httpx

from doc_ingest.compiler import LanguageOutputBuilder
from doc_ingest.config import load_config
import doc_ingest.pipeline as pipeline_module
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.dash import DashFeedSource
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.sources.base import Document, LanguageCatalog
from doc_ingest.utils.filesystem import read_json, write_json, write_text
from doc_ingest.utils.http import RetryConfig, request_with_retries, stream_to_file_with_retries
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


def test_run_many_uses_explicit_language_concurrency(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    config.language_concurrency = 1
    pipeline = DocumentationPipeline(config)

    current = 0
    peak = 0

    async def fake_run(self, **kwargs):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        from doc_ingest.models import RunSummary

        return RunSummary()

    monkeypatch.setattr(DocumentationPipeline, "run", fake_run)

    asyncio.run(
        pipeline.run_many(
            language_names=["python", "rust", "go"],
            language_concurrency=2,
        )
    )

    assert peak == 2


def test_validate_only_uses_local_metadata_without_resolving_sources(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    language_dir = config.paths.markdown_dir / "python"
    output_path = language_dir / "python.md"
    body = "\n".join([
        "# Python Documentation",
        "",
        "## Metadata",
        "",
        "## Table of Contents",
        "",
        "## Documentation",
        "",
        "x" * 2500,
    ])
    write_text(output_path, body)
    write_json(
        language_dir / "_meta.json",
        {
            "language": "Python",
            "slug": "python",
            "source": "devdocs",
            "source_slug": "python~3.14",
            "source_url": "https://docs.python.org/3/",
            "mode": "important",
            "total_documents": 1,
            "topics": [{"topic": "Reference", "document_count": 1}],
        },
    )

    pipeline = DocumentationPipeline(config)

    async def fail_resolve(*_args, **_kwargs):
        raise AssertionError("validate-only should not resolve remote source catalogs")

    monkeypatch.setattr(pipeline.registry, "resolve", fail_resolve)

    summary = asyncio.run(pipeline.run(language_name="Python", validate_only=True))

    assert len(summary.reports) == 1
    report = summary.reports[0]
    assert report.output_path == output_path
    assert report.validation is not None
    assert report.validation.score == 1.0


def test_failed_language_run_keeps_checkpoint_with_last_document(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="fake", slug="fake-lang", display_name="Fake Lang")

    class FailingSource:
        name = "fake"

        async def list_languages(self, *, force_refresh: bool = False):
            return [catalog]

        async def fetch(self, language: LanguageCatalog, mode):
            yield Document(topic="Reference", slug="first", title="First", markdown="First", order_hint=3)
            yield Document(topic="Reference", slug="second", title="Second", markdown="Second", order_hint=7)
            raise RuntimeError("source interrupted")

    report = asyncio.run(
        pipeline._run_language(
            source=FailingSource(),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    checkpoint_path = config.paths.checkpoints_dir / "fake-lang.json"
    checkpoint = read_json(checkpoint_path, {})

    assert report.failures == ["RuntimeError: source interrupted"]
    assert checkpoint["phase"] == "failed"
    assert checkpoint["source_slug"] == "fake-lang"
    assert checkpoint["mode"] == "full"
    assert checkpoint["emitted_document_count"] == 2
    assert checkpoint["document_inventory_position"] == 7
    assert checkpoint["last_document"]["title"] == "Second"
    assert checkpoint["failures"][0]["error_type"] == "RuntimeError"
    assert checkpoint["failures"][0]["emitted_document_count"] == 2


def test_successful_language_run_removes_active_checkpoint(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="fake", slug="fake-lang", display_name="Fake Lang")

    class SuccessfulSource:
        name = "fake"

        async def list_languages(self, *, force_refresh: bool = False):
            return [catalog]

        async def fetch(self, language: LanguageCatalog, mode):
            yield Document(topic="Reference", slug="first", title="First", markdown="First", order_hint=0)

    report = asyncio.run(
        pipeline._run_language(
            source=SuccessfulSource(),
            catalog=catalog,
            mode="important",
            progress_tracker=None,
            validate_only=False,
        )
    )

    checkpoint_path = config.paths.checkpoints_dir / "fake-lang.json"
    state_path = config.paths.state_dir / "fake-lang.json"

    assert not checkpoint_path.exists()
    assert state_path.exists()
    assert report.total_documents == 1


def test_finalize_failure_keeps_checkpoint_in_validating_phase(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="fake", slug="fake-lang", display_name="Fake Lang")

    class SuccessfulSource:
        name = "fake"

        async def list_languages(self, *, force_refresh: bool = False):
            return [catalog]

        async def fetch(self, language: LanguageCatalog, mode):
            yield Document(topic="Reference", slug="first", title="First", markdown="First", order_hint=0)

    def fail_validation(**_kwargs):
        raise RuntimeError("validation interrupted")

    monkeypatch.setattr(pipeline_module, "validate_output", fail_validation)

    report = asyncio.run(
        pipeline._run_language(
            source=SuccessfulSource(),
            catalog=catalog,
            mode="important",
            progress_tracker=None,
            validate_only=False,
        )
    )

    checkpoint = read_json(config.paths.checkpoints_dir / "fake-lang.json", {})

    assert report.failures == ["RuntimeError: validation interrupted"]
    assert checkpoint["phase"] == "failed"
    assert checkpoint["failures"][0]["phase"] == "validating"
    assert checkpoint["failures"][0]["emitted_document_count"] == 1


def test_topic_filters_record_diagnostics_and_persist_state(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="fake", slug="fake-lang", display_name="Fake Lang")

    class DiagnosticSource:
        name = "fake"

        async def list_languages(self, *, force_refresh: bool = False):
            return [catalog]

        async def fetch(self, language: LanguageCatalog, mode, diagnostics=None):
            documents = [
                Document(topic="Reference", slug="ref", title="Reference", markdown="Reference", order_hint=0),
                Document(topic="Guide", slug="guide", title="Guide", markdown="Guide", order_hint=1),
                Document(topic="Internal", slug="internal", title="Internal", markdown="Internal", order_hint=2),
            ]
            if diagnostics is not None:
                diagnostics.discovered += len(documents)
            for document in documents:
                if diagnostics is not None:
                    diagnostics.emitted += 1
                yield document

    report = asyncio.run(
        pipeline._run_language(
            source=DiagnosticSource(),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
            include_topics=["Reference", "Guide"],
            exclude_topics=["Guide"],
        )
    )

    state = read_json(config.paths.state_dir / "fake-lang.json", {})

    assert report.total_documents == 1
    assert [topic.topic for topic in report.topics] == ["Reference"]
    assert report.source_diagnostics is not None
    assert report.source_diagnostics.discovered == 3
    assert report.source_diagnostics.emitted == 3
    assert report.source_diagnostics.skipped["filtered_topic_exclude"] == 1
    assert report.source_diagnostics.skipped["filtered_topic_include"] == 1
    assert state["source_diagnostics"]["skipped"]["filtered_topic_exclude"] == 1


def test_devdocs_reloads_invalid_cached_json(tmp_path: Path) -> None:
    source = DevDocsSource(cache_dir=tmp_path, core_topics_path=tmp_path / "missing.json")
    dataset_dir = tmp_path / "devdocs" / "python~3.14"
    dataset_dir.mkdir(parents=True)
    bad = dataset_dir / "db.json"
    bad.write_text("not json", encoding="utf-8")

    assert source._is_valid_json_file(bad) is False


def test_request_with_retries_retries_transient_status() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await request_with_retries(
                client,
                "GET",
                "https://example.invalid/data.json",
                retry_config=RetryConfig(max_attempts=2, base_delay_seconds=0),
            )

    response = asyncio.run(run())

    assert attempts == 2
    assert response.status_code == 200


def test_stream_to_file_with_retries_retries_transient_status(tmp_path: Path) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"archive")

    target = tmp_path / "archive.tgz"

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await stream_to_file_with_retries(
                client,
                "https://example.invalid/archive.tgz",
                target,
                retry_config=RetryConfig(max_attempts=2, base_delay_seconds=0),
            )

    asyncio.run(run())

    assert attempts == 2
    assert target.read_bytes() == b"archive"
    assert not target.with_name(f"{target.name}.tmp").exists()


def test_stream_to_file_with_retries_does_not_retry_non_retryable_status(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await stream_to_file_with_retries(
                client,
                "https://example.invalid/missing.tgz",
                tmp_path / "missing.tgz",
                retry_config=RetryConfig(max_attempts=3, base_delay_seconds=0),
            )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())

    assert attempts == 1


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


def test_mdn_extract_tarball_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "mdn.tar.gz"
    payload = b"unsafe"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("../evil.txt")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))

    from doc_ingest.sources.mdn import _extract_tarball

    with pytest.raises(RuntimeError, match="Unsafe tar member path"):
        _extract_tarball(archive, tmp_path / "out")


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


def test_dash_docset_extract_rejects_path_traversal(tmp_path: Path) -> None:
    source = DashFeedSource(cache_dir=tmp_path)
    payload = b"unsafe"
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as tar:
        member = tarfile.TarInfo("../evil.txt")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))

    class FakeResponse:
        content = archive_buffer.getvalue()

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

    with pytest.raises(RuntimeError, match="Unsafe tar member path"):
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


def test_language_output_builder_deduplicates_after_slug_normalization(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="C++",
        language_slug=slugify("C++"),
        source="devdocs",
        source_slug="cpp",
        source_url="https://example.invalid/cpp",
        mode="important",
        output_root=tmp_path,
    )

    builder.add(Document(topic="Reference", slug="std::vector", title="Vector A", markdown="A"))
    builder.add(Document(topic="Reference", slug="std/vector", title="Vector B", markdown="B"))
    builder.add(Document(topic="Reference", slug="COM1", title="Reserved", markdown="C"))

    builder.finalize()

    assert (tmp_path / "c" / "reference" / "std-vector.md").exists()
    assert (tmp_path / "c" / "reference" / "std-vector-2.md").exists()
    assert (tmp_path / "c" / "reference" / "com1-item.md").exists()
