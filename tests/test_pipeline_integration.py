from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from doc_ingest.config import load_config
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.utils.filesystem import read_json

from .helpers import FixtureSource, contract_documents, synthetic_catalog


@pytest.mark.parametrize(
    ("source_name", "mode", "include_topics", "expected_docs", "expected_skips"),
    [
        ("devdocs", "important", None, 2, {"filtered_mode": 1}),
        ("mdn", "full", None, 3, {}),
        ("dash", "full", ["Reference"], 2, {"filtered_topic_include": 1}),
    ],
)
def test_pipeline_run_is_deterministic_without_live_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_name: str,
    mode: str,
    include_topics: list[str] | None,
    expected_docs: int,
    expected_skips: dict[str, int],
) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = synthetic_catalog(source=source_name)
    source = FixtureSource(source_name, catalog, contract_documents())

    async def resolve(language_name: str, source_name=None, force_refresh: bool = False):
        assert language_name == "Synthetic Lang"
        return source, catalog

    monkeypatch.setattr(pipeline.registry, "resolve", resolve)

    summary = asyncio.run(
        pipeline.run(
            language_name="Synthetic Lang",
            mode=mode,  # type: ignore[arg-type]
            include_topics=include_topics,
        )
    )

    assert len(summary.reports) == 1
    report = summary.reports[0]
    assert report.failures == []
    assert report.total_documents == expected_docs
    assert report.validation is not None
    assert report.validation.score == 1.0
    assert report.source == source_name
    assert report.source_diagnostics is not None
    assert report.source_diagnostics.discovered == 3
    expected_emitted = 2 if mode == "important" else 3
    assert report.source_diagnostics.emitted == expected_emitted
    assert report.source_diagnostics.skipped == expected_skips
    assert report.output_path is not None and report.output_path.exists()

    state = read_json(config.paths.state_dir / "synthetic-lang.json", {})
    assert state["completed"] is True
    assert state["source"] == source_name
    assert state["total_documents"] == expected_docs
    assert state["source_diagnostics"]["skipped"] == expected_skips
    assert not (config.paths.checkpoints_dir / "synthetic-lang.json").exists()

    report_json = read_json(config.paths.reports_dir / "run_summary.json", {})
    assert report_json["reports"][0]["language"] == "Synthetic Lang"
    assert report_json["reports"][0]["source"] == source_name
    assert report_json["reports"][0]["total_documents"] == expected_docs
    report_md = (config.paths.reports_dir / "run_summary.md").read_text(encoding="utf-8")
    assert "# Documentation Ingestion Report" in report_md
    assert "Source diagnostics" in report_md


def test_pipeline_run_records_resolution_failure_and_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)

    async def resolve(language_name: str, source_name=None, force_refresh: bool = False):
        return None

    async def suggest(language_name: str):
        return [("devdocs", "Synthetic Lang")]

    monkeypatch.setattr(pipeline.registry, "resolve", resolve)
    monkeypatch.setattr(pipeline.registry, "suggest", suggest)

    summary = asyncio.run(pipeline.run(language_name="Missing Lang"))

    report = summary.reports[0]
    assert report.source == "none"
    assert report.failures == ["No source provides 'Missing Lang'. Closest matches: Synthetic Lang (devdocs)."]
    report_json = read_json(config.paths.reports_dir / "run_summary.json", {})
    assert report_json["reports"][0]["failures"][0]["code"] == "not_found"
    assert report_json["reports"][0]["failures"][0]["message"] == str(report.failures[0])
