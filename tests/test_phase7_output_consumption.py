from __future__ import annotations

import asyncio
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import yaml

from doc_ingest.cache import decide_cache_refresh, read_cache_metadata, write_cache_metadata
from doc_ingest.compiler import LanguageOutputBuilder, render_compilation, write_streamed_compilation
from doc_ingest.config import load_config
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.runtime import SourceRuntime
from doc_ingest.services import DocumentationService, RunLanguageRequest
from doc_ingest.sources.base import Document, LanguageCatalog
from doc_ingest.sources.dash import DashFeedSource
from doc_ingest.sources.devdocs import DevDocsSource
from doc_ingest.utils.filesystem import read_json, write_json
from doc_ingest.utils.text import slugify

from .helpers import FixtureSource, long_markdown


def test_consolidated_anchors_are_unique_and_match_toc(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="Anchor Lang",
        language_slug=slugify("Anchor Lang"),
        source="fixture",
        source_slug="anchor-lang",
        source_url="https://example.invalid/anchor",
        mode="full",
        output_root=tmp_path,
    )
    builder.add(Document(topic="Reference", slug="alpha", title="Repeat", markdown=long_markdown("Repeat")))
    builder.add(Document(topic="Guides", slug="beta", title="Repeat", markdown=long_markdown("Repeat")))

    plan = builder.build_plan()
    rendered = render_compilation(plan)
    consolidated = rendered.files[tmp_path / "anchor-lang" / "anchor-lang.md"]

    assert "- [Reference](#reference)" in consolidated
    assert "  - [Repeat](#repeat)" in consolidated
    assert "- [Guides](#guides)" in consolidated
    assert "  - [Repeat](#repeat-2)" in consolidated
    assert '<a id="repeat"></a>' in consolidated
    assert '<a id="repeat-2"></a>' in consolidated

    write_streamed_compilation(plan)
    streamed = (tmp_path / "anchor-lang" / "anchor-lang.md").read_text(encoding="utf-8")
    assert '<a id="repeat"></a>' in streamed
    assert '<a id="repeat-2"></a>' in streamed


def test_optional_document_frontmatter_keeps_existing_metadata_lines(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    config.emit_document_frontmatter = True
    catalog = LanguageCatalog(source="fixture", slug="frontmatter-lang", display_name="Frontmatter Lang")
    source = FixtureSource(
        "fixture",
        catalog,
        [
            Document(
                topic="Reference",
                slug="alpha",
                title="Alpha",
                markdown=long_markdown("Alpha"),
                source_url="https://example.invalid/alpha",
                order_hint=7,
            )
        ],
    )
    report = asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    doc_path = config.paths.markdown_dir / "frontmatter-lang" / "reference" / "alpha.md"
    text = doc_path.read_text(encoding="utf-8")
    assert report.failures == []
    assert text.startswith("---\n")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["language"] == "Frontmatter Lang"
    assert frontmatter["language_slug"] == "frontmatter-lang"
    assert frontmatter["source"] == "fixture"
    assert frontmatter["topic"] == "Reference"
    assert frontmatter["order_hint"] == 7
    assert "_Language: Frontmatter Lang · Topic: Reference_" in text
    meta = read_json(config.paths.markdown_dir / "frontmatter-lang" / "_meta.json", {})
    assert meta["outputs"]["document_frontmatter"] is True


def test_optional_chunk_export_writes_jsonl_manifest_and_stable_files(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    config.emit_chunks = True
    config.chunk_max_chars = 700
    config.chunk_overlap_chars = 50
    catalog = LanguageCatalog(source="fixture", slug="chunk-lang", display_name="Chunk Lang")
    source = FixtureSource(
        "fixture",
        catalog,
        [Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha", repeat=30))],
    )

    report = asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    chunks_dir = config.paths.markdown_dir / "chunk-lang" / "chunks"
    manifest = chunks_dir / "manifest.jsonl"
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert report.failures == []
    assert records
    assert records[0]["chunk_id"] == "chunk-lang:reference:alpha:0000"
    assert records[0]["text_path"].startswith("chunks/reference-alpha-")
    assert records[0]["document_title"] == "Alpha"
    assert (config.paths.markdown_dir / "chunk-lang" / records[0]["text_path"]).exists()
    assert len((config.paths.markdown_dir / "chunk-lang" / records[0]["text_path"]).read_text(encoding="utf-8")) <= 701
    meta = read_json(config.paths.markdown_dir / "chunk-lang" / "_meta.json", {})
    assert meta["outputs"]["chunks"]["chunk_count"] == len(records)


def test_default_run_does_not_create_optional_chunks_or_frontmatter(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="fixture", slug="default-lang", display_name="Default Lang")
    source = FixtureSource(
        "fixture",
        catalog,
        [Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha"))],
    )

    asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    language_dir = config.paths.markdown_dir / "default-lang"
    assert not (language_dir / "chunks").exists()
    assert not (language_dir / "reference" / "alpha.md").read_text(encoding="utf-8").startswith("---\n")
    assert "outputs" not in read_json(language_dir / "_meta.json", {})


def test_cache_policy_ttl_and_force_refresh_decisions(tmp_path: Path) -> None:
    cached = tmp_path / "catalog.json"
    cached.write_text("{}", encoding="utf-8")
    write_cache_metadata(cached, source="devdocs", cache_key="catalog", policy="ttl")
    metadata = read_cache_metadata(cached)
    assert metadata is not None
    metadata.fetched_at = datetime.now(UTC) - timedelta(hours=3)
    write_json(cached.with_name("catalog.json.meta.json"), metadata.model_dump(mode="json"))

    expired = decide_cache_refresh(
        cached,
        source="devdocs",
        cache_key="catalog",
        policy="ttl",
        ttl_hours=1,
    )
    fresh = decide_cache_refresh(
        cached,
        source="devdocs",
        cache_key="catalog",
        policy="ttl",
        ttl_hours=24,
    )
    forced = decide_cache_refresh(
        cached,
        source="devdocs",
        cache_key="catalog",
        policy="use-if-present",
        force_refresh=True,
    )

    assert expired.should_refresh is True
    assert expired.reason == "ttl_expired"
    assert fresh.should_refresh is False
    assert forced.should_refresh is True


def test_devdocs_cache_policy_always_refreshes_valid_cached_dataset(tmp_path: Path) -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=b'{"fresh":"yes"}')

    runtime = SourceRuntime(cache_policy="always-refresh")
    runtime._clients["default"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = DevDocsSource(cache_dir=tmp_path, core_topics_path=tmp_path / "missing.json", runtime=runtime)
    dataset = tmp_path / "devdocs" / "python"
    dataset.mkdir(parents=True)
    index_path = dataset / "index.json"
    index_path.write_text('{"old":"yes"}', encoding="utf-8")

    async def run() -> None:
        try:
            await source._ensure_json_dataset("python", index_path, "index.json")
        finally:
            await runtime.close()

    asyncio.run(run())

    assert requests == ["https://documents.devdocs.io/python/index.json"]
    assert read_cache_metadata(index_path) is not None
    assert json.loads(index_path.read_text(encoding="utf-8")) == {"fresh": "yes"}


def test_dash_docset_download_records_cache_metadata(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("Swift.docset/")
        member.type = tarfile.DIRTYPE
        archive.addfile(member)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=buffer.getvalue(), headers={"ETag": '"dash-test"'})

    runtime = SourceRuntime(cache_policy="always-refresh")
    runtime._clients["dash"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = DashFeedSource(cache_dir=tmp_path, runtime=runtime)

    async def run() -> Path:
        try:
            return await source._download_docset("Swift")
        finally:
            await runtime.close()

    docset = asyncio.run(run())
    metadata = read_cache_metadata(tmp_path / "dash" / "Swift" / "_docset.tgz")

    assert docset.name == "Swift.docset"
    assert metadata is not None
    assert metadata.source == "dash"
    assert metadata.cache_key == "Swift/docset"
    assert metadata.etag == '"dash-test"'
    assert metadata.byte_count == len(buffer.getvalue())


def test_service_layer_returns_typed_summary_for_gui_consumers(tmp_path: Path, monkeypatch) -> None:
    config = load_config(root=tmp_path)
    captured = {}

    async def fake_run(self, **kwargs):
        captured.update(kwargs)
        from doc_ingest.models import RunSummary

        return RunSummary()

    monkeypatch.setattr("doc_ingest.pipeline.DocumentationPipeline.run", fake_run)
    service = DocumentationService(config)
    summary = asyncio.run(
        service.run_language(
            RunLanguageRequest(
                language="Python",
                emit_document_frontmatter=True,
                emit_chunks=True,
                cache_policy="ttl",
                cache_ttl_hours=12,
            )
        )
    )

    assert summary.reports == []
    assert captured["language_name"] == "Python"
    assert config.emit_document_frontmatter is True
    assert config.emit_chunks is True
    assert config.cache_policy == "ttl"
    assert config.cache_ttl_hours == 12
