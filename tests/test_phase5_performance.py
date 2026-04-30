from __future__ import annotations

import asyncio
import io
import sys
import tarfile
import time
from pathlib import Path

import httpx

from doc_ingest.adaptive import AdaptiveBulkController, AdaptiveBulkPolicy
from doc_ingest.config import load_config
from doc_ingest.models import LanguageRunReport, ResumeBoundary
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.runtime import SourceRuntime, SourceRuntimePolicy
from doc_ingest.sources.base import Document, LanguageCatalog
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.sources.mdn import MdnContentSource
from doc_ingest.utils.filesystem import read_json, write_text

from .helpers import long_markdown


def _write_mdn_archive(target: Path, files: dict[str, str]) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            payload = text.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(buffer.getvalue())


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
    assert checkpoint["schema_version"] == 1
    assert checkpoint["emitted_documents"][0]["content_sha256"]
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


def test_missing_resume_fragment_rebuilds_from_durable_document(tmp_path: Path) -> None:
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
    assert source.seen_boundaries == [1]
    assert not any("replaying from the start" in warning for warning in report.warnings)


def test_missing_resume_document_still_falls_back_to_full_replay(tmp_path: Path) -> None:
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
    Path(checkpoint["emitted_documents"][0]["path"]).unlink()

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


def test_resume_hash_mismatch_rolls_back_to_last_verified_artifact(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="devdocs", slug="resume-lang", display_name="Resume Lang")
    pipeline = DocumentationPipeline(config)
    asyncio.run(
        pipeline._run_language(
            source=ResumeFixtureSource(catalog, _resume_docs(), fail_after=2),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )
    checkpoint = read_json(config.paths.checkpoints_dir / "resume-lang.json", {})
    Path(checkpoint["emitted_documents"][1]["path"]).write_text("# Beta\n\ncorrupted\n", encoding="utf-8")

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
    assert source.seen_boundaries == [1]
    assert any("content hash mismatch" in warning for warning in report.warnings)


def test_schema_mismatched_checkpoint_is_ignored_by_pipeline(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="devdocs", slug="resume-lang", display_name="Resume Lang")
    write_text(
        config.paths.checkpoints_dir / "resume-lang.json",
        '{"language":"Resume Lang","slug":"resume-lang","source":"devdocs","source_slug":"resume-lang","phase":"failed","document_inventory_position":2,"emitted_document_count":2,"emitted_documents":[]}',
    )
    pipeline = DocumentationPipeline(config)
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


def test_source_runtime_circuit_breaker_opens_after_repeated_failures() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"nope")

    runtime = SourceRuntime(policies={"default": SourceRuntimePolicy(max_concurrency=1, min_delay_seconds=0)})
    runtime._clients["default"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    breaker = runtime.breaker("https://example.invalid/a")
    breaker.backoff_seconds = 5

    async def run() -> None:
        try:
            for _ in range(3):
                try:
                    await runtime.request("GET", "https://example.invalid/a")
                except httpx.HTTPStatusError:
                    pass
            try:
                await runtime.request("GET", "https://example.invalid/a")
            except RuntimeError as exc:
                assert "Source circuit open" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("expected circuit breaker rejection")
        finally:
            await runtime.close()

    asyncio.run(run())
    assert runtime.telemetry.circuit_breaker_rejections == 1


def test_adaptive_controller_emergency_drops_to_one_on_memory_pressure(monkeypatch) -> None:
    class FakeMemory:
        percent = 92.0

    class FakePsutil:
        @staticmethod
        def virtual_memory():
            return FakeMemory()

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil())
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=4, max_concurrency=6))
    controller.observe(LanguageRunReport(language="Python", slug="python", source="fixture", source_slug="python"))

    assert controller.current_concurrency == 1
    assert any(reason.startswith("emergency_decrease:memory_pressure") for reason in controller.adjustment_reasons)


def test_mdn_commit_sha_skips_redundant_redownload(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    _write_mdn_archive(
        source.archive_path,
        {
            "content-main/files/en-us/web/html/index.md": "---\ntitle: HTML\nslug: Web/HTML\n---\nBody",
        },
    )
    from doc_ingest.cache import write_cache_metadata

    write_cache_metadata(
        source.archive_path,
        source="mdn",
        cache_key="content-archive",
        url="https://example.invalid/mdn.tar.gz",
        policy="ttl",
        mdn_commit_sha="sha-same",
    )

    async def fake_sha() -> str:
        return "sha-same"

    async def fake_stream(_url: str, target: Path, **_kwargs) -> None:
        raise AssertionError("matching commit SHA should skip download")

    monkeypatch.setattr(source, "_latest_commit_sha", fake_sha)
    source.runtime.stream_to_file = fake_stream  # type: ignore[method-assign]
    index = asyncio.run(source._ensure_archive_index(area="web/html"))

    assert "web/html" in index.ready_areas
    assert index.mdn_commit_sha == "sha-same"


def test_mdn_force_refresh_redownloads_archive_and_indexes_members(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    source.archive_path.parent.mkdir(parents=True)
    source.archive_path.write_bytes(b"old")

    async def fake_sha() -> str:
        return "sha-new"

    async def fake_stream(_url: str, target: Path, **_kwargs) -> None:
        _write_mdn_archive(
            target,
            {
                "content-main/files/en-us/web/html/index.md": "---\ntitle: HTML\nslug: Web/HTML\n---\nBody",
                "content-main/files/en-us/web/html/elements/a/index.md": "---\ntitle: A\nslug: Web/HTML/Element/a\npage-type: html-element\n---\nA body",
            },
        )

    monkeypatch.setattr(source, "_latest_commit_sha", fake_sha)
    source.runtime.stream_to_file = fake_stream  # type: ignore[method-assign]

    index = asyncio.run(source._ensure_archive_index(area="web/html", force_refresh=True))

    assert source.archive_path.read_bytes() != b"old"
    assert index.ready_areas["web/html"] == sorted(index.ready_areas["web/html"])
    assert any(member.endswith("/elements/a/index.md") for member in index.ready_areas["web/html"])


def test_mdn_fetch_reads_documents_on_demand_from_archive(tmp_path: Path, monkeypatch) -> None:
    source = MdnContentSource(cache_dir=tmp_path)
    _write_mdn_archive(
        source.archive_path,
        {
            "content-main/files/en-us/web/html/index.md": "---\ntitle: HTML\nslug: Web/HTML\npage-type: landing-page\n---\nRoot",
            "content-main/files/en-us/web/html/elements/a/index.md": "---\ntitle: Anchor\nslug: Web/HTML/Element/a\npage-type: html-element\n---\n[Link](/en-US/docs/Web/HTML)",
        },
    )

    async def fake_sha() -> str:
        return "sha-fetch"

    monkeypatch.setattr(source, "_latest_commit_sha", fake_sha)
    catalog = LanguageCatalog(
        source="mdn",
        slug="html",
        display_name="HTML",
        core_topics=["html-element"],
        discovery_metadata={"area": "web/html"},
    )

    async def collect() -> list[Document]:
        return [doc async for doc in source.fetch(catalog, "full")]

    docs = asyncio.run(collect())

    assert len(docs) == 2
    assert docs[1].title == "Anchor"
    assert "https://developer.mozilla.org/en-US/docs/Web/HTML" in docs[1].markdown
