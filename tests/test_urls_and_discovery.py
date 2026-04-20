from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_ingest.adapters import SiteAdapter
from doc_ingest.config import load_config
from doc_ingest.discovery import DiscoveryHelper
from doc_ingest.models import LanguageEntry, PlannedSource
from doc_ingest.utils.urls import normalize_url


class UrlAndDiscoveryTests(unittest.TestCase):
    def test_normalize_url_canonicalizes_common_variants(self) -> None:
        url = "HTTP://Docs.Python.org:443/3/index.html?utm_source=x&view=all#section"
        normalized = normalize_url(url, keep_query_params=["view"])
        self.assertEqual(normalized, "https://docs.python.org/3?view=all")

    def test_discovery_helper_filters_irrelevant_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top_50_programming_languages_with_official_docs.txt").write_text("", encoding="utf-8")
            config = load_config(root)
            language = LanguageEntry(name="Python", source_url="https://docs.python.org/3/", slug="python")
            plan = PlannedSource(
                language=language,
                strategy="html_recursive",
                start_urls=["https://docs.python.org/3/"],
                allowed_domains=["docs.python.org"],
                allowed_path_prefixes=["/3"],
                ignored_url_patterns=["/search"],
            )
            helper = DiscoveryHelper(config, SiteAdapter(name="generic"), plan)
            self.assertTrue(helper.should_visit("https://docs.python.org/3/tutorial/index.html"))
            self.assertFalse(helper.should_visit("https://docs.python.org/3/search.html"))
            self.assertFalse(helper.should_visit("https://example.com/docs"))
            self.assertFalse(helper.should_visit("https://docs.python.org/3/_static/app.js"))


if __name__ == "__main__":
    unittest.main()
