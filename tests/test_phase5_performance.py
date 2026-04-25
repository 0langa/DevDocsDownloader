from __future__ import annotations

import asyncio
import io
import tarfile
import time
from pathlib import Path

import httpx

from doc_ingest.config import load_config
from doc_ingest.models import ResumeBoundary
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.runtime import SourceRuntime, SourceRuntimePolicy
from doc_ingest.sources.base import Document, LanguageCatalog
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.utils.filesystem import read_json, write_text

from .helpers import long_markdown


class ResumeFixtureSource:
    name = "devdocs"

    def __init__(self, catalog: LanguageCatalog, documents: list[Document], *, fail_after: int | None = None) -> None:
        self.catalog = catalog
        self.documents = documents
        self.fail_after = fail_after
        self.seen_boundaries: list[int | None] = []

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return [self.catalog]

    async def fetch(self, language, mode, diagnostics=None, resume_boundary=None, force_refresh=False):
        self.seen_boundaries.append(
            resume_boundary.document_inventory_position if resume_boundary is not None else None
        )
        selected = [
            doc
            for doc in self.documents
            if resume_boundary is None or doc.order_hint > resume_boundary.document_inventory_position
        ]
        if diagnostics is not None:
            diagnostics.discovered += len(self.documents)
            if resume_boundary is not None:
                diagnostics.skip("checkpoint_resume_skip", len(self.documents) - len(selected))
        for index, document in enumerate(selected, start=1):
            if diagnostics is not None:
                diagnostics.emitted += 1
            yield document
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("fixture interruption")


def _resume_docs() -> list[Document]:
    return [
        Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha"), order_hint=1),
        Document(topic="Reference", slug="beta", title="Beta", markdown=long_markdown("Beta"), order_hint=2),
        Document(topic="Guides", slug="gamma", title="Gamma", markdown=long_markdown("Gamma"), order_hint=3),
    ]


def test_failed_run_manifest_allows_complete_adapter_level_resume(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="devdocs", slug="resume-lang", display_name="Resume Lang")
    first_source = ResumeFixtureSource(catalog, _resume_docs(), fail_after=2)
    pipeline = DocumentationPipeline(config)

    first_report = asyncio.run(
        pipeline._run_language(
            source=first_source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )
    checkpoint = read_json(config.paths.checkpoints_dir / "resume-lang.json", {})
    assert first_report.failures == ["RuntimeError: fixture interruption"]
    assert checkpoint["emitted_document_count"] == 2
    assert len(checkpoint["emitted_documents"]) == 2
    assert Path(checkpoint["emitted_documents"][0]["fragment_path"]).exists()

    second_source = ResumeFixtureSource(catalog, _resume_docs())
    second_report = asyncio.run(
        pipeline._run_language(
            source=second_source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    output = (config.paths.markdown_dir / "resume-lang" / "resume-lang.md").read_text(encoding="utf-8")
    assert second_report.failures == []
    assert second_report.total_documents == 3
    assert second_source.seen_boundaries == [2]
    assert "#### Alpha" in output
    assert "#### Beta" in output
    assert "#### Gamma" in output
    assert not (config.paths.checkpoints_dir / "resume-lang.json").exists()


def test_missing_resume_artifact_falls_back_to_full_replay(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="devdocs", slug="resume-lang", display_name="Resume Lang")
    pipeline = DocumentationPipeline(config)
    asyncio.run(
        pipeline._run_language(
            source=ResumeFixtureSource(catalog, _resume_docs(), fail_after=1),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )
    checkpoint = read_json(config.paths.checkpoints_dir / "resume-lang.json", {})
    Path(checkpoint["emitted_documents"][0]["fragment_path"]).unlink()

    source = ResumeFixtureSource(catalog, _resume_docs())
    report = asyncio.run(
        pipeline._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    assert report.failures == []
    assert source.seen_boundaries == [None]
    assert any("replaying from the start" in warning for warning in report.warnings)


def test_devdocs_resume_boundary_skips_inventory_rows(tmp_path: Path) -> None:
    source = DevDocsSource(cache_dir=tmp_path, core_topics_path=tmp_path / "missing.json")
    dataset = tmp_path / "devdocs" / "python"
    dataset.mkdir(parents=True)
    (dataset / "index.json").write_text(
        '{"entries": ['
        '{"name": "A", "type": "Reference", "path": "a"},'
        '{"name": "B", "type": "Reference", "path": "b"},'
        '{"name": "C", "type": "Reference", "path": "c"}'
        "]}",
        encoding="utf-8",
    )
    (dataset / "db.json").write_text('{"a":"<p>A</p>","b":"<p>B</p>","c":"<p>C</p>"}', encoding="utf-8")
    catalog = LanguageCatalog(source="devdocs", slug="python", display_name="Python")

    async def collect() -> list[Document]:
        return [
            doc
            async for doc in source.fetch(
                catalog,
                "full",
                resume_boundary=ResumeBoundary(document_inventory_position=1, emitted_document_count=2),
            )
        ]

    docs = asyncio.run(collect())
    assert [doc.title for doc in docs] == ["C"]


def test_generated_markdown_balanced_durability_skips_fsync(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def fake_fsync(_fd: int) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr("doc_ingest.utils.filesystem.os.fsync", fake_fsync)
    write_text(tmp_path / "balanced.md", "x", durability="balanced")
    write_text(tmp_path / "strict.json", "{}", durability="strict")

    assert calls == 1
    assert not (tmp_path / "balanced.md.tmp").exists()


def test_source_runtime_policy_limits_concurrency() -> None:
    current = 0
    peak = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return httpx.Response(200, content=b"ok")

    runtime = SourceRuntime(policies={"default": SourceRuntimePolicy(max_concurrency=1, min_delay_seconds=0)})
    runtime._clients["default"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> None:
        try:
            await asyncio.gather(
                runtime.request("GET", "https://example.invalid/a"),
                runtime.request("GET", "https://example.invalid/b"),
                runtime.request("GET", "https://example.invalid/c"),
            )
        finally:
            await runtime.close()

    asyncio.run(run())
    assert peak == 1


def test_source_runtime_policy_applies_minimum_delay_between_starts() -> None:
    runtime = SourceRuntime(policies={"default": SourceRuntimePolicy(max_concurrency=2, min_delay_seconds=0.03)})
    runtime._clients["default"] = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok"))
    )

    async def run() -> float:
        started = time.perf_counter()
        try:
            await asyncio.gather(
                runtime.request("GET", "https://example.invalid/a"),
                runtime.request("GET", "https://example.invalid/b"),
            )
        finally:
            await runtime.close()
        return time.perf_counter() - started

    elapsed = asyncio.run(run())
    assert elapsed >= 0.025


def test_mdn_metadata_skips_reextract_when_archive_and_area_are_ready(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    archive = source.archive_path
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")
    area_dir = source.extracted_root / "content-main" / "files" / "en-us" / "web" / "html"
    area_dir.mkdir(parents=True)
    source._write_cache_metadata()

    def fail_extract(*_args, **_kwargs) -> None:
        raise AssertionError("valid MDN metadata should skip extraction")

    monkeypatch.setattr("doc_ingest.sources.mdn._extract_tarball", fail_extract)
    root = asyncio.run(source._ensure_content(area="web/html"))

    assert root == source.extracted_root


def test_mdn_changed_checksum_triggers_reextract(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    source.archive_path.parent.mkdir(parents=True)
    source.archive_path.write_bytes(b"old")
    (source.extracted_root / "content-main" / "files" / "en-us" / "web" / "html").mkdir(parents=True)
    source._write_cache_metadata()
    source.archive_path.write_bytes(b"new")
    extracted = False

    def fake_extract(_archive: Path, dest: Path) -> None:
        nonlocal extracted
        extracted = True
        (dest / "content-main" / "files" / "en-us" / "web" / "html").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("doc_ingest.sources.mdn._extract_tarball", fake_extract)
    asyncio.run(source._ensure_content(area="web/html"))

    assert extracted is True


def test_mdn_force_refresh_redownloads_archive(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    source.archive_path.parent.mkdir(parents=True)
    source.archive_path.write_bytes(b"old")

    async def fake_stream(_url: str, target: Path, **_kwargs) -> None:
        target.write_bytes(b"new")

    def fake_extract(_archive: Path, dest: Path) -> None:
        (dest / "content-main" / "files" / "en-us" / "web" / "html").mkdir(parents=True, exist_ok=True)

    source.runtime.stream_to_file = fake_stream  # type: ignore[method-assign]
    monkeypatch.setattr("doc_ingest.sources.mdn._extract_tarball", fake_extract)

    asyncio.run(source._ensure_content(area="web/html", force_refresh=True))
    assert source.archive_path.read_bytes() == b"new"


def test_mdn_extract_still_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    payload = b"unsafe"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("../evil.txt")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))

    from doc_ingest.sources.mdn import _extract_tarball

    try:
        _extract_tarball(archive, tmp_path / "out")
    except RuntimeError as exc:
        assert "Unsafe tar member path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsafe tar member was not rejected")
