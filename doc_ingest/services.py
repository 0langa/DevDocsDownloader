from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import AppConfig
from .models import (
    BulkConcurrencyPolicy,
    CacheEntryMetadata,
    CacheFreshnessPolicy,
    CrawlMode,
    LanguageRunCheckpoint,
    RunSummary,
)
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker
from .runtime import SourceRuntime
from .sources.presets import PRESETS
from .sources.registry import SourceRegistry
from .utils.filesystem import read_json


class ServiceEvent(BaseModel):
    event_type: Literal[
        "phase_change",
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


class BulkRunRequest(BaseModel):
    languages: list[str]
    mode: CrawlMode = "important"
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


class AuditPresetResult(BaseModel):
    preset: str
    language: str
    resolved: bool
    source: str = ""
    slug: str = ""


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
    topics: list[dict[str, Any]] = Field(default_factory=list)
    has_chunks: bool = False
    has_frontmatter: bool = False


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
    failure_count: int = 0


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


class DocumentationService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def run_language(
        self,
        request: RunLanguageRequest,
        *,
        progress_tracker: CrawlProgressTracker | None = None,
        event_sink: ServiceEventSink | None = None,
    ) -> RunSummary:
        self._apply_output_options(request)
        await _emit(event_sink, ServiceEvent(event_type="phase_change", language=request.language, phase="started"))
        pipeline = DocumentationPipeline(self.config)
        try:
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
                ServiceEvent(event_type="failure", language=request.language, message=f"{type(exc).__name__}: {exc}"),
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
        pipeline = DocumentationPipeline(self.config)
        try:
            summary = await pipeline.run_many(
                language_names=request.languages,
                mode=request.mode,
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
            await _emit(event_sink, ServiceEvent(event_type="failure", message=f"{type(exc).__name__}: {exc}"))
            raise
        finally:
            await pipeline.close()

    async def list_languages(self, *, source: str | None = None, force_refresh: bool = False) -> list[LanguageEntry]:
        registry = self._registry()
        try:
            catalogs = await registry.catalog(force_refresh=force_refresh)
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
                    )
                )
        return sorted(rows, key=lambda item: (item.language.lower(), item.source))

    async def refresh_catalogs(self) -> dict[str, int]:
        registry = self._registry()
        try:
            catalogs = await registry.catalog(force_refresh=True)
        finally:
            await registry.runtime.close()
        return {source: len(entries) for source, entries in catalogs.items()}

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
            bundles.append(
                OutputBundleSummary(
                    language_slug=language_dir.name,
                    path=language_dir,
                    language=str(meta.get("language") or language_dir.name),
                    source=str(meta.get("source") or ""),
                    source_slug=str(meta.get("source_slug") or ""),
                    mode=str(meta.get("mode") or ""),
                    total_documents=int(meta.get("total_documents") or 0),
                    topics=list(meta.get("topics") or []),
                    has_chunks=(language_dir / "chunks" / "manifest.jsonl").exists()
                    or bool(outputs.get("chunks", False)),
                    has_frontmatter=bool(outputs.get("document_frontmatter", False)),
                )
            )
        return bundles

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
        summaries: list[CheckpointSummary] = []
        for path in sorted(self.config.paths.checkpoints_dir.glob("*.json")):
            checkpoint = self._load_checkpoint(path)
            if checkpoint is None:
                continue
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
                    failure_count=len(checkpoint.failures),
                )
            )
        return summaries

    def read_checkpoint(self, checkpoint_name: str) -> dict[str, Any]:
        path = self._checkpoint_path(checkpoint_name)
        return read_json(path, {})

    def delete_checkpoint(self, checkpoint_name: str) -> bool:
        path = self._checkpoint_path(checkpoint_name)
        if not path.exists():
            return False
        path.unlink()
        return True

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
            ),
        )

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
        try:
            return LanguageRunCheckpoint.model_validate(read_json(path, {}))
        except Exception:
            return None

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
            for index in range(report.total_documents):
                await _emit(
                    event_sink,
                    ServiceEvent(
                        event_type="document_emitted",
                        language=report.language,
                        payload={"index": index + 1, "total": report.total_documents},
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
                    await _emit(
                        event_sink, ServiceEvent(event_type="failure", language=report.language, message=failure)
                    )


async def _emit(event_sink: ServiceEventSink | None, event: ServiceEvent) -> None:
    if event_sink is None:
        return
    result = event_sink(event)
    if result is not None:
        await result


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
