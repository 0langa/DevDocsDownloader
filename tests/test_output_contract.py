from __future__ import annotations

import asyncio
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.utils.filesystem import read_json

from .helpers import (
    FixtureSource,
    contract_documents,
    normalize_contract_text,
    synthetic_catalog,
)

FIXTURES = Path(__file__).parent / "fixtures" / "output_contract"


def _expected(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").rstrip() + "\n"


def _normalized_file(path: Path, root: Path) -> str:
    return normalize_contract_text(path.read_text(encoding="utf-8"), root).rstrip() + "\n"


def test_stable_output_contract_golden_files_and_state(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = synthetic_catalog(source="devdocs")
    source = FixtureSource("devdocs", catalog, contract_documents())

    report = asyncio.run(
        pipeline._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    language_dir = config.paths.markdown_dir / "synthetic-lang"
    assert _normalized_file(language_dir / "index.md", tmp_path) == _expected("index.md")
    assert _normalized_file(language_dir / "reference" / "_section.md", tmp_path) == _expected("reference_section.md")
    assert _normalized_file(language_dir / "reference" / "std-vector.md", tmp_path) == _expected("vector_api.md")
    assert _normalized_file(language_dir / "synthetic-lang.md", tmp_path) == _expected("consolidated.md")

    assert (language_dir / "reference" / "std-vector-2.md").exists()
    assert (language_dir / "guides" / "com1-item.md").exists()
    assert not (config.paths.checkpoints_dir / "synthetic-lang.json").exists()

    meta = read_json(language_dir / "_meta.json", {})
    assert {
        "language": meta["language"],
        "slug": meta["slug"],
        "source": meta["source"],
        "source_slug": meta["source_slug"],
        "source_url": meta["source_url"],
        "mode": meta["mode"],
        "total_documents": meta["total_documents"],
        "topics": meta["topics"],
    } == {
        "language": "Synthetic Lang",
        "slug": "synthetic-lang",
        "source": "devdocs",
        "source_slug": "synthetic-lang",
        "source_url": "https://example.invalid/synthetic",
        "mode": "full",
        "total_documents": 3,
        "topics": [
            {"topic": "Reference", "document_count": 2},
            {"topic": "Guides", "document_count": 1},
        ],
    }
    assert isinstance(meta["generated_at"], str)

    state = read_json(config.paths.state_dir / "synthetic-lang.json", {})
    assert state["completed"] is True
    assert state["language"] == "Synthetic Lang"
    assert state["source"] == "devdocs"
    assert state["source_slug"] == "synthetic-lang"
    assert state["total_documents"] == 3
    assert state["topics"] == meta["topics"]
    assert state["source_diagnostics"] == {"discovered": 3, "emitted": 3, "skipped": {}}
    assert state["output_path"].endswith("synthetic-lang.md")

    assert report.validation is not None
    assert report.validation.score == 1.0
    assert report.failures == []
    assert report.source_diagnostics is not None
    assert report.source_diagnostics.discovered == 3


def test_failed_output_contract_retains_checkpoint_boundary(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    pipeline = DocumentationPipeline(config)
    catalog = synthetic_catalog(source="mdn")
    source = FixtureSource("mdn", catalog, contract_documents(), fail_after=2)

    report = asyncio.run(
        pipeline._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    checkpoint = read_json(config.paths.checkpoints_dir / "synthetic-lang.json", {})
    assert report.failures == ["RuntimeError: fixture source interrupted"]
    assert checkpoint["phase"] == "failed"
    assert checkpoint["language"] == "Synthetic Lang"
    assert checkpoint["source"] == "mdn"
    assert checkpoint["source_slug"] == "synthetic-lang"
    assert checkpoint["mode"] == "full"
    assert checkpoint["document_inventory_position"] == 20
    assert checkpoint["emitted_document_count"] == 2
    assert checkpoint["last_document"] == {
        "topic": "Reference",
        "slug": "std-vector-2",
        "title": "Vector Guide",
        "source_url": "https://example.invalid/reference/vector-guide",
        "order_hint": 20,
    }
    assert checkpoint["failures"][0]["phase"] == "compiling"
    assert checkpoint["failures"][0]["error_type"] == "RuntimeError"
    assert checkpoint["failures"][0]["emitted_document_count"] == 2
