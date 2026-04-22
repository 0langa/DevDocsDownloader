from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_ingest.adapters import PythonDocsAdapter, TypeScriptAdapter
from doc_ingest.config import load_config
from doc_ingest.mergers.compiler import compile_language_markdown, compile_language_markdown_streaming
from doc_ingest.models import CrawlState, ExtractedDocument, LanguageEntry, PageState
from doc_ingest.validators.markdown_validator import validate_markdown


class CompilerAndValidatorTests(unittest.TestCase):
    def test_compile_orders_pages_using_state_depth(self) -> None:
        language = LanguageEntry(name="Python", source_url="https://docs.python.org/3/", slug="python")
        docs = [
            ExtractedDocument(
                url="https://docs.python.org/3/library",
                final_url="https://docs.python.org/3/library",
                title="Library",
                markdown="## Library\n\nLibrary text",
                asset_type="html",
                content_hash="b",
                word_count=4,
            ),
            ExtractedDocument(
                url="https://docs.python.org/3/tutorial",
                final_url="https://docs.python.org/3/tutorial",
                title="Tutorial",
                markdown="## Tutorial\n\nTutorial text",
                asset_type="html",
                content_hash="a",
                word_count=4,
            ),
        ]
        state = CrawlState(
            language="Python",
            slug="python",
            source_url="https://docs.python.org/3/",
            pages={
                "https://docs.python.org/3/tutorial": PageState(normalized_url="https://docs.python.org/3/tutorial", discovered_url="https://docs.python.org/3/tutorial", depth=1, status="processed"),
                "https://docs.python.org/3/library": PageState(normalized_url="https://docs.python.org/3/library", discovered_url="https://docs.python.org/3/library", depth=2, status="processed"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "python.md"
            compile_language_markdown(language, docs, output, state=state, adapter=PythonDocsAdapter())
            text = output.read_text(encoding="utf-8")
            self.assertLess(text.index("### Tutorial"), text.index("### Library"))
            self.assertIn("## Metadata", text)
            self.assertIn("## Documentation", text)
            self.assertIn("## Appendix", text)

    def test_validator_accepts_expected_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_documents = root / "source-documents"
            source_documents.mkdir(parents=True, exist_ok=True)
            (source_documents / "renamed-link-source.md").write_text("", encoding="utf-8")
            config = load_config(root)
            output = root / "output" / "markdown" / "python.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                "# Python Documentation\n\n## Metadata\n\n- Source: https://docs.python.org/3/\n- Crawl Date: 2026-04-21T00:00:00+00:00\n- Pages Processed: 1\n- Pages Skipped: 0\n- Adapter Used: python-docs\n\n## Table of Contents\n\n- [Guide](#guide)\n  - [Intro](#guide-intro)\n\n## Documentation\n\n### Guide\n\n#### Intro\n\nText\n\n## Appendix\n\n### Skipped Pages\n\n- None\n\n### Low-Quality Pages\n\n- None\n\n### Notes\n\n- None\n",
                encoding="utf-8",
            )
            result = validate_markdown("Python", output, config)
            self.assertGreater(result.score, 0.5)
            self.assertGreater(result.metrics.structure_quality, 0.7)

    def test_compiler_deduplicates_near_duplicate_pages_and_builds_appendix(self) -> None:
        language = LanguageEntry(name="Python", source_url="https://docs.python.org/3/", slug="python")
        docs = [
            ExtractedDocument(
                url="https://docs.python.org/3/tutorial/intro",
                final_url="https://docs.python.org/3/tutorial/intro",
                title="Introduction",
                markdown="## Introduction\n\nShared body text.\n\nMore detail here.",
                asset_type="html",
                content_hash="a",
                word_count=6,
                breadcrumbs=["Tutorial"],
            ),
            ExtractedDocument(
                url="https://docs.python.org/3/tutorial/intro-duplicate",
                final_url="https://docs.python.org/3/tutorial/intro-duplicate",
                title="Introduction Copy",
                markdown="## Introduction Copy\n\nShared body text.\n\nMore detail here.",
                asset_type="html",
                content_hash="b",
                word_count=6,
                breadcrumbs=["Tutorial"],
            ),
        ]
        state = CrawlState(
            language="Python",
            slug="python",
            source_url="https://docs.python.org/3/",
            pages={
                "https://docs.python.org/3/tutorial/intro": PageState(normalized_url="https://docs.python.org/3/tutorial/intro", discovered_url="https://docs.python.org/3/tutorial/intro", depth=1, status="processed"),
                "https://docs.python.org/3/tutorial/intro-duplicate": PageState(normalized_url="https://docs.python.org/3/tutorial/intro-duplicate", discovered_url="https://docs.python.org/3/tutorial/intro-duplicate", depth=1, status="failed", last_error="Duplicate"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "python.md"
            compile_language_markdown(language, docs, output, state=state, adapter=PythonDocsAdapter())
            text = output.read_text(encoding="utf-8")
            self.assertEqual(text.count("Shared body text."), 1)
            self.assertIn("## Appendix", text)
            self.assertIn("### Low-Quality Pages", text)
            self.assertIn("### Tutorial", text)

    def test_compiler_ignores_adapter_noise_headings(self) -> None:
        language = LanguageEntry(name="TypeScript", source_url="https://www.typescriptlang.org/docs/", slug="typescript")
        docs = [
            ExtractedDocument(
                url="https://www.typescriptlang.org/docs/handbook/intro.html",
                final_url="https://www.typescriptlang.org/docs/handbook/intro.html",
                title="TypeScript Handbook",
                markdown="## On this page\n\n- Link one\n\n## Handbook\n\nUseful handbook text.",
                asset_type="html",
                content_hash="ts-1",
                word_count=8,
                breadcrumbs=["Handbook"],
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "typescript.md"
            compile_language_markdown(language, docs, output, adapter=TypeScriptAdapter())
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("On this page", text)
            self.assertIn("Useful handbook text.", text)

    def test_compile_streaming_accepts_iterable_documents(self) -> None:
        language = LanguageEntry(name="Python", source_url="https://docs.python.org/3/", slug="python")
        docs = [
            ExtractedDocument(
                url="https://docs.python.org/3/tutorial",
                final_url="https://docs.python.org/3/tutorial",
                title="Tutorial",
                markdown="## Tutorial\n\nTutorial text",
                asset_type="html",
                content_hash="stream-a",
                word_count=4,
                breadcrumbs=["Guide"],
            ),
            ExtractedDocument(
                url="https://docs.python.org/3/library",
                final_url="https://docs.python.org/3/library",
                title="Library",
                markdown="## Library\n\nLibrary text",
                asset_type="html",
                content_hash="stream-b",
                word_count=4,
                breadcrumbs=["Reference"],
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "python-stream.md"
            compile_language_markdown_streaming(language, (doc for doc in docs), output, adapter=PythonDocsAdapter())
            text = output.read_text(encoding="utf-8")
            self.assertIn("### Guide", text)
            self.assertIn("### Reference", text)


if __name__ == "__main__":
    unittest.main()
