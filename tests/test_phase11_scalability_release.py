from __future__ import annotations

import asyncio
import builtins
from pathlib import Path

import doc_ingest.adaptive as adaptive_module
from doc_ingest.adaptive import AdaptiveBulkController, AdaptiveBulkPolicy
from doc_ingest.config import load_config
from doc_ingest.models import FailureDetail, LanguageRunReport, RunSummary, RuntimeTelemetrySnapshot
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.base import LanguageCatalog
from doc_ingest.sources.registry import SourceRegistry


def test_static_bulk_mode_preserves_explicit_concurrency(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    current = 0
    peak = 0

    async def fake_run(self, **kwargs):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return RunSummary(
            reports=[LanguageRunReport(language=kwargs["language_name"], slug="x", source="fixture", source_slug="x")]
        )

    monkeypatch.setattr(DocumentationPipeline, "run", fake_run)

    summary = asyncio.run(
        pipeline.run_many(
            language_names=["a", "b", "c"],
            language_concurrency=2,
            concurrency_policy="static",
        )
    )

    assert peak == 2
    assert summary.adaptive_telemetry is not None
    assert summary.adaptive_telemetry.policy == "static"
    assert [report.language for report in summary.reports] == ["a", "b", "c"]


def test_adaptive_bulk_policy_reduces_after_failure_and_preserves_order(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)

    async def fake_run(self, **kwargs):
        language = kwargs["language_name"]
        report = LanguageRunReport(language=language, slug=language, source="fixture", source_slug=language)
        if language == "a":
            report.failures.append(FailureDetail(code="runtime_error", message="failed"))
            report.runtime_telemetry = RuntimeTelemetrySnapshot(retries=4, failures=1)
        return RunSummary(reports=[report])

    monkeypatch.setattr(DocumentationPipeline, "run", fake_run)

    summary = asyncio.run(
        pipeline.run_many(
            language_names=["a", "b", "c", "d"],
            language_concurrency=2,
            concurrency_policy="adaptive",
            adaptive_min_concurrency=1,
            adaptive_max_concurrency=3,
        )
    )

    assert [report.language for report in summary.reports] == ["a", "b", "c", "d"]
    assert summary.adaptive_telemetry is not None
    assert summary.adaptive_telemetry.policy == "adaptive"
    assert summary.adaptive_telemetry.current_concurrency <= 2
    assert any(reason.startswith("decrease:") for reason in summary.adaptive_telemetry.adjustment_reasons)


def test_adaptive_controller_increases_after_successful_windows(monkeypatch) -> None:
    monkeypatch.setattr(adaptive_module, "_system_pressure_reasons", lambda _policy: [])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=1, min_concurrency=1, max_concurrency=3))

    controller.observe(LanguageRunReport(language="a", slug="a", source="fixture", source_slug="a"))
    controller.observe(LanguageRunReport(language="b", slug="b", source="fixture", source_slug="b"))

    assert controller.current_concurrency == 2
    assert controller.snapshot().adjustment_reasons == ["increase:successful_window:to:2"]


def test_adaptive_controller_tolerates_missing_psutil(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=1, min_concurrency=1, max_concurrency=2))
    controller.observe(LanguageRunReport(language="a", slug="a", source="fixture", source_slug="a"))

    assert controller.snapshot().observed_windows == 1


class SuggestionSource:
    def __init__(self, name: str, entries: list[LanguageCatalog]) -> None:
        self.name = name
        self._entries = entries

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return self._entries


def test_source_resolution_priority_and_matching_buckets(tmp_path: Path) -> None:
    registry = SourceRegistry(cache_dir=tmp_path)
    registry.sources = [
        SuggestionSource(
            "devdocs",
            [
                LanguageCatalog(source="devdocs", slug="python~3.13", display_name="Python", version="3.13"),
                LanguageCatalog(source="devdocs", slug="go", display_name="Go"),
            ],
        ),
        SuggestionSource("mdn", [LanguageCatalog(source="mdn", slug="html", display_name="HTML")]),
        SuggestionSource("dash", [LanguageCatalog(source="dash", slug="go", display_name="Go Dash")]),
    ]

    html_source, html_catalog = asyncio.run(registry.resolve("html"))
    go_source, go_catalog = asyncio.run(registry.resolve("Go"))
    py_source, py_catalog = asyncio.run(registry.resolve("python"))

    assert (html_source.name, html_catalog.display_name) == ("mdn", "HTML")
    assert (go_source.name, go_catalog.display_name) == ("devdocs", "Go")
    assert (py_source.name, py_catalog.display_name) == ("devdocs", "Python")


def test_source_suggestions_are_deterministic_and_deduplicated(tmp_path: Path) -> None:
    registry = SourceRegistry(cache_dir=tmp_path)
    registry.sources = [
        SuggestionSource("devdocs", [LanguageCatalog(source="devdocs", slug="typescript", display_name="TypeScript")]),
        SuggestionSource("mdn", [LanguageCatalog(source="mdn", slug="javascript", display_name="JavaScript")]),
        SuggestionSource("dash", [LanguageCatalog(source="dash", slug="typescript", display_name="TypeScript")]),
        SuggestionSource("plugin", [LanguageCatalog(source="plugin", slug="type-theory", display_name="Type Theory")]),
    ]

    suggestions = asyncio.run(registry.suggest("type", limit=4))

    assert suggestions[0] == ("devdocs", "TypeScript")
    assert ("dash", "TypeScript") in suggestions
    assert ("plugin", "Type Theory") in suggestions
    assert len(suggestions) == len(set(suggestions))
