from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from doc_ingest.models import CrawlMode, SourceRunDiagnostics
from doc_ingest.sources.base import AdapterEvent, Document, LanguageCatalog, document_events

LONG_BODY = (
    "This fixture paragraph is intentionally verbose so the validator sees a "
    "realistic compiled manual rather than a tiny smoke output. It describes "
    "stable contract behavior, deterministic ordering, source URLs, topic "
    "sections, and markdown normalization across the generated files. "
)


def long_markdown(title: str, *, repeat: int = 8) -> str:
    return f"# {title}\n\n" + (LONG_BODY * repeat) + "\n\n```python\nprint('fixture')\n```\n"


def contract_documents() -> list[Document]:
    return [
        Document(
            topic="Reference",
            slug="std::vector",
            title="Vector API",
            markdown=long_markdown("Vector API"),
            source_url="https://example.invalid/reference/vector",
            order_hint=10,
        ),
        Document(
            topic="Reference",
            slug="std/vector",
            title="Vector Guide",
            markdown=long_markdown("Vector Guide"),
            source_url="https://example.invalid/reference/vector-guide",
            order_hint=20,
        ),
        Document(
            topic="Guides",
            slug="COM1",
            title="Getting Started",
            markdown=long_markdown("Getting Started"),
            source_url="https://example.invalid/guides/start",
            order_hint=30,
        ),
    ]


def synthetic_catalog(*, source: str = "fixture") -> LanguageCatalog:
    return LanguageCatalog(
        source=source,
        slug="synthetic-lang",
        display_name="Synthetic Lang",
        core_topics=["Reference"],
        all_topics=["Reference", "Guides"],
        homepage="https://example.invalid/synthetic",
    )


@dataclass
class FixtureSource:
    name: str
    catalog: LanguageCatalog
    documents: list[Document]
    fail_after: int | None = None
    skip_reason: str | None = None

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
                diagnostics.skip(self.skip_reason or "filtered_mode", skipped)
        for index, document in enumerate(selected, start=1):
            if diagnostics is not None:
                diagnostics.emitted += 1
            yield Document(
                topic=document.topic,
                slug=document.slug,
                title=document.title,
                markdown=document.markdown,
                source_url=document.source_url,
                order_hint=document.order_hint,
            )
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("fixture source interrupted")

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics))


def normalize_contract_text(text: str, root: Path) -> str:
    normalized = text.replace(str(root), "[ROOT]")
    normalized = normalized.replace(str(root).replace("\\", "/"), "[ROOT]")
    normalized = normalized.replace(LONG_BODY * 8, "[LONG_BODY]")
    normalized = re.sub(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00",
        "[TIMESTAMP]",
        normalized,
    )
    normalized = re.sub(r'"duration_seconds":\s*[0-9.]+', '"duration_seconds": [DURATION]', normalized)
    normalized = re.sub(r"- Duration \(s\): [0-9.]+", "- Duration (s): [DURATION]", normalized)
    return normalized
