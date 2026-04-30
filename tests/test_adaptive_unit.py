from __future__ import annotations

from doc_ingest.adaptive import AdaptiveBulkController, AdaptiveBulkPolicy
from doc_ingest.models import LanguageRunReport, RuntimeTelemetrySnapshot


def test_adaptive_controller_increases_after_success_window(monkeypatch) -> None:
    monkeypatch.setattr("doc_ingest.adaptive._system_pressure_reasons", lambda _policy: [])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=1, min_concurrency=1, max_concurrency=3))

    controller.observe(LanguageRunReport(language="a", slug="a", source="fixture", source_slug="a"))
    controller.observe(LanguageRunReport(language="b", slug="b", source="fixture", source_slug="b"))

    assert controller.current_concurrency == 2
    assert controller.snapshot().adjustment_reasons == ["increase:successful_window:to:2"]


def test_adaptive_controller_decreases_on_rapid_failure_bursts(monkeypatch) -> None:
    monkeypatch.setattr("doc_ingest.adaptive._system_pressure_reasons", lambda _policy: [])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=3, min_concurrency=1, max_concurrency=4))

    controller.observe(
        LanguageRunReport(
            language="a",
            slug="a",
            source="fixture",
            source_slug="a",
            failures=[],
            runtime_telemetry=RuntimeTelemetrySnapshot(retries=4, failures=1),
        )
    )

    assert controller.current_concurrency == 2
    assert any(reason.startswith("decrease:") for reason in controller.snapshot().adjustment_reasons)


def test_adaptive_controller_recovers_after_low_concurrency_success(monkeypatch) -> None:
    monkeypatch.setattr("doc_ingest.adaptive._system_pressure_reasons", lambda _policy: [])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=2, min_concurrency=1, max_concurrency=3))

    controller.observe(
        LanguageRunReport(
            language="a",
            slug="a",
            source="fixture",
            source_slug="a",
            failures=["boom"],
        )
    )
    assert controller.current_concurrency == 1

    controller.observe(LanguageRunReport(language="b", slug="b", source="fixture", source_slug="b"))
    controller.observe(LanguageRunReport(language="c", slug="c", source="fixture", source_slug="c"))

    assert controller.current_concurrency == 2


def test_adaptive_controller_enforces_min_max_bounds(monkeypatch) -> None:
    monkeypatch.setattr("doc_ingest.adaptive._system_pressure_reasons", lambda _policy: [])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=5, min_concurrency=2, max_concurrency=3))

    assert controller.current_concurrency == 3

    controller.observe(LanguageRunReport(language="a", slug="a", source="fixture", source_slug="a", failures=["boom"]))
    controller.observe(LanguageRunReport(language="b", slug="b", source="fixture", source_slug="b", failures=["boom"]))
    assert controller.current_concurrency == 2

    controller.observe(LanguageRunReport(language="c", slug="c", source="fixture", source_slug="c"))
    controller.observe(LanguageRunReport(language="d", slug="d", source="fixture", source_slug="d"))
    controller.observe(LanguageRunReport(language="e", slug="e", source="fixture", source_slug="e"))
    controller.observe(LanguageRunReport(language="f", slug="f", source="fixture", source_slug="f"))
    assert controller.current_concurrency == 3


def test_adaptive_controller_emergency_drops_on_memory_pressure(monkeypatch) -> None:
    monkeypatch.setattr("doc_ingest.adaptive._system_pressure_reasons", lambda _policy: ["memory_pressure:91.0"])
    controller = AdaptiveBulkController(AdaptiveBulkPolicy(initial_concurrency=3, min_concurrency=1, max_concurrency=4))

    controller.observe(LanguageRunReport(language="a", slug="a", source="fixture", source_slug="a"))

    assert controller.current_concurrency == 1
    assert controller.snapshot().adjustment_reasons == ["emergency_decrease:memory_pressure:91.0:to:1"]
