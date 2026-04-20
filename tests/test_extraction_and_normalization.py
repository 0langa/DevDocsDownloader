from __future__ import annotations

import builtins
import unittest
from unittest.mock import patch

from doc_ingest.extractors.dispatcher import extract_document
from doc_ingest.errors import OptionalDependencyError
from doc_ingest.models import FetchResult
from doc_ingest.normalizers.markdown import normalize_document


class ExtractionAndNormalizationTests(unittest.TestCase):
    def test_html_extraction_selects_structured_candidate(self) -> None:
        html = b"""
        <html><head><title>Example Docs</title></head>
        <body>
          <nav><a href="/login">login</a></nav>
          <main>
            <h1>Welcome</h1>
            <p>Intro text for the documentation page.</p>
            <h2>Usage</h2>
            <pre><code class="language-python">print('hi')</code></pre>
            <p><a href="/guide">Guide</a></p>
          </main>
        </body></html>
        """
        result = FetchResult(
            url="https://example.com/docs",
            final_url="https://example.com/docs",
            content_type="text/html",
            status_code=200,
            method="http",
            content=html,
        )
        document = extract_document(result, preferred_extractors=["html_readability", "html_docling"])
        self.assertEqual(document.asset_type, "html")
        self.assertIsNotNone(document.extraction)
        self.assertGreater(document.extraction.score, 0.2)
        self.assertIn(document.metadata["extractor"], {"html_readability", "html_docling"})

    def test_normalizer_fixes_heading_spacing_and_boilerplate(self) -> None:
        result = FetchResult(
            url="https://example.com/plain",
            final_url="https://example.com/plain",
            content_type="text/plain",
            status_code=200,
            method="http",
            content=b"#Bad\n\ncookie\n\nText body",
        )
        document = extract_document(result)
        document.markdown = "#Bad\n\ncookie\n\nText body\n"
        normalized = normalize_document(document)
        self.assertIn("# Bad", normalized.markdown)
        self.assertNotIn("cookie", normalized.markdown.lower())

    def test_docx_extraction_fails_lazily_when_mammoth_missing(self) -> None:
        result = FetchResult(
            url="https://example.com/file.docx",
            final_url="https://example.com/file.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            status_code=200,
            method="http",
            content=b"fake-docx",
        )
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "mammoth":
                raise ImportError("missing mammoth")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(OptionalDependencyError) as ctx:
                extract_document(result)
        self.assertIn("mammoth", str(ctx.exception))
        self.assertIn("DOCX extraction", str(ctx.exception))

    def test_normalizer_handles_sidebar_heavy_markdown_fixture(self) -> None:
        result = FetchResult(
            url="https://example.com/sidebar",
            final_url="https://example.com/sidebar",
            content_type="text/plain",
            status_code=200,
            method="http",
            content=b"placeholder",
        )
        document = extract_document(result)
        document.markdown = (
            "## Intro\n\n"
            "On This Page\n\n"
            "Skip to main content\n\n"
            "|Name|Value|\n|---|---|\n|A|B|\n\n"
            "``` \nprint('x')\n\n"
            "A real paragraph.\n\n"
            "A real paragraph.\n\n"
            "A real paragraph.\n"
        )
        normalized = normalize_document(document)
        self.assertNotIn("On This Page", normalized.markdown)
        self.assertIn("| Name | Value |", normalized.markdown)
        self.assertIn("```text", normalized.markdown)


if __name__ == "__main__":
    unittest.main()
