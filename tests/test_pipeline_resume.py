from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.models import CrawlState, FetchResult, PageState
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.state import CrawlStateStore


class _FakeHttpFetcher:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages

    def set_adaptive_controller(self, _controller) -> None:
        return None

    async def close(self) -> None:
        return None

    async def fetch(self, url: str, _cache_dir: Path) -> FetchResult:
        content = self.pages[url]
        return FetchResult(
            url=url,
            final_url=url,
            content_type="text/html",
            status_code=200,
            method="http",
            content=content,
        )


class _FakeBrowserFetcher:
    async def close(self) -> None:
        return None

    async def fetch(self, _url: str, _cache_dir: Path) -> FetchResult:
        raise AssertionError("Browser fetch should not be used in this test")


class PipelineResumeTests(unittest.TestCase):
    def test_state_store_migrates_legacy_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "python.json"
            state_path.write_text(
                json.dumps(
                    {
                        "processed": {
                            "https://docs.python.org/3/tutorial": {
                                "title": "Tutorial",
                                "hash": "abc123",
                                "asset_type": "html",
                            }
                        },
                        "failed": {
                            "https://docs.python.org/3/broken": "HTTP 500",
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = CrawlStateStore(
                state_path,
                language="Python",
                slug="python",
                source_url="https://docs.python.org/3/",
            )

            state = store.load()

            self.assertEqual(state.language, "Python")
            self.assertIn("https://docs.python.org/3/tutorial", state.pages)
            self.assertEqual(state.pages["https://docs.python.org/3/tutorial"].status, "processed")
            self.assertEqual(state.pages["https://docs.python.org/3/tutorial"].content_hash, "abc123")
            self.assertIn("https://docs.python.org/3/broken", state.pages)
            self.assertEqual(state.pages["https://docs.python.org/3/broken"].status, "failed")

    def test_pipeline_writes_resumable_state_and_output(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_documents = root / "source-documents"
                source_documents.mkdir(parents=True, exist_ok=True)
                (source_documents / "renamed-link-source.md").write_text(
                    "- Python - https://docs.python.org/3/\n",
                    encoding="utf-8",
                )
                config = load_config(root)
                config.crawl.browser_enabled = False
                config.crawl.max_concurrency = 1
                config.crawl.max_discovered_urls_per_language = 8
                pages = {
                    "https://docs.python.org/3": b"""
                    <html><head><title>Python</title></head><body><main>
                    <h1>Python</h1><p>Intro text for python docs with enough useful prose to survive quality checks and normalization without being marked as noise.</p>
                    <a href=\"https://docs.python.org/3/tutorial\">Tutorial</a>
                    </main></body></html>
                    """,
                    "https://docs.python.org/3/tutorial": b"""
                    <html><head><title>Tutorial</title></head><body><main>
                    <h1>Tutorial</h1><p>Tutorial body with enough useful text to be kept and processed by the resumable pipeline during the test run.</p>
                    </main></body></html>
                    """,
                }
                pipeline = DocumentationPipeline(config)
                pipeline.http_fetcher = _FakeHttpFetcher(pages)
                pipeline.browser_fetcher = _FakeBrowserFetcher()
                try:
                    summary = await pipeline.run(language_name="python")
                finally:
                    await pipeline.close()
                report = summary.reports[0]
                self.assertEqual(report.pages_processed, 2)
                self.assertTrue(report.output_path and report.output_path.exists())
                self.assertIsNotNone(report.validation)
                self.assertGreater(report.validation.quality_score, 0.4)
                self.assertGreater(report.performance.fetch.items_total, 0)
                self.assertGreater(report.performance.extract.items_total, 0)
                self.assertGreaterEqual(report.performance.queue_discover.depth_hwm, 1)
                self.assertGreaterEqual(report.performance.queue_extract.depth_hwm, 0)
                self.assertGreaterEqual(report.performance.extraction_latency.count, report.performance.extract.items_total)
                state_path = config.paths.state_dir / "python.json"
                self.assertTrue(state_path.exists())
                state_text = state_path.read_text(encoding="utf-8")
                self.assertIn('"compiled": true', state_text.lower())

        asyncio.run(run_case())

    def test_state_store_skips_invalid_page_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "python.json"
            state_path.write_text(
                json.dumps(
                    {
                        "language": "Python",
                        "slug": "python",
                        "source_url": "https://docs.python.org/3/",
                        "pages": {
                            "https://docs.python.org/3/ok": {
                                "normalized_url": "https://docs.python.org/3/ok",
                                "discovered_url": "https://docs.python.org/3/ok",
                                "status": "processed",
                            },
                            "https://docs.python.org/3/bad": {
                                "status": "processed"
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = CrawlStateStore(state_path, language="Python", slug="python", source_url="https://docs.python.org/3/")
            state = store.load()
            self.assertIn("https://docs.python.org/3/ok", state.pages)
            self.assertNotIn("https://docs.python.org/3/bad", state.pages)

    def test_pipeline_respects_max_pages_limit(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_documents = root / "source-documents"
                source_documents.mkdir(parents=True, exist_ok=True)
                (source_documents / "renamed-link-source.md").write_text(
                    "- Python - https://docs.python.org/3/\n",
                    encoding="utf-8",
                )
                config = load_config(root)
                config.crawl.browser_enabled = False
                config.crawl.max_concurrency = 1
                config.crawl.max_pages_per_language = 1
                pages = {
                    "https://docs.python.org/3": b"""
                    <html><head><title>Python</title></head><body><main>
                    <h1>Python</h1><p>Intro text for python docs with enough useful prose to survive quality checks and normalization.</p>
                    <a href=\"https://docs.python.org/3/tutorial\">Tutorial</a>
                    </main></body></html>
                    """,
                    "https://docs.python.org/3/tutorial": b"""
                    <html><head><title>Tutorial</title></head><body><main>
                    <h1>Tutorial</h1><p>Tutorial body with enough text to be processed if discovered.</p>
                    </main></body></html>
                    """,
                }
                pipeline = DocumentationPipeline(config)
                pipeline.http_fetcher = _FakeHttpFetcher(pages)
                pipeline.browser_fetcher = _FakeBrowserFetcher()
                try:
                    summary = await pipeline.run(language_name="python", force_refresh=True)
                finally:
                    await pipeline.close()

                report = summary.reports[0]
                self.assertEqual(report.pages_processed, 1)
                state_path = config.paths.state_dir / "python.json"
                state = CrawlStateStore(
                    state_path,
                    language="Python",
                    slug="python",
                    source_url="https://docs.python.org/3/",
                ).load()
                self.assertEqual(len(state.pages), 1)

        asyncio.run(run_case())

    def test_pipeline_does_not_stall_when_seed_url_is_already_processed(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_documents = root / "source-documents"
                source_documents.mkdir(parents=True, exist_ok=True)
                (source_documents / "renamed-link-source.md").write_text(
                    "- Python - https://docs.python.org/3/\n",
                    encoding="utf-8",
                )
                config = load_config(root)
                config.crawl.browser_enabled = False
                config.crawl.max_concurrency = 1
                config.crawl.max_extraction_workers = 1
                config.crawl.max_pending_extractions_per_language = 4
                state_store = CrawlStateStore(
                    config.paths.state_dir / "python.json",
                    language="Python",
                    slug="python",
                    source_url="https://docs.python.org/3/",
                )
                state = CrawlState(
                    language="Python",
                    slug="python",
                    source_url="https://docs.python.org/3/",
                    pages={
                        "https://docs.python.org/3": PageState(
                            normalized_url="https://docs.python.org/3",
                            discovered_url="https://docs.python.org/3",
                            status="processed",
                            content_hash="seed-hash",
                        ),
                        "https://docs.python.org/3/tutorial": PageState(
                            normalized_url="https://docs.python.org/3/tutorial",
                            discovered_url="https://docs.python.org/3/tutorial",
                            parent_url="https://docs.python.org/3",
                            depth=1,
                            status="pending",
                        ),
                    },
                )
                state_store.save(state)

                pages = {
                    "https://docs.python.org/3/tutorial": b"""
                    <html><head><title>Tutorial</title></head><body><main>
                    <h1>Tutorial</h1><p>Tutorial body with enough useful text to be processed after resume.</p>
                    </main></body></html>
                    """,
                }
                pipeline = DocumentationPipeline(config)
                pipeline.http_fetcher = _FakeHttpFetcher(pages)
                pipeline.browser_fetcher = _FakeBrowserFetcher()
                try:
                    summary = await asyncio.wait_for(pipeline.run(language_name="python"), timeout=10.0)
                finally:
                    await pipeline.close()
                report = summary.reports[0]
                self.assertGreaterEqual(report.pages_processed, 1)

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
