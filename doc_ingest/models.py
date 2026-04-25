from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CrawlMode = Literal["important", "full"]
CheckpointPhase = Literal["initialized", "fetching", "compiling", "validating", "completed", "failed"]


class TopicStats(BaseModel):
    topic: str
    document_count: int = 0


class SourceRunDiagnostics(BaseModel):
    discovered: int = 0
    emitted: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)

    def skip(self, reason: str, count: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + count


class ValidationIssue(BaseModel):
    level: Literal["info", "warning", "error"]
    code: str
    message: str


class ValidationResult(BaseModel):
    language: str
    output_path: Path
    score: float = 0.0
    quality_score: float = 0.0
    issues: list[ValidationIssue] = Field(default_factory=list)


class LanguageRunState(BaseModel):
    language: str
    slug: str
    source: str
    source_slug: str
    source_url: str = ""
    mode: CrawlMode = "important"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    topics: list[TopicStats] = Field(default_factory=list)
    total_documents: int = 0
    source_diagnostics: SourceRunDiagnostics | None = None
    output_path: str | None = None
    completed: bool = False
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class DocumentCheckpoint(BaseModel):
    topic: str
    slug: str
    title: str
    source_url: str = ""
    order_hint: int = 0


class CheckpointFailure(BaseModel):
    phase: CheckpointPhase
    error_type: str
    message: str
    document_inventory_position: int | None = None
    emitted_document_count: int = 0
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LanguageRunCheckpoint(BaseModel):
    language: str
    slug: str
    source: str
    source_slug: str
    source_url: str = ""
    mode: CrawlMode = "important"
    phase: CheckpointPhase = "initialized"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    document_inventory_position: int | None = None
    emitted_document_count: int = 0
    output_path: str | None = None
    last_document: DocumentCheckpoint | None = None
    failures: list[CheckpointFailure] = Field(default_factory=list)


class LanguageRunReport(BaseModel):
    language: str
    slug: str
    source: str
    source_slug: str
    source_url: str = ""
    mode: CrawlMode = "important"
    output_path: Path | None = None
    total_documents: int = 0
    source_diagnostics: SourceRunDiagnostics | None = None
    topics: list[TopicStats] = Field(default_factory=list)
    validation: ValidationResult | None = None
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


class RunSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reports: list[LanguageRunReport] = Field(default_factory=list)
