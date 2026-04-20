from __future__ import annotations

import builtins
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_ingest.adapters import MicrosoftLearnAdapter, PythonDocsAdapter
from doc_ingest.config import load_config
from doc_ingest.errors import OptionalDependencyError
from doc_ingest.fetchers.browser import BrowserFetcher
from doc_ingest.models import ExtractedDocument, FetchResult, LanguageEntry
from doc_ingest.mergers.compiler import compile_language_markdown


class OptionalDependenciesAndAdaptersTests(unittest.TestCase):
    def test_textual_module_import_does_not_require_mammoth(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "mammoth":
                raise ImportError("missing mammoth")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            module = importlib.import_module("doc_ingest.extractors.textual")
            importlib.reload(module)
            self.assertTrue(hasattr(module, "extract_text"))

    def test_browser_fetcher_imports_playwright_lazily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top_50_programming_languages_with_official_docs.txt").write_text("", encoding="utf-8")
            config = load_config(root)
            fetcher = BrowserFetcher(config)
            real_import = builtins.__import__

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "playwright.async_api":
                    raise ImportError("missing playwright")
                return real_import(name, globals, locals, fromlist, level)

            async def run_case() -> None:
                with patch("builtins.__import__", side_effect=fake_import):
                    with self.assertRaises(OptionalDependencyError):
                        await fetcher.fetch("https://example.com", config.paths.cache_dir)
            import asyncio

            asyncio.run(run_case())

    def test_adapter_ordering_prioritizes_microsoft_learn_overview_before_reference(self) -> None:
        language = LanguageEntry(name="C#", source_url="https://learn.microsoft.com/en-us/dotnet/csharp/", slug="csharp")
        docs = [
            ExtractedDocument(
                url="https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/",
                final_url="https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/",
                title="Language reference",
                markdown="## Language reference\n\nReference body.",
                asset_type="html",
                content_hash="ref",
                word_count=4,
                breadcrumbs=["Reference"],
            ),
            ExtractedDocument(
                url="https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/",
                final_url="https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/",
                title="Overview",
                markdown="## Overview\n\nOverview body.",
                asset_type="html",
                content_hash="ov",
                word_count=4,
                breadcrumbs=["Overview"],
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "csharp.md"
            compile_language_markdown(language, docs, output, adapter=MicrosoftLearnAdapter())
            text = output.read_text(encoding="utf-8")
            self.assertLess(text.index("## Overview"), text.index("## Reference"))

    def test_python_adapter_strips_known_navigation_boilerplate(self) -> None:
        adapter = PythonDocsAdapter()
        cleaned = adapter.clean_markdown("Next topic\n\nActual text.\n\nPrevious topic")
        self.assertNotIn("Next topic", cleaned)
        self.assertNotIn("Previous topic", cleaned)


if __name__ == "__main__":
    unittest.main()
