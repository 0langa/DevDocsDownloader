from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.models import RunSummary, SourceRunDiagnostics, TopicStats
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.reporting import write_reports
from doc_ingest.services import DocumentationService, RunLanguageRequest, ServiceEvent
from doc_ingest.sources.base import (
    AdapterEvent,
    Document,
    DocumentEvent,
    DocumentWarningEvent,
    LanguageCatalog,
    SourceStatsEvent,
)
from doc_ingest.utils.filesystem import read_json, write_text
from doc_ingest.validator import validate_output

from .helpers import long_markdown


def _consolidated(path: Path, body: str) -> Path:
    text = "\n".join(
        [
            "# Test Documentation",
            "",
            "## Metadata",
            "",
            "## Table of Contents",
            "",
            "- [Reference](#reference)",
            "  - [Alpha](#alpha)",
            "",
            "## Documentation",
            "",
            body,
            "",
            "x" * 2200,
        ]
    )
    write_text(path, text)
    return path


def test_validator_reports_missing_internal_anchor(tmp_path: Path) -> None:
    output = _consolidated(
        tmp_path / "test.md",
        "\n".join(
            [
                '<a id="reference"></a>',
                "",
                "### Reference",
                "",
                "#### Alpha",
                "",
                "content",
            ]
        ),
    )

    result = validate_output(
        language="Test",
        output_path=output,
        total_documents=1,
        topics=[TopicStats(topic="Reference", document_count=1)],
    )

    assert any(issue.code == "missing_internal_anchor" for issue in result.issues)


def test_validator_reports_duplicate_sections_and_heading_mismatch(tmp_path: Path) -> None:
    output = _consolidated(
        tmp_path / "test.md",
        "\n".join(
            [
                '<a id="reference"></a>',
                "",
                "### Reference",
                "",
                "#### Alpha",
                "",
                "#### Alpha",
                "",
                "### Reference",
            ]
        ),
    )

    result = validate_output(
        language="Test",
        output_path=output,
        total_documents=1,
        topics=[TopicStats(topic="Reference", document_count=1)],
    )
    codes = {issue.code for issue in result.issues}

    assert "duplicate_topic_section" in codes
    assert "document_heading_count_mismatch" in codes
    assert "duplicate_document_heading" in codes


def test_validator_reports_source_inventory_mismatch(tmp_path: Path) -> None:
    output = _consolidated(
        tmp_path / "test.md",
        "\n".join(
            [
                '<a id="reference"></a>',
                "",
                "### Reference",
                "",
                '<a id="alpha"></a>',
                "",
                "#### Alpha",
            ]
        ),
    )
    diagnostics = SourceRunDiagnostics(discovered=5, emitted=1, skipped={})

    result = validate_output(
        language="Test",
        output_path=output,
        total_documents=1,
        topics=[TopicStats(topic="Reference", document_count=1)],
        source_diagnostics=diagnostics,
    )

    assert any(issue.code == "source_inventory_mismatch" for issue in result.issues)


def test_document_validation_jsonl_maps_issues_to_document_paths(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    language_dir = tmp_path / "markdown" / "doc-lang"
    doc_path = language_dir / "reference" / "alpha.md"
    write_text(language_dir / "reference" / "_section.md", "# Reference\n\n## Contents\n\n- [Alpha](alpha.md)\n")
    write_text(
        doc_path,
        "# Alpha\n\n_Language: Doc Lang · Topic: Reference_\n\nSee [relative](other.md).\n\n<div>leftover</div>\n",
    )
    output = _consolidated(
        language_dir / "doc-lang.md",
        "\n".join(['<a id="reference"></a>', "", "### Reference", "", '<a id="alpha"></a>', "", "#### Alpha"]),
    )
    validation = validate_output(
        language="Doc Lang",
        output_path=output,
        total_documents=1,
        topics=[TopicStats(topic="Reference", document_count=1)],
        source="fixture",
        source_slug="doc-lang",
    )

    summary = RunSummary(
        reports=[
            {
                "language": "Doc Lang",
                "slug": "doc-lang",
                "source": "fixture",
                "source_slug": "doc-lang",
                "output_path": output,
                "total_documents": 1,
                "topics": [TopicStats(topic="Reference", document_count=1)],
                "validation": validation,
            }
        ]
    )
    write_reports(summary, reports_dir)
    records = [json.loads(line) for line in (reports_dir / "validation_documents.jsonl").read_text().splitlines()]

    assert records[0]["document_path"].endswith("alpha.md")
    assert {issue["code"] for issue in records[0]["issues"]} >= {"relative_link", "html_leftover"}


def test_document_warning_event_persists_structured_records_and_report_text(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = LanguageCatalog(source="fixture", slug="warning-lang", display_name="Warning Lang")

    class WarningSource:
        name = "fixture"

        async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
            return [catalog]

        async def _events(self) -> AsyncIterator[AdapterEvent]:
            yield SourceStatsEvent(discovered=1)
            yield DocumentWarningEvent(
                code="fixture_doc_warning",
                message="recoverable document warning",
                source_url="https://example.invalid/alpha",
                topic="Reference",
                slug="alpha",
                title="Alpha",
                order_hint=1,
            )
            yield DocumentEvent(
                Document(
                    topic="Reference",
                    slug="alpha",
                    title="Alpha",
                    markdown=long_markdown("Alpha", repeat=10),
                    source_url="https://example.invalid/alpha",
                    order_hint=1,
                )
            )
            yield SourceStatsEvent(emitted=1)

        def events(self, language, mode, diagnostics=None, resume_boundary=None, force_refresh=False):
            return self._events()

    report = asyncio.run(
        pipeline._run_language(
            source=WarningSource(),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )
    write_reports(RunSummary(reports=[report]), config.paths.reports_dir)
    state = read_json(config.paths.state_dir / "warning-lang.json", {})
    report_md = (config.paths.reports_dir / "run_summary.md").read_text(encoding="utf-8")

    assert report.document_warnings[0].code == "fixture_doc_warning"
    assert state["document_warnings"][0]["slug"] == "alpha"
    assert "[fixture_doc_warning] Alpha: recoverable document warning" in report_md


def test_service_event_sink_receives_stable_summary_events(tmp_path: Path, monkeypatch) -> None:
    config = load_config(root=tmp_path)
    events: list[ServiceEvent] = []

    async def fake_run(self, **_kwargs):
        diagnostics = SourceRunDiagnostics(discovered=1, emitted=1, skipped={})
        output = _consolidated(
            tmp_path / "event.md",
            "\n".join(['<a id="reference"></a>', "", "### Reference", "", '<a id="alpha"></a>', "", "#### Alpha"]),
        )
        validation = validate_output(
            language="Event Lang",
            output_path=output,
            total_documents=1,
            topics=[TopicStats(topic="Reference", document_count=1)],
            source_diagnostics=diagnostics,
        )
        return RunSummary(
            reports=[
                {
                    "language": "Event Lang",
                    "slug": "event-lang",
                    "source": "fixture",
                    "source_slug": "event-lang",
                    "total_documents": 1,
                    "source_diagnostics": diagnostics,
                    "topics": [TopicStats(topic="Reference", document_count=1)],
                    "validation": validation,
                    "runtime_telemetry": {
                        "requests": 1,
                        "retries": 0,
                        "bytes_observed": 5,
                        "failures": 0,
                        "cache_hits": 1,
                        "cache_refreshes": 0,
                    },
                }
            ]
        )

    monkeypatch.setattr("doc_ingest.pipeline.DocumentationPipeline.run", fake_run)
    service = DocumentationService(config)

    asyncio.run(service.run_language(RunLanguageRequest(language="Event Lang"), event_sink=events.append))

    assert [event.event_type for event in events] == [
        "phase_change",
        "phase_change",
        "validation_completed",
        "runtime_telemetry",
        "phase_change",
    ]


def test_history_and_trend_reports_tolerate_corrupt_history(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    reports_dir = config.paths.reports_dir
    (reports_dir / "history").mkdir(parents=True)
    write_text(reports_dir / "history" / "0000-run_summary.json", "{not json")
    summary = RunSummary(
        reports=[
            {
                "language": "Trend Lang",
                "slug": "trend-lang",
                "source": "fixture",
                "source_slug": "trend-lang",
                "total_documents": 2,
                "duration_seconds": 1.5,
            }
        ]
    )

    write_reports(summary, reports_dir)
    trends = read_json(reports_dir / "trends.json", {})
    snapshot = DocumentationService(config).inspect_runtime()

    assert (reports_dir / "run_summary.json").exists()
    assert list((reports_dir / "history").glob("*-run_summary.json"))
    assert trends["corrupt_history_files"] == 1
    assert trends["languages"]["Trend Lang"]["latest_total_documents"] == 2
    assert reports_dir / "trends.json" in snapshot.trend_reports
