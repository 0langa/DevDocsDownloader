from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from doc_ingest.config import load_config
from doc_ingest.models import CrawlMode, SourceRunDiagnostics
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.sources.base import AdapterEvent, Document, LanguageCatalog, document_events
from doc_ingest.utils.filesystem import read_json
from doc_ingest.version import app_version


def _long_markdown(title: str) -> str:
    body = (
        "This minimal smoke document exercises the installed package runtime, "
        "pipeline orchestration, markdown compilation, and report writing. "
    )
    return f"# {title}\n\n{body * 8}\n\n```python\nprint('minimal smoke')\n```\n"


def _catalog() -> LanguageCatalog:
    return LanguageCatalog(
        source="fixture",
        slug="smoke-lang",
        display_name="Smoke Lang",
        core_topics=["Reference"],
        all_topics=["Reference", "Guides"],
        homepage="https://example.invalid/smoke",
    )


def _documents() -> list[Document]:
    return [
        Document(
            topic="Reference",
            slug="intro",
            title="Intro",
            markdown=_long_markdown("Intro"),
            source_url="https://example.invalid/smoke/reference/intro",
            order_hint=10,
        ),
        Document(
            topic="Guides",
            slug="guide",
            title="Guide",
            markdown=_long_markdown("Guide"),
            source_url="https://example.invalid/smoke/guides/guide",
            order_hint=20,
        ),
    ]


@dataclass
class _FixtureSource:
    catalog: LanguageCatalog
    documents: list[Document]

    name: str = "fixture"

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return [self.catalog]

    async def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[Document]:
        selected = [document for document in self.documents if mode == "full" or document.topic in language.core_topics]
        if diagnostics is not None:
            diagnostics.discovered += len(self.documents)
            skipped = len(self.documents) - len(selected)
            if skipped:
                diagnostics.skip("filtered_mode", skipped)
        for document in selected:
            if diagnostics is not None:
                diagnostics.emitted += 1
            yield document

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics))


async def _run_smoke(root: Path) -> None:
    config = load_config(root=root)
    pipeline = DocumentationPipeline(config)
    source = _FixtureSource(_catalog(), _documents())
    report = await pipeline._run_language(
        source=source,
        catalog=source.catalog,
        mode="full",
        progress_tracker=None,
        validate_only=False,
    )

    language_dir = config.paths.markdown_dir / source.catalog.slug
    consolidated = language_dir / f"{source.catalog.slug}.md"
    meta = read_json(language_dir / "_meta.json", {})

    assert consolidated.exists(), "compiled markdown bundle missing"
    assert meta["language"] == source.catalog.display_name
    assert meta["source"] == source.name
    assert report.validation is not None
    assert report.validation.score > 0


def main() -> None:
    version = app_version()
    if not version:
        raise RuntimeError("app_version() returned an empty version string")

    with tempfile.TemporaryDirectory(prefix="devdocsdownloader-minimal-") as temp_dir:
        asyncio.run(_run_smoke(Path(temp_dir)))

    print(f"minimal smoke ok ({version})")


if __name__ == "__main__":
    main()
