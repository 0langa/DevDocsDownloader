from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import doc_ingest.cli as cli
from doc_ingest.config import load_config
from doc_ingest.gui.state import GuiJobQueue
from doc_ingest.models import CacheEntryMetadata, LanguageRunCheckpoint, RunSummary
from doc_ingest.services import BulkRunRequest, DocumentationService, RunLanguageRequest, ServiceEvent
from doc_ingest.utils.filesystem import write_json, write_text

runner = CliRunner()


def test_gui_service_output_reading_and_path_safety(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    language_dir = config.paths.markdown_dir / "synthetic"
    write_json(
        language_dir / "_meta.json",
        {
            "language": "Synthetic",
            "source": "devdocs",
            "source_slug": "synthetic",
            "mode": "important",
            "total_documents": 1,
            "topics": [{"topic": "Reference", "document_count": 1}],
            "outputs": {"document_frontmatter": True, "chunks": True},
        },
    )
    write_text(language_dir / "synthetic.md", "# Synthetic\n")
    write_text(language_dir / "reference" / "_section.md", "# Reference\n")
    write_text(language_dir / "chunks" / "manifest.jsonl", '{"chunk_id":"synthetic-reference-0"}\n')

    service = DocumentationService(config)
    bundles = service.list_output_bundles()

    assert len(bundles) == 1
    assert bundles[0].language == "Synthetic"
    assert bundles[0].has_chunks is True
    assert bundles[0].has_frontmatter is True
    tree = service.output_tree("synthetic")
    assert any(child.name == "synthetic.md" for child in tree.children)
    assert service.read_output_file("synthetic", "synthetic.md").content == "# Synthetic\n"
    assert service.read_meta("synthetic")["language"] == "Synthetic"

    with pytest.raises(ValueError):
        service.read_output_file("synthetic", "..\\..\\pyproject.toml")


def test_gui_service_report_checkpoint_and_cache_readers(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    write_json(config.paths.reports_dir / "run_summary.json", {"reports": [{"language": "Synthetic"}]})
    write_text(config.paths.reports_dir / "run_summary.md", "# Report\n")
    write_text(config.paths.reports_dir / "validation_documents.jsonl", '{"language":"Synthetic","issues":[]}\n')
    write_json(config.paths.reports_dir / "trends.json", {"languages": {"Synthetic": {"runs": 1}}})
    write_text(config.paths.reports_dir / "trends.md", "# Trends\n")
    write_json(config.paths.reports_dir / "history" / "20260101T000000Z-run_summary.json", {"reports": []})

    checkpoint = LanguageRunCheckpoint(
        language="Synthetic",
        slug="synthetic",
        source="devdocs",
        source_slug="synthetic",
        phase="failed",
        emitted_document_count=2,
        document_inventory_position=20,
    )
    write_json(config.paths.checkpoints_dir / "synthetic.json", checkpoint.model_dump(mode="json"))

    metadata = CacheEntryMetadata(
        source="devdocs",
        cache_key="docs-json",
        url="https://example.invalid/docs.json",
        checksum="abc",
        byte_count=123,
        policy="ttl",
    )
    write_json(config.paths.cache_dir / "devdocs" / "docs.json.meta.json", metadata.model_dump(mode="json"))

    service = DocumentationService(config)
    reports = service.read_reports()
    checkpoints = service.list_checkpoints()
    cache = service.list_cache_metadata()

    assert reports.latest_json["reports"][0]["language"] == "Synthetic"
    assert reports.latest_markdown == "# Report\n"
    assert reports.validation_documents[0]["language"] == "Synthetic"
    assert len(reports.history_reports) == 1
    assert checkpoints[0].slug == "synthetic"
    assert checkpoints[0].phase == "failed"
    assert service.read_checkpoint("synthetic")["language"] == "Synthetic"
    assert cache[0].source == "devdocs"
    assert cache[0].cache_key == "docs-json"
    assert service.delete_checkpoint("synthetic") is True
    assert not (config.paths.checkpoints_dir / "synthetic.json").exists()

    with pytest.raises(ValueError):
        service.read_report_file("..\\state\\synthetic.json")
    with pytest.raises(ValueError):
        service.delete_checkpoint("..\\synthetic")


def test_gui_job_queue_transitions_and_events() -> None:
    class FakeService:
        async def run_language(self, _request: Any, *, event_sink=None) -> RunSummary:
            if event_sink is not None:
                event_sink(ServiceEvent(event_type="phase_change", language="Synthetic", phase="started"))
                event_sink(
                    ServiceEvent(
                        event_type="document_emitted",
                        language="Synthetic",
                        payload={"index": 1, "total": 1},
                    )
                )
                event_sink(ServiceEvent(event_type="validation_completed", language="Synthetic", payload={"score": 1}))
            return RunSummary()

    async def scenario() -> None:
        queue = GuiJobQueue()
        state = queue.submit_run(FakeService(), RunLanguageRequest(language="Synthetic"))  # type: ignore[arg-type]
        await queue.wait_idle()
        assert state.status == "completed"
        assert state.progress == 1.0
        assert [event.event_type for event in state.events] == [
            "phase_change",
            "document_emitted",
            "validation_completed",
        ]
        assert state.summary["reports"] == []

    asyncio.run(scenario())


def test_gui_job_queue_bulk_preserves_adaptive_request_fields() -> None:
    captured = {}

    class FakeService:
        async def run_bulk(self, request: BulkRunRequest, *, event_sink=None) -> RunSummary:
            captured.update(request.model_dump())
            return RunSummary()

    async def scenario() -> None:
        queue = GuiJobQueue()
        state = queue.submit_bulk(
            FakeService(),  # type: ignore[arg-type]
            BulkRunRequest(
                languages=["Synthetic"],
                concurrency_policy="adaptive",
                adaptive_min_concurrency=1,
                adaptive_max_concurrency=4,
            ),
        )
        await queue.wait_idle()
        assert state.status == "completed"
        assert captured["concurrency_policy"] == "adaptive"
        assert captured["adaptive_max_concurrency"] == 4

    asyncio.run(scenario())


def test_gui_job_queue_failure_and_cancel() -> None:
    async def scenario() -> None:
        queue = GuiJobQueue()

        async def failing(_event_sink):
            raise RuntimeError("boom")

        failed = queue.submit(label="bad", kind="run", runner=failing)
        await queue.wait_idle()
        assert failed.status == "failed"
        assert "RuntimeError: boom" in failed.error

        async def noop(_event_sink):
            return {"ok": True}

        first = queue.submit(label="first", kind="run", runner=noop)
        second = queue.submit(label="second", kind="run", runner=noop)
        assert queue.cancel_job(second.id) is True
        await queue.wait_idle()
        assert first.status == "completed"
        assert second.status == "cancelled"

    asyncio.run(scenario())


def test_cli_gui_help_and_missing_extra(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)

    def fake_load_config(*_args, **_kwargs):
        return config

    def fake_run_gui(*_args, **_kwargs) -> None:
        raise RuntimeError("NiceGUI support is not installed. Run: python -m pip install -e .[gui]")

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr("doc_ingest.gui.app.run_gui", fake_run_gui)

    help_result = runner.invoke(cli.app, ["gui", "--help"])
    error_result = runner.invoke(cli.app, ["gui", "--host", "127.0.0.1", "--port", "8123"])

    assert help_result.exit_code == 0
    assert "--host" in help_result.output
    assert "--port" in help_result.output
    assert "--native" in help_result.output
    assert "--output-dir" in help_result.output
    assert error_result.exit_code == 1
    assert "pip install -e .[gui]" in error_result.output


def test_cli_gui_wires_options(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    captured = {}

    def fake_load_config(*_args, **kwargs):
        captured["output_dir"] = kwargs.get("output_dir")
        return config

    def fake_run_gui(passed_config, **kwargs) -> None:
        captured["config"] = passed_config
        captured.update(kwargs)

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr("doc_ingest.gui.app.run_gui", fake_run_gui)

    result = runner.invoke(
        cli.app,
        [
            "gui",
            "--host",
            "0.0.0.0",
            "--port",
            "8123",
            "--reload",
            "--native",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert captured["config"] is config
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8123
    assert captured["reload"] is True
    assert captured["native"] is True
    assert captured["output_dir"] == tmp_path / "out"


def test_nicegui_app_factory_smoke(tmp_path: Path) -> None:
    if importlib.util.find_spec("nicegui") is None:
        pytest.skip("NiceGUI optional extra is not installed")

    from doc_ingest.gui.app import create_gui_app

    app = create_gui_app(load_config(root=tmp_path))
    assert app is not None
