from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol

from ..models import SourceRunDiagnostics

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


@dataclass(slots=True)
class Document:
    topic: str
    slug: str
    title: str
    markdown: str
    source_url: str = ""
    order_hint: int = 0


class DocumentationSource(Protocol):
    name: str

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]: ...

    def fetch(
        self,
        language: LanguageCatalog,
        mode: CrawlMode,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[Document]: ...
