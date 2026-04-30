from __future__ import annotations

import asyncio
import json
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
    assert bundles[0].bundle_bytes > 0
    assert bundles[0].file_count >= 4
    assert bundles[0].chunk_count == 1
    assert isinstance(bundles[0].latest_quality, dict)
    tree = service.output_tree("synthetic")
    assert any(child.name == "synthetic.md" for child in tree.children)
    assert service.read_output_file("synthetic", "synthetic.md").content == "# Synthetic\n"
    assert service.read_meta("synthetic")["language"] == "Synthetic"
    storage = service.output_storage_summary()
    assert storage.bundle_count == 1
    assert storage.total_bundle_bytes >= bundles[0].bundle_bytes

    with pytest.raises(ValueError):
        service.read_output_file("synthetic", "..\\..\\pyproject.toml")

    deleted = service.delete_output_bundle("synthetic")
    assert deleted.deleted is True
    assert deleted.freed_bytes >= bundles[0].bundle_bytes
    assert not language_dir.exists()


def test_service_report_checkpoint_and_cache_readers(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    config.paths.markdown_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.paths.reports_dir / "run_summary.json", {"reports": [{"language": "Synthetic"}]})
    write_text(config.paths.reports_dir / "run_summary.md", "# Report\n")
    write_text(config.paths.reports_dir / "validation_documents.jsonl", '{"language":"Synthetic","issues":[]}\n')
    write_json(config.paths.reports_dir / "trends.json", {"languages": {"Synthetic": {"runs": 1}}})
    write_text(config.paths.reports_dir / "trends.md", "# Trends\n")
    write_json(config.paths.reports_dir / "history" / "20260101T000000Z-run_summary.json", {"reports": []})
    write_json(
        config.paths.cache_dir / "catalogs" / "devdocs.json",
        {
            "source": "devdocs",
            "entries": [{"source": "devdocs", "slug": "synthetic", "display_name": "Synthetic"}],
        },
    )

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
    write_json(config.paths.state_dir / "synthetic.json", {"language": "Synthetic"})

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
    assert isinstance(reports.quality_trends, dict)
    assert len(reports.history_reports) == 1
    assert checkpoints[0].slug == "synthetic"
    assert checkpoints[0].phase == "failed"
    assert checkpoints[0].is_stale is False
    assert service.read_checkpoint("synthetic")["language"] == "Synthetic"
    assert cache[0].source == "devdocs"
    assert cache[0].cache_key == "docs-json"
    assert service.delete_checkpoint("synthetic") is True
    assert not (config.paths.checkpoints_dir / "synthetic.json").exists()
    assert not (config.paths.state_dir / "synthetic.json").exists()
    pruned = service.prune_report_history(keep_latest=0)
    assert pruned.deleted is True
    assert pruned.deleted_files == 1
    assert not (config.paths.reports_dir / "history").exists()

    with pytest.raises(ValueError):
        service.read_report_file("..\\state\\synthetic.json")
    with pytest.raises(ValueError):
        service.delete_checkpoint("..\\synthetic")


def test_service_languages_include_quality_fields(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    write_json(
        config.paths.cache_dir / "catalogs" / "devdocs.json",
        {
            "source": "devdocs",
            "entries": [
                {
                    "source": "devdocs",
                    "slug": "python~3.13",
                    "display_name": "Python",
                    "version": "3.13",
                    "discovery_metadata": {},
                }
            ],
        },
    )
    write_json(
        config.paths.cache_dir / "catalogs" / "mdn.json",
        {
            "source": "mdn",
            "entries": [
                {
                    "source": "mdn",
                    "slug": "python",
                    "display_name": "Python",
                    "version": "live",
                    "discovery_metadata": {},
                }
            ],
        },
    )
    quality_path = config.paths.logs_dir / "quality_history.jsonl"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(
            {
                "language": "Python",
                "source": "mdn",
                "slug": "python",
                "run_date": "2026-05-01T00:00:00+00:00",
                "validation_score": 0.9,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service = DocumentationService(config)
    rows = asyncio.run(service.list_languages())
    python_rows = [row for row in rows if row.language == "Python"]
    assert len(python_rows) == 2
    assert any(row.preferred_source for row in python_rows)
    assert any(row.latest_validation_score is not None for row in python_rows)


def test_service_flags_and_deletes_stale_checkpoints(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    config.paths.markdown_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        config.paths.cache_dir / "catalogs" / "devdocs.json",
        {
            "source": "devdocs",
            "entries": [{"source": "devdocs", "slug": "something-else", "display_name": "Other"}],
        },
    )
    write_json(
        config.paths.checkpoints_dir / "stale.json",
        LanguageRunCheckpoint(
            language="Stale",
            slug="stale",
            source="devdocs",
            source_slug="missing-slug",
            phase="failed",
        ).model_dump(mode="json"),
    )
    write_json(
        config.paths.state_dir / "stale.json",
        {"language": "Stale"},
    )

    service = DocumentationService(config)
    checkpoints = service.list_checkpoints()

    assert checkpoints[0].is_stale is True
    assert "no longer resolvable" in checkpoints[0].stale_reason
    assert service.delete_stale_checkpoints() == 1
    assert not (config.paths.checkpoints_dir / "stale.json").exists()
    assert not (config.paths.state_dir / "stale.json").exists()


def test_service_discards_checkpoint_with_missing_schema_version(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    write_json(
        config.paths.checkpoints_dir / "legacy.json",
        {
            "language": "Legacy",
            "slug": "legacy",
            "source": "devdocs",
            "source_slug": "legacy",
            "phase": "failed",
        },
    )

    service = DocumentationService(config)

    assert service.list_checkpoints() == []
    with pytest.raises(FileNotFoundError):
        service.read_checkpoint("legacy")


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
