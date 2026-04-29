from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CrawlMode = Literal["important", "full"]
CheckpointPhase = Literal["initialized", "fetching", "compiling", "validating", "cancelling", "completed", "failed"]
CacheFreshnessPolicy = Literal["use-if-present", "ttl", "always-refresh", "validate-if-possible"]
BulkConcurrencyPolicy = Literal["static", "adaptive"]


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


class DocumentValidationResult(BaseModel):
    language: str
    source: str = ""
    source_slug: str = ""
    topic: str = ""
    slug: str = ""
    title: str = ""
    document_path: Path
    source_url: str = ""
    issues: list[ValidationIssue] = Field(default_factory=list)
    context: str = ""


class ValidationScoreComponents(BaseModel):
    completeness: float = 0.0
    structure: float = 0.0
    conversion: float = 0.0
    consistency: float = 0.0
    document_quality: float = 0.0


class ValidationResult(BaseModel):
    language: str
    output_path: Path
    score: float = 0.0
    quality_score: float = 0.0
    component_scores: ValidationScoreComponents | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    document_results: list[DocumentValidationResult] = Field(default_factory=list)


class SourceWarningRecord(BaseModel):
    code: str
    message: str
    source_url: str = ""
    topic: str = ""
    slug: str = ""
    title: str = ""
    order_hint: int | None = None


class RuntimeTelemetrySnapshot(BaseModel):
    requests: int = 0
    retries: int = 0
    bytes_observed: int = 0
    failures: int = 0
    cache_hits: int = 0
    cache_refreshes: int = 0


class AdaptiveBulkTelemetry(BaseModel):
    policy: BulkConcurrencyPolicy = "static"
    min_concurrency: int = 1
    max_concurrency: int = 1
    current_concurrency: int = 1
    adjustment_count: int = 0
    adjustment_reasons: list[str] = Field(default_factory=list)
    observed_windows: int = 0
    failed_languages: int = 0
    retry_pressure_windows: int = 0


class AssetRecord(BaseModel):
    source_url: str = ""
    media_type: str = ""
    original_path: str = ""
    output_path: str | None = None
    checksum: str = ""
    byte_count: int = 0
    status: Literal["copied", "referenced", "skipped"] = "referenced"
    reason: str = ""


class AssetInventorySummary(BaseModel):
    total: int = 0
    copied: int = 0
    referenced: int = 0
    skipped: int = 0
    manifest_path: str | None = None


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
    document_warnings: list[SourceWarningRecord] = Field(default_factory=list)
    runtime_telemetry: RuntimeTelemetrySnapshot | None = None
    asset_inventory: AssetInventorySummary | None = None
    failures: list[str] = Field(default_factory=list)


class DocumentCheckpoint(BaseModel):
    topic: str
    slug: str
    title: str
    source_url: str = ""
    order_hint: int = 0


class DocumentArtifactCheckpoint(DocumentCheckpoint):
    path: str
    fragment_path: str


class ResumeBoundary(BaseModel):
    document_inventory_position: int
    emitted_document_count: int


class CacheEntryMetadata(BaseModel):
    source: str
    cache_key: str
    url: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_version: str = ""
    etag: str = ""
    last_modified: str = ""
    checksum: str = ""
    byte_count: int = 0
    policy: CacheFreshnessPolicy = "use-if-present"
    refreshed_by_force: bool = False


class CacheDecision(BaseModel):
    should_refresh: bool
    reason: str
    policy: CacheFreshnessPolicy = "use-if-present"
    metadata: CacheEntryMetadata | None = None


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
    emitted_documents: list[DocumentArtifactCheckpoint] = Field(default_factory=list)
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
    document_warnings: list[SourceWarningRecord] = Field(default_factory=list)
    runtime_telemetry: RuntimeTelemetrySnapshot | None = None
    asset_inventory: AssetInventorySummary | None = None
    failures: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


class RunSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reports: list[LanguageRunReport] = Field(default_factory=list)
    adaptive_telemetry: AdaptiveBulkTelemetry | None = None
