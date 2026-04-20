from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_ingest.adapters import PythonDocsAdapter
from doc_ingest.config import load_config
from doc_ingest.mergers.compiler import compile_language_markdown
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

    def test_validator_accepts_expected_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top_50_programming_languages_with_official_docs.txt").write_text("", encoding="utf-8")
            config = load_config(root)
            output = root / "output" / "markdown" / "python.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                "# Python Documentation\n\n## Source Metadata\n\n- Language: Python\n\n## Crawl Summary\n\n- Processed pages: 1\n\n## Table of Contents\n\n- [Intro](#intro)\n\n## Guide\n\n### Intro\n\nText\n",
                encoding="utf-8",
            )
            result = validate_markdown("Python", output, config)
            self.assertGreater(result.score, 0.5)

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
            self.assertIn("## Appendix: Failed Pages", text)
            self.assertIn("## Tutorial", text)


if __name__ == "__main__":
    unittest.main()
