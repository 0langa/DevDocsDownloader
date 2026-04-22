from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


CrawlMode = Literal["important", "full"]


class TopicStats(BaseModel):
    topic: str
    document_count: int = 0


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
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    topics: list[TopicStats] = Field(default_factory=list)
    total_documents: int = 0
    output_path: str | None = None
    completed: bool = False
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class LanguageRunReport(BaseModel):
    language: str
    slug: str
    source: str
    source_slug: str
    source_url: str = ""
    mode: CrawlMode = "important"
    output_path: Path | None = None
    total_documents: int = 0
    topics: list[TopicStats] = Field(default_factory=list)
    validation: ValidationResult | None = None
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


class RunSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reports: list[LanguageRunReport] = Field(default_factory=list)
