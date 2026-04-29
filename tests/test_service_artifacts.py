from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from doc_ingest.config import load_config
from doc_ingest.models import CacheEntryMetadata, LanguageRunCheckpoint
from doc_ingest.services import DocumentationService
from doc_ingest.utils.filesystem import write_json, write_text


def test_service_output_reading_and_path_safety(tmp_path: Path) -> None:
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


def test_service_report_checkpoint_and_cache_readers(tmp_path: Path) -> None:
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


def test_refresh_catalogs_returns_structured_statuses(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    service = DocumentationService(config)

    write_json(
        config.paths.cache_dir / "catalogs" / "devdocs.json",
        {
            "source": "devdocs",
            "discovery_strategy": "live",
            "fetched_at": "2026-04-29T00:00:00Z",
            "entries": [
                {"source": "devdocs", "slug": "python", "display_name": "Python", "support_level": "supported"}
            ],
            "fallback_used": True,
            "fallback_reason": "network failed",
            "warnings": ["used cached manifest"],
        },
    )

    class FakeSource:
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def list_languages(self, *, force_refresh: bool = False):
            if self.fail:
                raise RuntimeError(f"{self.name} boom")
            return [object()]

    class FakeRuntime:
        async def close(self) -> None:
            return None

    class FakeRegistry:
        def __init__(self) -> None:
            self.sources = [FakeSource("devdocs"), FakeSource("mdn", fail=True)]
            self.runtime = FakeRuntime()

    service._registry = lambda: FakeRegistry()  # type: ignore[method-assign]
    results = {row.source: row for row in asyncio.run(service.refresh_catalogs())}

    assert results["devdocs"].status == "fallback"
    assert results["devdocs"].entry_count == 1
    assert results["devdocs"].fallback_reason == "network failed"
    assert results["mdn"].status == "failed"
    assert "RuntimeError: mdn boom" in results["mdn"].errors[0]
