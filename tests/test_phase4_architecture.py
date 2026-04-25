from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from doc_ingest.compiler import LanguageOutputBuilder, render_compilation, write_streamed_compilation
from doc_ingest.config import load_config
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.base import (
    AdapterEvent,
    Document,
    DocumentEvent,
    LanguageCatalog,
    SkippedEvent,
    SourceStatsEvent,
    WarningEvent,
)
from doc_ingest.utils.filesystem import read_json
from doc_ingest.utils.text import slugify

from .helpers import long_markdown


def test_pipeline_owns_shared_source_runtime(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)

    assert pipeline.registry.runtime is pipeline.runtime
    assert all(source.runtime is pipeline.runtime for source in pipeline.registry.sources)
    assert pipeline.runtime.client("default") is pipeline.runtime.client("default")

    asyncio.run(pipeline.close())

    assert pipeline.runtime.closed is True


def test_event_stream_updates_report_state_and_diagnostics(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="event", slug="event-lang", display_name="Event Lang")

    class EventSource:
        name = "event"

        async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
            return [catalog]

        def events(self, language: LanguageCatalog, mode, diagnostics=None) -> AsyncIterator[AdapterEvent]:
            return self._events()

        async def _events(self) -> AsyncIterator[AdapterEvent]:
            yield SourceStatsEvent(discovered=3)
            yield WarningEvent(
                code="fixture_warning", message="recoverable source issue", source_url="https://example.invalid"
            )
            yield SkippedEvent(reason="fixture_skip")
            yield DocumentEvent(
                Document(
                    topic="Reference",
                    slug="event-doc",
                    title="Event Doc",
                    markdown=long_markdown("Event Doc", repeat=10),
                    order_hint=5,
                )
            )
            yield SourceStatsEvent(emitted=1)

    report = asyncio.run(
        pipeline._run_language(
            source=EventSource(),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    state = read_json(config.paths.state_dir / "event-lang.json", {})

    assert report.failures == []
    assert report.warnings == ["fixture_warning: recoverable source issue (https://example.invalid)"]
    assert report.source_diagnostics is not None
    assert report.source_diagnostics.discovered == 3
    assert report.source_diagnostics.emitted == 1
    assert report.source_diagnostics.skipped == {"fixture_skip": 1}
    assert state["source_diagnostics"]["skipped"] == {"fixture_skip": 1}


def test_compiler_plan_and_renderer_are_deterministic_without_writes(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="Plan Lang",
        language_slug=slugify("Plan Lang"),
        source="fixture",
        source_slug="plan-lang",
        source_url="https://example.invalid/plan",
        mode="full",
        output_root=tmp_path,
    )

    builder.add(Document(topic="Reference", slug="std::vector", title="Vector A", markdown=long_markdown("Vector A")))
    builder.add(Document(topic="Reference", slug="std/vector", title="Vector B", markdown=long_markdown("Vector B")))
    builder.add(Document(topic="Guides", slug="COM1", title="Guide", markdown=long_markdown("Guide")))

    plan = builder.build_plan()
    rendered = render_compilation(plan)

    assert [topic.name for topic in plan.topics] == ["Reference", "Guides"]
    assert [doc.document.slug for doc in plan.topics[0].documents] == ["std-vector", "std-vector-2"]
    assert [doc.document.slug for doc in plan.topics[1].documents] == ["com1-item"]
    assert rendered.output_path == tmp_path / "plan-lang" / "plan-lang.md"
    assert tmp_path / "plan-lang" / "index.md" in rendered.files
    assert tmp_path / "plan-lang" / "reference" / "std-vector.md" in rendered.files
    assert not (tmp_path / "plan-lang" / "index.md").exists()


def test_compiler_streams_documents_before_finalize_and_writes_from_fragments(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="Stream Lang",
        language_slug=slugify("Stream Lang"),
        source="fixture",
        source_slug="stream-lang",
        source_url="https://example.invalid/stream",
        mode="full",
        output_root=tmp_path,
    )

    builder.add(Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha")))
    per_doc_path = tmp_path / "stream-lang" / "reference" / "alpha.md"
    assert per_doc_path.exists()
    assert (tmp_path / "stream-lang" / "_fragments").exists()
    assert not (tmp_path / "stream-lang" / "stream-lang.md").exists()

    plan = builder.build_plan()
    assert plan.topics[0].documents[0].document is not None
    plan.topics[0].documents[0].document = None

    write_streamed_compilation(plan)

    consolidated = (tmp_path / "stream-lang" / "stream-lang.md").read_text(encoding="utf-8")
    assert "#### Alpha" in consolidated
    assert "print('fixture')" in consolidated
    assert not (tmp_path / "stream-lang" / "_fragments").exists()
