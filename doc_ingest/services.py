from __future__ import annotations

import json
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import AppConfig
from .models import (
    BulkConcurrencyPolicy,
    CacheEntryMetadata,
    CacheFreshnessPolicy,
    CrawlMode,
    DryRunResult,
    FailureDetail,
    LanguageRunCheckpoint,
    RunSummary,
)
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker
from .runtime import SourceRuntime
from .sources.presets import PRESETS
from .sources.registry import SourceRegistry
from .state import load_checkpoint_payload
from .utils.filesystem import read_json


class ServiceEvent(BaseModel):
    event_type: Literal[
        "phase_change",
        "activity",
        "document_emitted",
        "warning",
        "validation_completed",
        "runtime_telemetry",
        "failure",
    ]
    language: str = ""
    phase: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


ServiceEventSink = Callable[[ServiceEvent], None | Awaitable[None]]


class RunLanguageRequest(BaseModel):
    language: str
    mode: CrawlMode = "important"
    source: str | None = None
    force_refresh: bool = False
    validate_only: bool = False
    include_topics: list[str] | None = None
    exclude_topics: list[str] | None = None
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
    chunk_strategy: Literal["chars", "tokens"] = "chars"
    chunk_max_tokens: int = 1_000
    chunk_overlap_tokens: int = 100
    cache_policy: CacheFreshnessPolicy = "use-if-present"
    cache_ttl_hours: int | None = None
    dry_run: bool = False


class BulkRunRequest(BaseModel):
    languages: list[str]
    mode: CrawlMode = "important"
    source: str | None = None
    force_refresh: bool = False
    language_concurrency: int = 3
    concurrency_policy: BulkConcurrencyPolicy = "static"
    adaptive_min_concurrency: int = 1
    adaptive_max_concurrency: int = 6
    include_topics: list[str] | None = None
    exclude_topics: list[str] | None = None
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
    chunk_strategy: Literal["chars", "tokens"] = "chars"
    chunk_max_tokens: int = 1_000
    chunk_overlap_tokens: int = 100
    cache_policy: CacheFreshnessPolicy = "use-if-present"
    cache_ttl_hours: int | None = None


class LanguageEntry(BaseModel):
    language: str
    source: str
    slug: str
    version: str = ""
    size_hint: int | None = None
    discovery_metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: str = ""
    preferred_source: bool = False
    latest_validation_score: float | None = None
    quality_trend: str = ""


class SourceHealthEntry(BaseModel):
    status: str
    last_checked: str
    catalog_age_hours: float = 0.0
    circuit_breaker: str = "closed"
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AuditPresetResult(BaseModel):
    preset: str
    language: str
    resolved: bool
    source: str = ""
    slug: str = ""


class CatalogAuditResult(BaseModel):
    source: str
    path: Path | None = None
    source_root_url: str = ""
    discovery_strategy: str = ""
    fetched_at: str = ""
    total_entries: int = 0
    supported_entries: int = 0
    experimental_entries: int = 0
    ignored_entries: int = 0
    fallback_used: bool = False
    fallback_reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CatalogRefreshResult(BaseModel):
    source: str
    status: Literal["refreshed", "fallback", "failed"]
    entry_count: int = 0
    supported_entries: int = 0
    experimental_entries: int = 0
    ignored_entries: int = 0
    discovery_strategy: str = ""
    fetched_at: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RuntimeSnapshot(BaseModel):
    states: list[Path] = Field(default_factory=list)
    checkpoints: list[Path] = Field(default_factory=list)
    reports: list[Path] = Field(default_factory=list)
    history_reports: list[Path] = Field(default_factory=list)
    trend_reports: list[Path] = Field(default_factory=list)


class OutputBundleSummary(BaseModel):
    language_slug: str
    path: Path
    language: str = ""
    source: str = ""
    source_slug: str = ""
    mode: str = ""
    total_documents: int = 0
    generated_at: str = ""
    bundle_bytes: int = 0
    file_count: int = 0
    chunk_count: int = 0
    topics: list[dict[str, Any]] = Field(default_factory=list)
    has_chunks: bool = False
    has_frontmatter: bool = False
    latest_quality: dict[str, Any] = Field(default_factory=dict)


class OutputStorageSummary(BaseModel):
    output_root: Path
    bundle_count: int = 0
    total_bundle_bytes: int = 0
    latest_reports_bytes: int = 0
    history_reports_bytes: int = 0
    history_report_count: int = 0
    validation_records_bytes: int = 0
    trends_bytes: int = 0
    total_managed_bytes: int = 0


class StorageCleanupResult(BaseModel):
    target: str
    deleted: bool = False
    freed_bytes: int = 0
    deleted_files: int = 0
    deleted_directories: int = 0


class OutputTreeNode(BaseModel):
    name: str
    path: Path
    relative_path: str
    is_dir: bool
    size: int = 0
    children: list[OutputTreeNode] = Field(default_factory=list)


class OutputFileContent(BaseModel):
    path: Path
    relative_path: str
    media_type: str
    content: str


class ReportBundle(BaseModel):
    latest_json_path: Path | None = None
    latest_markdown_path: Path | None = None
    validation_documents_path: Path | None = None
    trends_json_path: Path | None = None
    trends_markdown_path: Path | None = None
    history_reports: list[Path] = Field(default_factory=list)
    latest_json: dict[str, Any] = Field(default_factory=dict)
    latest_markdown: str = ""
    validation_documents: list[dict[str, Any]] = Field(default_factory=list)
    trends_json: dict[str, Any] = Field(default_factory=dict)
    trends_markdown: str = ""
    quality_trends: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class CheckpointSummary(BaseModel):
    language: str
    slug: str
    source: str
    source_slug: str
    mode: str
    phase: str
    path: Path
    emitted_document_count: int = 0
    document_inventory_position: int | None = None
    output_path: str | None = None
    updated_at: str = ""
    age_seconds: int = 0
    failure_count: int = 0
    is_stale: bool = False
    stale_reason: str = ""


class CacheMetadataSummary(BaseModel):
    path: Path
    source: str = ""
    cache_key: str = ""
    url: str = ""
    fetched_at: str = ""
    source_version: str = ""
    checksum: str = ""
    byte_count: int = 0
    policy: str = ""
    refreshed_by_force: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class CacheEntrySummary(BaseModel):
    source: str
    slug: str
    cache_key: str
    path: str
    byte_count: int = 0
    fetched_at: str = ""
    policy: str = ""
    next_refresh_due: str = ""
    source_version: str = ""
    checksum: str = ""
    refreshed_by_force: bool = False


class CacheSourceSummary(BaseModel):
    source: str
    total_bytes: int = 0
    entry_count: int = 0
    oldest_entry_at: str = ""
    newest_entry_at: str = ""


class CacheSummaryBundle(BaseModel):
    cache_root: Path
    total_bytes: int = 0
    max_cache_size_mb: int = 2048
    max_cache_size_bytes: int = 2_147_483_648
    sources: list[CacheSourceSummary] = Field(default_factory=list)
    entries: list[CacheEntrySummary] = Field(default_factory=list)


class DocumentationService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def run_language(
        self,
        request: RunLanguageRequest,
        *,
        progress_tracker: CrawlProgressTracker | None = None,
        event_sink: ServiceEventSink | None = None,
    ) -> RunSummary | DryRunResult:
        self._apply_output_options(request)
        await _emit(event_sink, ServiceEvent(event_type="phase_change", language=request.language, phase="started"))
        progress_tracker = progress_tracker or _DesktopProgressTracker(event_sink)
        pipeline = DocumentationPipeline(self.config)
        try:
            if request.dry_run:
                result = await pipeline.dry_run(
                    language_name=request.language,
                    mode=request.mode,
                    source_name=request.source,
                    force_refresh=request.force_refresh,
                    include_topics=request.include_topics,
                    exclude_topics=request.exclude_topics,
                )
                await _emit(
                    event_sink,
                    ServiceEvent(
                        event_type="activity",
                        language=request.language,
                        message=(
                            f"Preview ready: {result.source} / {result.slug} "
                            f"({result.estimated_document_count if result.estimated_document_count is not None else 'unknown'} docs)"
                        ),
                    ),
                )
                await _emit(
                    event_sink, ServiceEvent(event_type="phase_change", language=request.language, phase="completed")
                )
                return result
            summary = await pipeline.run(
                language_name=request.language,
                mode=request.mode,
                source_name=request.source,
                force_refresh=request.force_refresh,
                progress_tracker=progress_tracker,
                validate_only=request.validate_only,
                include_topics=request.include_topics,
                exclude_topics=request.exclude_topics,
            )
            await self._emit_summary_events(summary, event_sink=event_sink)
            await _emit(
                event_sink, ServiceEvent(event_type="phase_change", language=request.language, phase="completed")
            )
            return summary
        except Exception as exc:
            await _emit(
                event_sink,
                ServiceEvent(
                    event_type="failure",
                    language=request.language,
                    message=f"{type(exc).__name__}: {exc}",
                    payload=_failure_payload(
                        FailureDetail(
                            code="runtime_error",
                            message=f"{type(exc).__name__}: {exc}",
                            hint="Check the run log for the full stack trace.",
                            is_retriable=False,
                        )
                    ),
                ),
            )
            raise
        finally:
            await pipeline.close()

    async def run_bulk(
        self,
        request: BulkRunRequest,
        *,
        progress_tracker: CrawlProgressTracker | None = None,
        event_sink: ServiceEventSink | None = None,
    ) -> RunSummary:
        self._apply_output_options(request)
        self.config.language_concurrency = max(1, request.language_concurrency)
        self.config.bulk_concurrency_policy = request.concurrency_policy
        self.config.adaptive_min_concurrency = max(1, request.adaptive_min_concurrency)
        self.config.adaptive_max_concurrency = max(
            self.config.adaptive_min_concurrency, request.adaptive_max_concurrency
        )
        await _emit(event_sink, ServiceEvent(event_type="phase_change", phase="bulk_started"))
        progress_tracker = progress_tracker or _DesktopProgressTracker(event_sink)
        pipeline = DocumentationPipeline(self.config)
        try:
            summary = await pipeline.run_many(
                language_names=request.languages,
                mode=request.mode,
                source_name=request.source,
                force_refresh=request.force_refresh,
                progress_tracker=progress_tracker,
                language_concurrency=request.language_concurrency,
                concurrency_policy=request.concurrency_policy,
                adaptive_min_concurrency=request.adaptive_min_concurrency,
                adaptive_max_concurrency=request.adaptive_max_concurrency,
                include_topics=request.include_topics,
                exclude_topics=request.exclude_topics,
            )
            await self._emit_summary_events(summary, event_sink=event_sink)
            await _emit(event_sink, ServiceEvent(event_type="phase_change", phase="bulk_completed"))
            return summary
        except Exception as exc:
            await _emit(
                event_sink,
                ServiceEvent(
                    event_type="failure",
                    message=f"{type(exc).__name__}: {exc}",
                    payload=_failure_payload(
                        FailureDetail(
                            code="runtime_error",
                            message=f"{type(exc).__name__}: {exc}",
                            hint="Check the run log for the full stack trace.",
                            is_retriable=False,
                        )
                    ),
                ),
            )
            raise
        finally:
            await pipeline.close()

    async def list_languages(self, *, source: str | None = None, force_refresh: bool = False) -> list[LanguageEntry]:
        registry = self._registry()
        quality_rows = self._read_quality_history()
        latest_quality_by_key = self._latest_quality_by_source_slug(quality_rows)
        preferred_for_language = self._preferred_source_by_language(quality_rows)
        try:
            catalogs = await registry.catalog(force_refresh=force_refresh, source_name=source)
        finally:
            await registry.runtime.close()
        rows: list[LanguageEntry] = []
        for source_name, entries in catalogs.items():
            if source and source_name != source:
                continue
            for entry in entries:
                rows.append(
                    LanguageEntry(
                        language=entry.display_name,
                        source=source_name,
                        slug=entry.slug,
                        version=entry.version or "",
                        size_hint=entry.size_hint or None,
                        discovery_metadata=dict(entry.discovery_metadata or {}),
                        confidence=str(entry.discovery_metadata.get("confidence") or ""),
                        preferred_source=preferred_for_language.get(entry.display_name.strip().lower(), "")
                        == source_name,
                        latest_validation_score=latest_quality_by_key.get((source_name, entry.slug), {}).get(
                            "validation_score"
                        ),
                        quality_trend=self._trend_for_language(quality_rows, entry.display_name),
                    )
                )
        return sorted(rows, key=lambda item: (item.language.lower(), item.source))

    async def source_health(self) -> dict[str, SourceHealthEntry]:
        now = datetime.now(UTC)
        breaker: dict[str, dict[str, Any]] = {}
        out: dict[str, SourceHealthEntry] = {}
        for source in ("devdocs", "mdn", "dash", "web_page"):
            manifest_path = self.config.paths.cache_dir / "catalogs" / f"{source}.json"
            age_hours = 0.0
            status = "ok"
            reason = ""
            details: dict[str, Any] = {}
            if manifest_path.exists():
                payload = read_json(manifest_path, {})
                fetched_at = str(payload.get("fetched_at") or "")
                if fetched_at:
                    try:
                        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                        age_hours = max(0.0, (now - fetched).total_seconds() / 3600.0)
                    except ValueError:
                        pass
                if bool(payload.get("fallback_used", False)):
                    status = "degraded"
                    reason = str(payload.get("fallback_reason") or "catalog fallback used")
                if source == "mdn":
                    details["commit_sha"] = str(payload.get("diagnostics", {}).get("current_commit", ""))
            else:
                status = "degraded"
                reason = "catalog missing"
            domain_state = _source_breaker_state(source, breaker)
            if domain_state["state"] == "open":
                status = "failed"
            elif status == "ok" and age_hours > 24 * 7:
                status = "degraded"
                reason = reason or "catalog stale"
            out[source] = SourceHealthEntry(
                status=status,
                last_checked=now.isoformat(),
                catalog_age_hours=round(age_hours, 2),
                circuit_breaker=domain_state["state"],
                reason=reason or domain_state["last_failure_reason"],
                details=details,
            )
        return out

    async def refresh_catalogs(self) -> list[CatalogRefreshResult]:
        registry = self._registry()
        results: list[CatalogRefreshResult] = []
        try:
            for source in registry.sources:
                errors: list[str] = []
                entry_count = 0
                try:
                    entries = await source.list_languages(force_refresh=True)
                    entry_count = len(entries)
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                results.append(self._catalog_refresh_result(source=source.name, entry_count=entry_count, errors=errors))
        finally:
            await registry.runtime.close()
        return results

    def audit_source_catalogs(self) -> list[CatalogAuditResult]:
        results: list[CatalogAuditResult] = []
        catalogs_root = self.config.paths.cache_dir / "catalogs"
        for path in sorted(catalogs_root.glob("*.json")):
            payload = read_json(path, {})
            entries = payload.get("entries") if isinstance(payload, dict) else []
            if not isinstance(entries, list):
                entries = []
            support_levels = [
                str(entry.get("support_level") or "supported") for entry in entries if isinstance(entry, dict)
            ]
            results.append(
                CatalogAuditResult(
                    source=str(payload.get("source") or path.stem),
                    path=path,
                    source_root_url=str(payload.get("source_root_url") or ""),
                    discovery_strategy=str(payload.get("discovery_strategy") or ""),
                    fetched_at=str(payload.get("fetched_at") or ""),
                    total_entries=len(entries),
                    supported_entries=sum(1 for level in support_levels if level == "supported"),
                    experimental_entries=sum(1 for level in support_levels if level == "experimental"),
                    ignored_entries=sum(1 for level in support_levels if level == "ignored"),
                    fallback_used=bool(payload.get("fallback_used", False)),
                    fallback_reason=str(payload.get("fallback_reason") or ""),
                    warnings=[str(item) for item in payload.get("warnings") or []],
                    errors=[str(item) for item in payload.get("errors") or []],
                )
            )
        return results

    async def audit_presets(
        self,
        *,
        presets: list[str] | None = None,
        source: str | None = None,
        force_refresh: bool = False,
    ) -> list[AuditPresetResult]:
        names = presets or sorted(PRESETS.keys())
        registry = self._registry()
        results: list[AuditPresetResult] = []
        try:
            for preset in names:
                for language in PRESETS[preset]:
                    match = await registry.resolve(language, source_name=source, force_refresh=force_refresh)
                    if match is None:
                        results.append(AuditPresetResult(preset=preset, language=language, resolved=False))
                        continue
                    matched_source, catalog = match
                    results.append(
                        AuditPresetResult(
                            preset=preset,
                            language=language,
                            resolved=True,
                            source=matched_source.name,
                            slug=catalog.slug,
                        )
                    )
        finally:
            await registry.runtime.close()
        return results

    def list_presets(self) -> dict[str, list[str]]:
        return {name: list(languages) for name, languages in sorted(PRESETS.items())}

    def inspect_runtime(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            states=sorted(self.config.paths.state_dir.glob("*.json")),
            checkpoints=sorted(self.config.paths.checkpoints_dir.glob("*.json")),
            reports=sorted(self.config.paths.reports_dir.glob("run_summary.*")),
            history_reports=sorted((self.config.paths.reports_dir / "history").glob("*-run_summary.json")),
            trend_reports=[
                path
                for path in [
                    self.config.paths.reports_dir / "trends.json",
                    self.config.paths.reports_dir / "trends.md",
                    self.config.paths.reports_dir / "validation_documents.jsonl",
                ]
                if path.exists()
            ],
        )

    def list_output_bundles(self) -> list[OutputBundleSummary]:
        bundles: list[OutputBundleSummary] = []
        root = self.config.paths.markdown_dir
        if not root.exists():
            return bundles
        for language_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            meta_path = language_dir / "_meta.json"
            raw_meta = read_json(meta_path, {}) if meta_path.exists() else {}
            meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
            raw_outputs = meta.get("outputs")
            outputs: dict[str, Any] = raw_outputs if isinstance(raw_outputs, dict) else {}
            bundle_bytes, file_count = _path_usage(language_dir)
            chunk_manifest = language_dir / "chunks" / "manifest.jsonl"
            chunk_count = len(chunk_manifest.read_text(encoding="utf-8").splitlines()) if chunk_manifest.exists() else 0
            bundles.append(
                OutputBundleSummary(
                    language_slug=language_dir.name,
                    path=language_dir,
                    language=str(meta.get("language") or language_dir.name),
                    source=str(meta.get("source") or ""),
                    source_slug=str(meta.get("source_slug") or ""),
                    mode=str(meta.get("mode") or ""),
                    total_documents=int(meta.get("total_documents") or 0),
                    generated_at=str(meta.get("generated_at") or ""),
                    bundle_bytes=bundle_bytes,
                    file_count=file_count,
                    chunk_count=chunk_count,
                    topics=list(meta.get("topics") or []),
                    has_chunks=(language_dir / "chunks" / "manifest.jsonl").exists()
                    or bool(outputs.get("chunks", False)),
                    has_frontmatter=bool(outputs.get("document_frontmatter", False)),
                    latest_quality=self._latest_quality_record_for(
                        language=str(meta.get("language") or language_dir.name),
                        source=str(meta.get("source") or ""),
                        slug=str(meta.get("source_slug") or ""),
                    ),
                )
            )
        return bundles

    def output_storage_summary(self) -> OutputStorageSummary:
        bundles = self.list_output_bundles()
        reports_dir = self.config.paths.reports_dir
        history_dir = reports_dir / "history"
        latest_report_paths = [
            reports_dir / "run_summary.json",
            reports_dir / "run_summary.md",
        ]
        trends_paths = [
            reports_dir / "trends.json",
            reports_dir / "trends.md",
        ]
        validation_path = reports_dir / "validation_documents.jsonl"
        latest_reports_bytes = sum(path.stat().st_size for path in latest_report_paths if path.exists())
        trends_bytes = sum(path.stat().st_size for path in trends_paths if path.exists())
        validation_records_bytes = validation_path.stat().st_size if validation_path.exists() else 0
        history_reports = sorted(history_dir.glob("*-run_summary.json")) if history_dir.exists() else []
        history_reports_bytes = sum(path.stat().st_size for path in history_reports)
        total_bundle_bytes = sum(bundle.bundle_bytes for bundle in bundles)
        return OutputStorageSummary(
            output_root=self.config.paths.output_dir,
            bundle_count=len(bundles),
            total_bundle_bytes=total_bundle_bytes,
            latest_reports_bytes=latest_reports_bytes,
            history_reports_bytes=history_reports_bytes,
            history_report_count=len(history_reports),
            validation_records_bytes=validation_records_bytes,
            trends_bytes=trends_bytes,
            total_managed_bytes=(
                total_bundle_bytes
                + latest_reports_bytes
                + history_reports_bytes
                + validation_records_bytes
                + trends_bytes
            ),
        )

    def delete_output_bundle(self, language_slug: str) -> StorageCleanupResult:
        language_root = self._resolve_under(self.config.paths.markdown_dir, language_slug)
        if not language_root.exists():
            return StorageCleanupResult(target=language_slug, deleted=False)
        if not language_root.is_dir():
            raise NotADirectoryError(str(language_root))
        freed_bytes, deleted_files, deleted_directories = _path_usage_with_directories(language_root)
        shutil.rmtree(language_root)
        return StorageCleanupResult(
            target=language_slug,
            deleted=True,
            freed_bytes=freed_bytes,
            deleted_files=deleted_files,
            deleted_directories=deleted_directories,
        )

    def prune_report_history(self, *, keep_latest: int = 10) -> StorageCleanupResult:
        history_dir = self.config.paths.reports_dir / "history"
        keep = max(0, keep_latest)
        if not history_dir.exists():
            return StorageCleanupResult(target="reports/history", deleted=False)
        history_reports = sorted(history_dir.glob("*-run_summary.json"))
        if len(history_reports) <= keep:
            return StorageCleanupResult(target="reports/history", deleted=False)
        deleted_files = 0
        freed_bytes = 0
        for path in history_reports[: len(history_reports) - keep]:
            freed_bytes += path.stat().st_size
            path.unlink()
            deleted_files += 1
        deleted_directories = 0
        if not any(history_dir.iterdir()):
            history_dir.rmdir()
            deleted_directories = 1
        return StorageCleanupResult(
            target="reports/history",
            deleted=deleted_files > 0 or deleted_directories > 0,
            freed_bytes=freed_bytes,
            deleted_files=deleted_files,
            deleted_directories=deleted_directories,
        )

    def output_tree(self, language_slug: str) -> OutputTreeNode:
        language_root = self._resolve_under(self.config.paths.markdown_dir, language_slug)
        if not language_root.is_dir():
            raise FileNotFoundError(f"Output bundle not found: {language_slug}")
        return self._tree_node(language_root, root=language_root)

    def read_output_file(self, language_slug: str, relative_path: str) -> OutputFileContent:
        language_root = self._resolve_under(self.config.paths.markdown_dir, language_slug)
        path = self._resolve_under(language_root, relative_path)
        if path.is_dir():
            raise IsADirectoryError(str(path))
        content = path.read_text(encoding="utf-8")
        return OutputFileContent(
            path=path,
            relative_path=path.relative_to(language_root.resolve()).as_posix(),
            media_type=_media_type(path),
            content=content,
        )

    def read_meta(self, language_slug: str) -> dict[str, Any]:
        language_root = self._resolve_under(self.config.paths.markdown_dir, language_slug)
        return read_json(self._resolve_under(language_root, "_meta.json"), {})

    def read_reports(self) -> ReportBundle:
        reports_dir = self.config.paths.reports_dir
        latest_json_path = reports_dir / "run_summary.json"
        latest_markdown_path = reports_dir / "run_summary.md"
        validation_path = reports_dir / "validation_documents.jsonl"
        trends_json_path = reports_dir / "trends.json"
        trends_markdown_path = reports_dir / "trends.md"
        return ReportBundle(
            latest_json_path=latest_json_path if latest_json_path.exists() else None,
            latest_markdown_path=latest_markdown_path if latest_markdown_path.exists() else None,
            validation_documents_path=validation_path if validation_path.exists() else None,
            trends_json_path=trends_json_path if trends_json_path.exists() else None,
            trends_markdown_path=trends_markdown_path if trends_markdown_path.exists() else None,
            history_reports=sorted((reports_dir / "history").glob("*-run_summary.json")),
            latest_json=read_json(latest_json_path, {}) if latest_json_path.exists() else {},
            latest_markdown=latest_markdown_path.read_text(encoding="utf-8") if latest_markdown_path.exists() else "",
            validation_documents=_read_jsonl(validation_path),
            trends_json=read_json(trends_json_path, {}) if trends_json_path.exists() else {},
            trends_markdown=trends_markdown_path.read_text(encoding="utf-8") if trends_markdown_path.exists() else "",
            quality_trends=self._quality_trends_map(limit=10),
        )

    def read_report_file(self, relative_path: str) -> OutputFileContent:
        path = self._resolve_under(self.config.paths.reports_dir, relative_path)
        if path.is_dir():
            raise IsADirectoryError(str(path))
        return OutputFileContent(
            path=path,
            relative_path=path.relative_to(self.config.paths.reports_dir.resolve()).as_posix(),
            media_type=_media_type(path),
            content=path.read_text(encoding="utf-8"),
        )

    def list_checkpoints(self) -> list[CheckpointSummary]:
        resolvable_catalogs = self._catalog_slug_index()
        summaries: list[CheckpointSummary] = []
        for path in sorted(self.config.paths.checkpoints_dir.glob("*.json")):
            checkpoint = self._load_checkpoint(path)
            if checkpoint is None:
                continue
            is_stale, stale_reason = self._checkpoint_staleness(
                checkpoint,
                checkpoint_path=path,
                resolvable_catalogs=resolvable_catalogs,
            )
            age_seconds = max(0, int((datetime.now(UTC) - checkpoint.updated_at).total_seconds()))
            summaries.append(
                CheckpointSummary(
                    language=checkpoint.language,
                    slug=checkpoint.slug,
                    source=checkpoint.source,
                    source_slug=checkpoint.source_slug,
                    mode=checkpoint.mode,
                    phase=checkpoint.phase,
                    path=path,
                    emitted_document_count=checkpoint.emitted_document_count,
                    document_inventory_position=checkpoint.document_inventory_position,
                    output_path=checkpoint.output_path,
                    updated_at=checkpoint.updated_at.isoformat(),
                    age_seconds=age_seconds,
                    failure_count=len(checkpoint.failures),
                    is_stale=is_stale,
                    stale_reason=stale_reason,
                )
            )
        return summaries

    def read_checkpoint(self, checkpoint_name: str) -> dict[str, Any]:
        path = self._checkpoint_path(checkpoint_name)
        checkpoint = self._load_checkpoint(path)
        if checkpoint is None:
            raise FileNotFoundError(f"Checkpoint not found or invalid: {checkpoint_name}")
        is_stale, stale_reason = self._checkpoint_staleness(
            checkpoint,
            checkpoint_path=path,
            resolvable_catalogs=self._catalog_slug_index(),
        )
        payload = checkpoint.model_dump(mode="json")
        payload["age_seconds"] = max(0, int((datetime.now(UTC) - checkpoint.updated_at).total_seconds()))
        payload["is_stale"] = is_stale
        payload["stale_reason"] = stale_reason
        return payload

    def delete_checkpoint(self, checkpoint_name: str) -> bool:
        path = self._checkpoint_path(checkpoint_name)
        if not path.exists():
            return False
        checkpoint = self._load_checkpoint(path)
        path.unlink()
        slug = checkpoint.slug if checkpoint is not None else path.stem
        (self.config.paths.state_dir / f"{slug}.json").unlink(missing_ok=True)
        return True

    def delete_stale_checkpoints(self) -> int:
        deleted = 0
        for checkpoint in self.list_checkpoints():
            if not checkpoint.is_stale:
                continue
            if self.delete_checkpoint(checkpoint.slug):
                deleted += 1
        return deleted

    def list_cache_metadata(self) -> list[CacheMetadataSummary]:
        root = self.config.paths.cache_dir
        if not root.exists():
            return []
        summaries: list[CacheMetadataSummary] = []
        for path in sorted(root.rglob("*.json")):
            if not (path.name.endswith(".meta.json") or path.name == "cache_meta.json"):
                continue
            payload = read_json(path, {})
            if not isinstance(payload, dict):
                continue
            try:
                metadata = CacheEntryMetadata.model_validate(payload)
            except Exception:
                summaries.append(CacheMetadataSummary(path=path, raw=payload))
                continue
            summaries.append(
                CacheMetadataSummary(
                    path=path,
                    source=metadata.source,
                    cache_key=metadata.cache_key,
                    url=metadata.url,
                    fetched_at=metadata.fetched_at.isoformat(),
                    source_version=metadata.source_version,
                    checksum=metadata.checksum,
                    byte_count=metadata.byte_count,
                    policy=metadata.policy,
                    refreshed_by_force=metadata.refreshed_by_force,
                    raw=payload,
                )
            )
        return summaries

    def cache_summary(self) -> CacheSummaryBundle:
        entries: list[CacheEntrySummary] = []
        total_bytes = 0
        grouped: dict[str, list[CacheEntrySummary]] = {}
        for item in self.list_cache_metadata():
            slug = _slug_from_cache_metadata(item)
            next_refresh_due = _next_refresh_due(item.fetched_at, item.policy, self.config.cache_ttl_hours)
            entry = CacheEntrySummary(
                source=item.source or _source_from_cache_path(item.path),
                slug=slug,
                cache_key=item.cache_key,
                path=str(item.path),
                byte_count=item.byte_count,
                fetched_at=item.fetched_at,
                policy=item.policy,
                next_refresh_due=next_refresh_due,
                source_version=item.source_version,
                checksum=item.checksum,
                refreshed_by_force=item.refreshed_by_force,
            )
            entries.append(entry)
            total_bytes += entry.byte_count
            grouped.setdefault(entry.source or "unknown", []).append(entry)
        source_rows: list[CacheSourceSummary] = []
        for source_name, source_entries in sorted(grouped.items()):
            timestamps = [entry.fetched_at for entry in source_entries if entry.fetched_at]
            source_rows.append(
                CacheSourceSummary(
                    source=source_name,
                    total_bytes=sum(entry.byte_count for entry in source_entries),
                    entry_count=len(source_entries),
                    oldest_entry_at=min(timestamps) if timestamps else "",
                    newest_entry_at=max(timestamps) if timestamps else "",
                )
            )
        return CacheSummaryBundle(
            cache_root=self.config.paths.cache_dir,
            total_bytes=total_bytes,
            max_cache_size_mb=self.config.max_cache_size_mb,
            max_cache_size_bytes=self.config.max_cache_size_mb * 1024 * 1024,
            sources=source_rows,
            entries=sorted(entries, key=lambda item: (item.source, item.slug, item.cache_key)),
        )

    async def refresh_cache_entry(self, *, source: str, slug: str) -> CacheEntrySummary:
        registry = self._registry()
        try:
            if source == "catalog":
                raise ValueError("Use refresh catalogs for shared catalog entries.")
            match = await registry.resolve(slug, source_name=source, force_refresh=True)
            if match is None:
                raise FileNotFoundError(f"Cache entry not found in catalog: {source}/{slug}")
            resolved_source, catalog = match
            result = await resolved_source.preview(catalog, "important", force_refresh=True)
            summary = self.cache_summary()
            for entry in summary.entries:
                if entry.source == source and entry.slug == result.slug:
                    return entry
            raise FileNotFoundError(f"Cache metadata not found after refresh: {source}/{slug}")
        finally:
            await registry.runtime.close()

    def delete_cache_entry(self, *, source: str, slug: str) -> StorageCleanupResult:
        target = _cache_entry_root(self.config.paths.cache_dir, source=source, slug=slug)
        if target is None or not target.exists():
            return StorageCleanupResult(target=f"{source}/{slug}", deleted=False)
        freed_bytes, deleted_files, deleted_directories = _path_usage_with_directories(target)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        return StorageCleanupResult(
            target=f"{source}/{slug}",
            deleted=True,
            freed_bytes=freed_bytes,
            deleted_files=deleted_files,
            deleted_directories=deleted_directories,
        )

    def clear_cache(self, *, source: str | None = None) -> StorageCleanupResult:
        target_root = _cache_entry_root(self.config.paths.cache_dir, source=source, slug=None)
        if target_root is None or not target_root.exists():
            return StorageCleanupResult(target=source or "cache", deleted=False)
        freed_bytes, deleted_files, deleted_directories = _path_usage_with_directories(target_root)
        if source is None:
            shutil.rmtree(target_root)
            self.config.paths.cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            shutil.rmtree(target_root)
        return StorageCleanupResult(
            target=source or "cache",
            deleted=True,
            freed_bytes=freed_bytes,
            deleted_files=deleted_files,
            deleted_directories=deleted_directories,
        )

    def _apply_output_options(self, request: RunLanguageRequest | BulkRunRequest) -> None:
        self.config.emit_document_frontmatter = request.emit_document_frontmatter
        self.config.emit_chunks = request.emit_chunks
        self.config.chunk_max_chars = request.chunk_max_chars
        self.config.chunk_overlap_chars = request.chunk_overlap_chars
        self.config.chunk_strategy = request.chunk_strategy
        self.config.chunk_max_tokens = request.chunk_max_tokens
        self.config.chunk_overlap_tokens = request.chunk_overlap_tokens
        self.config.cache_policy = request.cache_policy
        self.config.cache_ttl_hours = request.cache_ttl_hours

    def _registry(self) -> SourceRegistry:
        return SourceRegistry(
            cache_dir=self.config.paths.cache_dir,
            runtime=SourceRuntime(
                cache_policy=self.config.cache_policy,
                cache_ttl_hours=self.config.cache_ttl_hours,
                cache_root=self.config.paths.cache_dir,
                max_cache_size_bytes=self.config.max_cache_size_mb * 1024 * 1024,
            ),
            quality_history_path=self.config.paths.logs_dir / "quality_history.jsonl",
        )

    def _quality_history_path(self) -> Path:
        return self.config.paths.logs_dir / "quality_history.jsonl"

    def _read_quality_history(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._quality_history_path())

    def _latest_quality_by_source_slug(self, rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            source = str(row.get("source") or "").strip().lower()
            slug = str(row.get("slug") or "").strip()
            run_date = str(row.get("run_date") or "")
            if not source or not slug:
                continue
            key = (source, slug)
            prev = latest.get(key)
            if prev is None or run_date >= str(prev.get("run_date") or ""):
                latest[key] = row
        return latest

    def _preferred_source_by_language(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        by_language: dict[str, tuple[float, str, str]] = {}
        for row in rows:
            language = str(row.get("language") or "").strip().lower()
            source = str(row.get("source") or "").strip().lower()
            run_date = str(row.get("run_date") or "")
            if not language or not source:
                continue
            try:
                score = float(row.get("validation_score") or 0.0)
            except Exception:
                score = 0.0
            prev = by_language.get(language)
            if prev is None or score > prev[0] or (score == prev[0] and run_date >= prev[2]):
                by_language[language] = (score, source, run_date)
        return {language: value[1] for language, value in by_language.items()}

    def _trend_for_language(self, rows: list[dict[str, Any]], language: str) -> str:
        key = language.strip().lower()
        history = [
            float(row.get("validation_score") or 0.0)
            for row in rows
            if str(row.get("language") or "").strip().lower() == key
        ]
        if len(history) < 2:
            return "stable"
        recent = history[-1]
        prior = history[-2]
        if recent > prior + 0.01:
            return "improving"
        if recent < prior - 0.01:
            return "degrading"
        return "stable"

    def _latest_quality_record_for(self, *, language: str, source: str, slug: str) -> dict[str, Any]:
        rows = self._read_quality_history()
        best: dict[str, Any] = {}
        for row in rows:
            if (
                str(row.get("language") or "").strip().lower() != language.strip().lower()
                or str(row.get("source") or "").strip().lower() != source.strip().lower()
                or str(row.get("slug") or "").strip() != slug
            ):
                continue
            if not best or str(row.get("run_date") or "") >= str(best.get("run_date") or ""):
                best = row
        return best

    def _quality_trends_map(self, *, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
        trends: dict[str, list[dict[str, Any]]] = {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._read_quality_history():
            language = str(row.get("language") or "").strip()
            if not language:
                continue
            grouped.setdefault(language, []).append(row)
        for language, rows in grouped.items():
            ordered = sorted(rows, key=lambda item: str(item.get("run_date") or ""))[-limit:]
            trends[language] = [
                {
                    "run_date": str(item.get("run_date") or ""),
                    "validation_score": float(item.get("validation_score") or 0.0),
                    "source": str(item.get("source") or ""),
                }
                for item in ordered
            ]
        return trends

    def _resolve_under(self, root: Path, requested: str | Path) -> Path:
        root_resolved = root.resolve()
        requested_path = Path(requested)
        if requested_path.is_absolute():
            candidate = requested_path.resolve()
        else:
            candidate = (root_resolved / requested_path).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"Path escapes configured root: {requested}") from exc
        return candidate

    def _checkpoint_path(self, checkpoint_name: str) -> Path:
        name = checkpoint_name if checkpoint_name.endswith(".json") else f"{checkpoint_name}.json"
        if Path(name).name != name:
            raise ValueError(f"Invalid checkpoint name: {checkpoint_name}")
        return self._resolve_under(self.config.paths.checkpoints_dir, name)

    def _load_checkpoint(self, path: Path) -> LanguageRunCheckpoint | None:
        return load_checkpoint_payload(read_json(path, {}), path=path)

    def _catalog_slug_index(self) -> dict[str, set[str]]:
        catalogs: dict[str, set[str]] = {}
        catalogs_root = self.config.paths.cache_dir / "catalogs"
        for path in sorted(catalogs_root.glob("*.json")):
            payload = read_json(path, {})
            if not isinstance(payload, dict):
                continue
            source_name = str(payload.get("source") or path.stem).strip().lower()
            slugs = catalogs.setdefault(source_name, set())
            entries = payload.get("entries")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                slug = str(entry.get("slug") or "").strip()
                if slug:
                    slugs.add(slug)
        return catalogs

    def _checkpoint_staleness(
        self,
        checkpoint: LanguageRunCheckpoint,
        *,
        checkpoint_path: Path,
        resolvable_catalogs: dict[str, set[str]],
    ) -> tuple[bool, str]:
        output_root = self.config.paths.markdown_dir
        if not output_root.exists():
            return True, f"Output root missing: {output_root}"
        if checkpoint.output_path:
            try:
                Path(checkpoint.output_path).resolve().relative_to(output_root.resolve())
            except ValueError:
                return True, "Checkpoint output path is outside the current output root."
        source_slugs = resolvable_catalogs.get(checkpoint.source.strip().lower())
        if source_slugs is None:
            return True, f"Source catalog unavailable for {checkpoint.source}."
        if checkpoint.source_slug not in source_slugs:
            return True, f"Language slug {checkpoint.source_slug} is no longer resolvable in {checkpoint.source}."
        if not checkpoint_path.exists():
            return True, "Checkpoint file missing."
        return False, ""

    def _catalog_refresh_result(
        self,
        *,
        source: str,
        entry_count: int,
        errors: list[str] | None = None,
    ) -> CatalogRefreshResult:
        manifest_path = self.config.paths.cache_dir / "catalogs" / f"{source}.json"
        payload = read_json(manifest_path, {}) if manifest_path.exists() else {}
        entries = payload.get("entries") if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            entries = []
        support_levels = [
            str(entry.get("support_level") or "supported") for entry in entries if isinstance(entry, dict)
        ]
        combined_errors = [
            *([str(item) for item in payload.get("errors") or []] if isinstance(payload, dict) else []),
            *(errors or []),
        ]
        fallback_used = bool(payload.get("fallback_used", False)) if isinstance(payload, dict) else False
        status: Literal["refreshed", "fallback", "failed"] = (
            "failed" if combined_errors and entry_count == 0 else "refreshed"
        )
        if fallback_used and status != "failed":
            status = "fallback"
        return CatalogRefreshResult(
            source=source,
            status=status,
            entry_count=entry_count,
            supported_entries=sum(1 for level in support_levels if level == "supported"),
            experimental_entries=sum(1 for level in support_levels if level == "experimental"),
            ignored_entries=sum(1 for level in support_levels if level == "ignored"),
            discovery_strategy=str(payload.get("discovery_strategy") or "") if isinstance(payload, dict) else "",
            fetched_at=str(payload.get("fetched_at") or "") if isinstance(payload, dict) else "",
            fallback_used=fallback_used,
            fallback_reason=str(payload.get("fallback_reason") or "") if isinstance(payload, dict) else "",
            warnings=[str(item) for item in payload.get("warnings") or []] if isinstance(payload, dict) else [],
            errors=combined_errors,
        )

    def _tree_node(self, path: Path, *, root: Path) -> OutputTreeNode:
        root_resolved = root.resolve()
        path_resolved = path.resolve()
        if path.is_dir():
            children = [
                self._tree_node(child, root=root) for child in sorted(path.iterdir(), key=lambda item: item.name)
            ]
            return OutputTreeNode(
                name=path.name,
                path=path,
                relative_path="."
                if path_resolved == root_resolved
                else path_resolved.relative_to(root_resolved).as_posix(),
                is_dir=True,
                children=children,
            )
        return OutputTreeNode(
            name=path.name,
            path=path,
            relative_path=path_resolved.relative_to(root_resolved).as_posix(),
            is_dir=False,
            size=path.stat().st_size,
        )

    async def _emit_summary_events(self, summary: RunSummary, *, event_sink: ServiceEventSink | None) -> None:
        for report in summary.reports:
            await _emit(event_sink, ServiceEvent(event_type="phase_change", language=report.language, phase="reported"))
            for warning_text in report.warnings:
                await _emit(
                    event_sink, ServiceEvent(event_type="warning", language=report.language, message=warning_text)
                )
            for warning_record in report.document_warnings:
                await _emit(
                    event_sink,
                    ServiceEvent(
                        event_type="warning",
                        language=report.language,
                        message=warning_record.message,
                        payload=warning_record.model_dump(mode="json"),
                    ),
                )
            if report.validation is not None:
                await _emit(
                    event_sink,
                    ServiceEvent(
                        event_type="validation_completed",
                        language=report.language,
                        payload={
                            "score": report.validation.score,
                            "issue_count": len(report.validation.issues),
                            "document_issue_count": len(report.validation.document_results),
                        },
                    ),
                )
            if report.runtime_telemetry is not None:
                await _emit(
                    event_sink,
                    ServiceEvent(
                        event_type="runtime_telemetry",
                        language=report.language,
                        payload=report.runtime_telemetry.model_dump(mode="json"),
                    ),
                )
            if report.failures:
                for failure in report.failures:
                    detail = (
                        failure
                        if isinstance(failure, FailureDetail)
                        else FailureDetail(code="runtime_error", message=failure)
                    )
                    await _emit(
                        event_sink,
                        ServiceEvent(
                            event_type="failure",
                            language=report.language,
                            message=detail.message,
                            payload=_failure_payload(detail),
                        ),
                    )


async def _emit(event_sink: ServiceEventSink | None, event: ServiceEvent) -> None:
    if event_sink is None:
        return
    result = event_sink(event)
    if result is not None:
        await result


class _DesktopProgressTracker(CrawlProgressTracker):
    def __init__(self, event_sink: ServiceEventSink | None) -> None:
        super().__init__(single_terminal=True)
        self._event_sink = event_sink

    async def register_language(self, slug: str, display_name: str) -> None:
        await super().register_language(slug, display_name)
        await _emit(
            self._event_sink,
            ServiceEvent(
                event_type="activity",
                language=slug,
                message=f"Preparing {display_name}",
                payload={"language_slug": slug, "display_name": display_name},
            ),
        )

    async def on_phase_changed(
        self,
        slug: str,
        *,
        phase: str,
        message: str = "",
        payload: dict[str, object] | None = None,
    ) -> None:
        await _emit(
            self._event_sink,
            ServiceEvent(
                event_type="phase_change",
                language=slug,
                phase=phase,
                message=message,
                payload=dict(payload or {}),
            ),
        )

    async def on_document_completed(
        self,
        slug: str,
        *,
        title: str = "",
        topic: str = "",
        total_documents: int | None = None,
    ) -> None:
        await super().on_document_completed(slug, title=title, topic=topic, total_documents=total_documents)
        language = self._languages.get(slug)
        completed = language.documents if language is not None else 0
        await _emit(
            self._event_sink,
            ServiceEvent(
                event_type="document_emitted",
                language=slug,
                message=f"Formatted {title or slug}",
                payload={
                    "index": completed,
                    "total": total_documents,
                    "title": title,
                    "topic": topic,
                    "phase": "compiling",
                },
            ),
        )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/jsonl"
    return "text/plain"


def _failure_payload(failure: FailureDetail) -> dict[str, Any]:
    return failure.model_dump(mode="json")


def _path_usage(path: Path) -> tuple[int, int]:
    if path.is_file():
        return path.stat().st_size, 1
    total_bytes = 0
    file_count = 0
    for child in path.rglob("*"):
        if child.is_file():
            total_bytes += child.stat().st_size
            file_count += 1
    return total_bytes, file_count


def _path_usage_with_directories(path: Path) -> tuple[int, int, int]:
    total_bytes, file_count = _path_usage(path)
    if path.is_file():
        return total_bytes, file_count, 0
    directory_count = 1 + sum(1 for child in path.rglob("*") if child.is_dir())
    return total_bytes, file_count, directory_count


def _slug_from_cache_metadata(item: CacheMetadataSummary) -> str:
    cache_key = item.cache_key or ""
    if not cache_key:
        return item.path.stem.replace(".meta", "")
    return cache_key.split("/", 1)[0]


def _source_from_cache_path(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    for source in ("devdocs", "mdn", "dash", "web_page", "catalogs"):
        if source in parts:
            return "catalog" if source == "catalogs" else source
    return "unknown"


def _next_refresh_due(fetched_at: str, policy: str, ttl_hours: int | None) -> str:
    if policy != "ttl" or not fetched_at:
        return ""
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    hours = ttl_hours if ttl_hours is not None else 24
    return (fetched + timedelta(hours=max(0, hours))).isoformat()


def _cache_entry_root(cache_root: Path, *, source: str | None, slug: str | None) -> Path | None:
    if source is None:
        return cache_root
    normalized = source.strip().lower()
    if normalized == "devdocs":
        return cache_root / "devdocs" / slug if slug else cache_root / "devdocs"
    if normalized == "dash":
        return cache_root / "dash" / slug if slug else cache_root / "dash"
    if normalized == "mdn":
        if slug:
            return cache_root / "mdn"
        return cache_root / "mdn"
    if normalized == "web_page":
        return cache_root / "web_page" / slug if slug else cache_root / "web_page"
    if normalized == "catalog":
        return cache_root / "catalogs"
    return None


def _source_breaker_state(source: str, breaker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    domains_by_source = {
        "devdocs": ("devdocs.io",),
        "mdn": ("developer.mozilla.org", "github.com"),
        "dash": ("kapeli.com",),
        "web_page": (),
    }
    domains = domains_by_source.get(source, ())
    for domain in domains:
        if domain in breaker:
            return breaker[domain]
    return {"state": "closed", "last_failure_reason": ""}
