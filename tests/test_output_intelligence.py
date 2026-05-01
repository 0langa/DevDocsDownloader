from __future__ import annotations

from pathlib import Path

from doc_ingest.compiler import _semantic_chunks
from doc_ingest.models import DocumentValidationResult, ValidationIssue, ValidationResult, ValidationScoreComponents
from doc_ingest.output_intelligence import (
    apply_output_template,
    compare_manifests,
    generate_epub,
    generate_html_site,
    write_language_manifest,
    write_validation_json,
)
from doc_ingest.utils.filesystem import write_text


def _write_doc(path: Path, title: str, body: str) -> None:
    write_text(path, f"# {title}\n\n{body}\n")


def test_write_language_manifest_and_compare(tmp_path: Path) -> None:
    language_dir = tmp_path / "python"
    _write_doc(language_dir / "reference" / "alpha.md", "Alpha", "one")
    manifest1 = write_language_manifest(
        language_dir=language_dir,
        language="Python",
        source="devdocs",
        source_slug="python~3.12",
        mode="full",
    )
    _write_doc(language_dir / "reference" / "alpha.md", "Alpha", "two")
    manifest2 = write_language_manifest(
        language_dir=language_dir,
        language="Python",
        source="devdocs",
        source_slug="python~3.12",
        mode="full",
    )
    diff = compare_manifests(manifest2, manifest1)

    assert manifest1["document_count"] == 1
    assert manifest2["content_sha256"] != manifest1["content_sha256"]
    assert diff["summary"]["changed"] == 1


def test_write_validation_json_and_generate_formats(tmp_path: Path) -> None:
    language_dir = tmp_path / "python"
    _write_doc(language_dir / "reference" / "alpha.md", "Alpha", "content")
    validation = ValidationResult(
        language="Python",
        output_path=language_dir / "python.md",
        score=0.9,
        quality_score=0.9,
        component_scores=ValidationScoreComponents(completeness=1.0),
        issues=[ValidationIssue(level="warning", code="relative_link", message="warn")],
        document_results=[
            DocumentValidationResult(
                language="Python",
                topic="reference",
                slug="alpha",
                title="Alpha",
                document_path=language_dir / "reference" / "alpha.md",
                integrity_hash="abc",
                quality_score=0.8,
            )
        ],
    )

    validation_path = write_validation_json(language_dir, validation)
    site_root = generate_html_site(language_dir, language_slug="python", language_name="Python")
    epub_path = generate_epub(language_dir, language_slug="python", language_name="Python")

    assert validation_path is not None and validation_path.exists()
    assert (site_root / "index.html").exists()
    assert (site_root / "search-index.json").exists()
    assert epub_path.exists()


def test_apply_output_template_renders_non_default_bundle(tmp_path: Path) -> None:
    language_dir = tmp_path / "python"
    _write_doc(language_dir / "reference" / "alpha.md", "Alpha", "content")
    write_text(language_dir / "python.md", "# Python\n")

    apply_output_template(
        language_dir,
        template_name="api-reference",
        language="Python",
        source="devdocs",
        run_date="2026-05-01T00:00:00Z",
    )

    rendered = (language_dir / "python.md").read_text(encoding="utf-8")
    assert "API Reference" in rendered
    assert "Alpha" in rendered


def test_semantic_chunks_keep_fences_and_parent_context() -> None:
    text = (
        "## Parent\n\n"
        "Intro.\n\n"
        "### Child One\n\n"
        "```py\nprint('x')\n```\n\n"
        "Child body.\n\n"
        "### Child Two\n\n"
        "More child body.\n"
    )
    chunks = list(_semantic_chunks(text, max_chars=120))
    assert chunks
    joined = "\n".join(chunk[3] for chunk in chunks)
    assert joined.count("```") % 2 == 0
    # If a chunk starts from H3 boundary, parent H2 context is prepended.
    assert "## Parent" in joined
