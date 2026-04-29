from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias

from ..models import ResumeBoundary, SourceRunDiagnostics

CrawlMode = Literal["important", "full"]


@dataclass(slots=True)
class LanguageCatalog:
    source: str
    slug: str
    display_name: str
    version: str = ""
    core_topics: list[str] = field(default_factory=list)
    all_topics: list[str] = field(default_factory=list)
    size_hint: int = 0
    homepage: str = ""
    aliases: list[str] = field(default_factory=list)
    support_level: Literal["supported", "experimental", "ignored"] = "supported"
    discovery_reason: str = ""
    discovery_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    topic: str
    slug: str
    title: str
    markdown: str
    source_url: str = ""
    order_hint: int = 0


@dataclass(slots=True)
class DocumentEvent:
    document: Document


@dataclass(slots=True)
class WarningEvent:
    message: str
    source_url: str = ""
    code: str = "source_warning"


@dataclass(slots=True)
class DocumentWarningEvent:
    message: str
    code: str = "document_warning"
    source_url: str = ""
    topic: str = ""
    slug: str = ""
    title: str = ""
    order_hint: int | None = None


@dataclass(slots=True)
class SkippedEvent:
    reason: str
    count: int = 1
    source_url: str = ""


@dataclass(slots=True)
class SourceStatsEvent:
    discovered: int = 0
    emitted: int = 0


@dataclass(slots=True)
class AssetEvent:
    path: str
    source_url: str = ""
    media_type: str = ""
    content: bytes | None = None
    local_path: str = ""


AdapterEvent: TypeAlias = (
    DocumentEvent | WarningEvent | DocumentWarningEvent | SkippedEvent | SourceStatsEvent | AssetEvent
)


async def document_events(documents: AsyncIterator[Document]) -> AsyncIterator[AdapterEvent]:
    async for document in documents:
        yield DocumentEvent(document=document)


class DocumentationSource(Protocol):
    name: str

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]: ...

    def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Document]: ...

    def events(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
        resume_boundary: ResumeBoundary | None = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[AdapterEvent]: ...
