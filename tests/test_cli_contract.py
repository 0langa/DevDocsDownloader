from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import doc_ingest.cli as cli
from doc_ingest.config import load_config
from doc_ingest.models import RunSummary
from doc_ingest.utils.filesystem import write_json, write_text

runner = CliRunner()


def test_cli_help_exposes_scripted_contract_options() -> None:
    run_result = runner.invoke(cli.app, ["run", "--help"])
    bulk_result = runner.invoke(cli.app, ["bulk", "--help"])
    audit_result = runner.invoke(cli.app, ["audit-presets", "--help"])

    assert run_result.exit_code == 0
    assert "--include-topic" in run_result.output
    assert "--exclude-topic" in run_result.output
    assert "--output-dir" in run_result.output
    assert "--chunk-strategy" in run_result.output
    assert "Maximum tokens" in run_result.output

    assert bulk_result.exit_code == 0
    assert "--language-conc" in bulk_result.output
    assert "static|adaptiv" in bulk_result.output
    assert "Minimum adaptive" in bulk_result.output
    assert "--include-topic" in bulk_result.output
    assert "--exclude-topic" in bulk_result.output
    assert "--chunk-strategy" in bulk_result.output
    assert "Maximum tokens" in bulk_result.output
    assert "--chunks" in run_result.output
    assert "--cache-policy" in run_result.output

    assert audit_result.exit_code == 0
    assert "--source" in audit_result.output
    assert "--force-refresh" in audit_result.output


def test_cli_run_wires_topic_filters(monkeypatch) -> None:
    captured = {}

    def fake_execute_run(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli, "_execute_run", fake_execute_run)

    result = runner.invoke(
        cli.app,
        [
            "run",
            "Synthetic Lang",
            "--mode",
            "full",
            "--source",
            "devdocs",
            "--include-topic",
            "Reference",
            "--include-topic",
            "Guides",
            "--exclude-topic",
            "Internal",
            "--silent",
        ],
    )

    assert result.exit_code == 0
    assert captured["language"] == "Synthetic Lang"
    assert captured["mode"] == "full"
    assert captured["source"] == "devdocs"
    assert captured["verbosity"] == "silent"
    assert captured["include_topics"] == ["Reference", "Guides"]
    assert captured["exclude_topics"] == ["Internal"]


def test_cli_bulk_wires_topic_filters(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    captured = {}

    def fake_load_config(*_args, **_kwargs):
        return config

    class FakeService:
        def __init__(self, config):
            self.config = config

        async def run_bulk(self, request, *, progress_tracker=None):
            captured.update(request.model_dump())
            return RunSummary()

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "DocumentationService", FakeService)

    result = runner.invoke(
        cli.app,
        [
            "bulk",
            "webapp",
            "--include-topic",
            "Reference",
            "--exclude-topic",
            "Internal",
            "--language-concurrency",
            "2",
            "--concurrency-policy",
            "adaptive",
            "--adaptive-min-concurrency",
            "1",
            "--adaptive-max-concurrency",
            "4",
            "--silent",
        ],
    )

    assert result.exit_code == 0
    assert captured["include_topics"] == ["Reference"]
    assert captured["exclude_topics"] == ["Internal"]
    assert captured["language_concurrency"] == 2
    assert captured["concurrency_policy"] == "adaptive"
    assert captured["adaptive_max_concurrency"] == 4


def test_cli_validate_output_dir_uses_local_output_and_writes_reports(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path, output_dir=tmp_path / "contract-output")
    language_dir = config.paths.markdown_dir / "synthetic-lang"
    output_path = language_dir / "synthetic-lang.md"
    write_text(
        output_path,
        "\n".join(
            [
                "# Synthetic Lang Documentation",
                "",
                "## Metadata",
                "",
                "## Table of Contents",
                "",
                "## Documentation",
                "",
                "x" * 2500,
            ]
        ),
    )
    write_json(
        language_dir / "_meta.json",
        {
            "language": "Synthetic Lang",
            "slug": "synthetic-lang",
            "source": "local",
            "source_slug": "synthetic-lang",
            "source_url": "https://example.invalid/synthetic",
            "mode": "important",
            "total_documents": 1,
            "topics": [{"topic": "Reference", "document_count": 1}],
        },
    )

    def fake_load_config(*_args, **_kwargs):
        return config

    monkeypatch.setattr(cli, "load_config", fake_load_config)

    result = runner.invoke(
        cli.app,
        ["validate", "Synthetic Lang", "--output-dir", str(config.paths.output_dir)],
    )

    assert result.exit_code == 0
    assert "Synthetic Lang" in result.output
    assert (config.paths.reports_dir / "run_summary.json").exists()
    assert (config.paths.reports_dir / "run_summary.md").exists()


def test_cli_audit_presets_exit_codes(monkeypatch, tmp_path: Path) -> None:
    config = load_config(root=tmp_path)

    def fake_load_config(*_args, **_kwargs):
        return config

    class FakeService:
        def __init__(self, config):
            self.config = config

        async def audit_presets(self, *, presets=None, source=None, force_refresh=False):
            from doc_ingest.services import AuditPresetResult

            return [
                AuditPresetResult(
                    preset=preset,
                    language=language,
                    resolved=True,
                    source=source or "devdocs",
                    slug=language.lower(),
                )
                for preset in presets or []
                for language in cli.PRESETS[preset]
            ]

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "DocumentationService", FakeService)

    ok = runner.invoke(cli.app, ["audit-presets", "webapp", "--source", "devdocs"])
    missing = runner.invoke(cli.app, ["audit-presets", "does-not-exist"])

    assert ok.exit_code == 0
    assert "Resolved:" in ok.output
    assert missing.exit_code == 1
    assert "Unknown preset" in missing.output
