from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


AssetType = Literal["html", "markdown", "pdf", "docx", "text", "binary", "unknown"]
FetchMethod = Literal["http", "browser", "cache"]
StatusType = Literal["pending", "processed", "failed", "skipped"]
CrawlMode = Literal["important", "full"]


class LanguageEntry(BaseModel):
    name: str
    source_url: HttpUrl
    slug: str


class PlannedSource(BaseModel):
    language: LanguageEntry
    strategy: str
    crawl_mode: CrawlMode = "full"
    start_urls: list[str]
    notes: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_path_prefixes: list[str] = Field(default_factory=list)
    max_depth: int = 8


class UrlRecord(BaseModel):
    url: str
    normalized_url: str
    depth: int = 0
    parent_url: str | None = None
    priority: int = 0
    discovered_from: str | None = None


class FetchResult(BaseModel):
    url: str
    final_url: str
    content_type: str
    status_code: int
    method: FetchMethod
    content: bytes
    history_status_codes: list[int] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractedDocument(BaseModel):
    url: str
    final_url: str
    title: str
    markdown: str
    asset_type: AssetType
    headings: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    word_count: int = 0
    content_hash: str
    source_order_hint: str = ""


class PageProcessResult(BaseModel):
    url: str
    status: StatusType
    message: str = ""
    document: ExtractedDocument | None = None


class ValidationIssue(BaseModel):
    level: Literal["info", "warning", "error"]
    code: str
    message: str


class ValidationResult(BaseModel):
    language: str
    output_path: Path
    score: float
    issues: list[ValidationIssue] = Field(default_factory=list)


class LanguageRunReport(BaseModel):
    language: str
    slug: str
    source_url: str
    strategy: str
    output_path: Path | None = None
    pages_discovered: int = 0
    pages_processed: int = 0
    assets_processed: int = 0
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    suspected_incompleteness: bool = False
    validation: ValidationResult | None = None


class RunSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reports: list[LanguageRunReport] = Field(default_factory=list)