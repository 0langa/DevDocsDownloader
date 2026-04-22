from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


AssetType = Literal["html", "markdown", "pdf", "docx", "text", "binary", "unknown"]
FetchMethod = Literal["http", "browser", "cache"]
StatusType = Literal["pending", "discovered", "processed", "failed", "skipped"]
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
    ignored_path_prefixes: list[str] = Field(default_factory=list)
    ignored_url_patterns: list[str] = Field(default_factory=list)
    preferred_extractors: list[str] = Field(default_factory=list)
    content_selectors: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    include_changelog: bool = False
    honor_robots: bool = True
    max_depth: int = 8


class UrlRecord(BaseModel):
    url: str
    normalized_url: str
    depth: int = 0
    parent_url: str | None = None
    priority: int = 0
    discovered_from: str | None = None


class ExtractionMetrics(BaseModel):
    text_length: int = 0
    word_count: int = 0
    heading_count: int = 0
    code_block_count: int = 0
    table_count: int = 0
    link_line_ratio: float = 0.0
    repeated_line_ratio: float = 0.0
    boilerplate_ratio: float = 0.0
    malformed_ratio: float = 0.0
    blank_line_ratio: float = 0.0
    score: float = 0.0
    signals: list[str] = Field(default_factory=list)


class ExtractionDecision(BaseModel):
    extractor: str
    score: float
    won_because: list[str] = Field(default_factory=list)
    metrics: ExtractionMetrics = Field(default_factory=ExtractionMetrics)
    candidates: list[dict[str, Any]] = Field(default_factory=list)


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
    breadcrumbs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extraction: ExtractionDecision | None = None


class PageProcessResult(BaseModel):
    url: str
    status: StatusType
    message: str = ""
    document: ExtractedDocument | None = None


class QualityMetrics(BaseModel):
    structure_quality: float = 0.0
    duplication_ratio: float = 0.0
    noise_ratio: float = 0.0
    completeness: float = 0.0
    extraction_confidence: float = 0.0
    section_count: int = 0
    subsection_count: int = 0
    low_quality_pages: int = 0


class ValidationIssue(BaseModel):
    level: Literal["info", "warning", "error"]
    code: str
    message: str


class ValidationResult(BaseModel):
    language: str
    output_path: Path
    score: float
    quality_score: float = 0.0
    metrics: QualityMetrics = Field(default_factory=QualityMetrics)
    issues: list[ValidationIssue] = Field(default_factory=list)


class StageMetrics(BaseModel):
    duration_ms_total: float = 0.0
    items_total: int = 0
    failures_total: int = 0
    throughput_items_per_sec: float = 0.0


class QueueMetrics(BaseModel):
    depth_current: int = 0
    depth_avg: float = 0.0
    depth_hwm: int = 0


class ExtractionLatencyMetrics(BaseModel):
    count: int = 0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    histogram: dict[str, int] = Field(default_factory=dict)


class CacheMetrics(BaseModel):
    fetch_hits: int = 0
    fetch_misses: int = 0
    fetch_hit_rate: float = 0.0
    normalized_hits: int = 0
    normalized_misses: int = 0
    normalized_hit_rate: float = 0.0
    normalized_serialize_ms_total: float = 0.0
    normalized_deserialize_ms_total: float = 0.0
    normalized_bytes_written: int = 0


class WorkerMetrics(BaseModel):
    discover_workers: int = 0
    extraction_workers_current: int = 0
    extraction_workers_max: int = 0
    extraction_scale_events_total: int = 0
    extraction_busy_seconds: float = 0.0
    extraction_idle_seconds: float = 0.0
    extraction_busy_ratio: float = 0.0


class SystemMetrics(BaseModel):
    cpu_utilization_avg_pct: float = 0.0
    resident_memory_peak_mb: float = 0.0


class PerformanceMetrics(BaseModel):
    fetch: StageMetrics = Field(default_factory=StageMetrics)
    discover: StageMetrics = Field(default_factory=StageMetrics)
    extract: StageMetrics = Field(default_factory=StageMetrics)
    persist: StageMetrics = Field(default_factory=StageMetrics)
    queue_discover: QueueMetrics = Field(default_factory=QueueMetrics)
    queue_extract: QueueMetrics = Field(default_factory=QueueMetrics)
    extraction_latency: ExtractionLatencyMetrics = Field(default_factory=ExtractionLatencyMetrics)
    cache: CacheMetrics = Field(default_factory=CacheMetrics)
    workers: WorkerMetrics = Field(default_factory=WorkerMetrics)
    system: SystemMetrics = Field(default_factory=SystemMetrics)


class PageState(BaseModel):
    normalized_url: str
    discovered_url: str
    parent_url: str | None = None
    depth: int = 0
    discovered_from: str | None = None
    title: str | None = None
    status: StatusType = "discovered"
    asset_type: AssetType | None = None
    attempts: int = 0
    last_error: str | None = None
    extractor: str | None = None
    extraction_score: float | None = None
    extraction_notes: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    duplicate_of: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    source_order_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrawlState(BaseModel):
    language: str
    slug: str
    source_url: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    plan: dict[str, Any] = Field(default_factory=dict)
    pages: dict[str, PageState] = Field(default_factory=dict)
    compiled: bool = False
    compiled_at: datetime | None = None
    output_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class LanguageRunReport(BaseModel):
    language: str
    slug: str
    source_url: str
    strategy: str
    output_path: Path | None = None
    adapter: str = "generic"
    pages_discovered: int = 0
    pages_queued: int = 0
    pages_fetched: int = 0
    pages_processed: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    pages_deduplicated: int = 0
    assets_processed: int = 0
    extractor_choices: dict[str, int] = Field(default_factory=dict)
    warnings_by_code: dict[str, int] = Field(default_factory=dict)
    coverage_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    suspected_incompleteness: bool = False
    validation: ValidationResult | None = None
    performance: PerformanceMetrics = Field(default_factory=PerformanceMetrics)


class RunSummary(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reports: list[LanguageRunReport] = Field(default_factory=list)
