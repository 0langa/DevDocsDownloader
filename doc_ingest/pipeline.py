from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from .adaptive import AdaptiveBulkController, AdaptiveBulkPolicy, static_bulk_telemetry
from .compiler import CompilationDocument, artifact_checkpoint, compile_from_stream
from .config import AppConfig
from .models import (
    AdaptiveBulkTelemetry,
    BulkConcurrencyPolicy,
    CrawlMode,
    DocumentArtifactCheckpoint,
    LanguageRunCheckpoint,
    LanguageRunReport,
    LanguageRunState,
    ResumeBoundary,
    RunSummary,
    RuntimeTelemetrySnapshot,
    SourceRunDiagnostics,
    SourceWarningRecord,
    TopicStats,
)
from .progress import CrawlProgressTracker
from .reporting import write_reports
from .runtime import SourceRuntime
from .sources.base import (
    AdapterEvent,
    AssetEvent,
    Document,
    DocumentationSource,
    DocumentEvent,
    DocumentWarningEvent,
    LanguageCatalog,
    SkippedEvent,
    SourceStatsEvent,
    WarningEvent,
    document_events,
)
from .sources.registry import SourceRegistry
from .state import RunCheckpointStore, RunStateStore
from .utils.filesystem import read_json
from .utils.text import slugify
from .validator import validate_output

LOGGER = logging.getLogger("doc_ingest")


class DocumentationPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.runtime = SourceRuntime(
            cache_policy=config.cache_policy,
            cache_ttl_hours=config.cache_ttl_hours,
        )
        self.registry = SourceRegistry(cache_dir=config.paths.cache_dir, runtime=self.runtime)

    async def close(self) -> None:
        await self.runtime.close()

    async def run_many(
        self,
        *,
        language_names: list[str],
        mode: CrawlMode = "important",
        source_name: str | None = None,
        force_refresh: bool = False,
        progress_tracker: CrawlProgressTracker | None = None,
        validate_only: bool = False,
        language_concurrency: int | None = None,
        concurrency_policy: BulkConcurrencyPolicy | None = None,
        adaptive_min_concurrency: int | None = None,
        adaptive_max_concurrency: int | None = None,
        include_topics: list[str] | None = None,
        exclude_topics: list[str] | None = None,
    ) -> RunSummary:
        summary = RunSummary()
        concurrency = max(1, language_concurrency or self.config.language_concurrency)
        policy = concurrency_policy or self.config.bulk_concurrency_policy

        async def _run_one(name: str) -> RunSummary:
            return await self.run(
                language_name=name,
                mode=mode,
                source_name=source_name,
                force_refresh=force_refresh,
                progress_tracker=progress_tracker,
                validate_only=validate_only,
                include_topics=include_topics,
                exclude_topics=exclude_topics,
                _write_reports=False,
            )

        if policy == "adaptive":
            partials, telemetry = await self._run_many_adaptive(
                language_names=language_names,
                run_one=_run_one,
                initial_concurrency=concurrency,
                min_concurrency=adaptive_min_concurrency or self.config.adaptive_min_concurrency,
                max_concurrency=adaptive_max_concurrency or self.config.adaptive_max_concurrency,
            )
            summary.adaptive_telemetry = telemetry
        else:
            semaphore = asyncio.Semaphore(concurrency)

            async def _run_one_static(name: str) -> RunSummary:
                async with semaphore:
                    return await _run_one(name)

            partials = await asyncio.gather(*(_run_one_static(name) for name in language_names))
            summary.adaptive_telemetry = static_bulk_telemetry(concurrency=concurrency)

        for partial in partials:
            summary.reports.extend(partial.reports)
        write_reports(summary, self.config.paths.reports_dir)
        return summary

    async def _run_many_adaptive(
        self,
        *,
        language_names: list[str],
        run_one,
        initial_concurrency: int,
        min_concurrency: int,
        max_concurrency: int,
    ) -> tuple[list[RunSummary], AdaptiveBulkTelemetry]:
        controller = AdaptiveBulkController(
            AdaptiveBulkPolicy(
                initial_concurrency=initial_concurrency,
                min_concurrency=min_concurrency,
                max_concurrency=max(max_concurrency, initial_concurrency),
            )
        )
        results: list[RunSummary | None] = [None] * len(language_names)
        active: dict[asyncio.Task[RunSummary], int] = {}
        next_index = 0

        while next_index < len(language_names) or active:
            while next_index < len(language_names) and len(active) < controller.current_concurrency:
                task = asyncio.create_task(run_one(language_names[next_index]))
                active[task] = next_index
                next_index += 1
            if not active:
                continue
            done, _pending = await asyncio.wait(active.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                index = active.pop(task)
                partial = await task
                results[index] = partial
                for report in partial.reports:
                    controller.observe(report)

        return [item for item in results if item is not None], controller.snapshot()

    async def run(
        self,
        *,
        language_name: str,
        mode: CrawlMode = "important",
        source_name: str | None = None,
        force_refresh: bool = False,
        progress_tracker: CrawlProgressTracker | None = None,
        validate_only: bool = False,
        include_topics: list[str] | None = None,
        exclude_topics: list[str] | None = None,
        _write_reports: bool = True,
    ) -> RunSummary:
        summary = RunSummary()
        if validate_only:
            local_report = self._validate_local_output(language_name=language_name, mode=mode)
            if local_report is not None:
                summary.reports.append(local_report)
                if _write_reports:
                    write_reports(summary, self.config.paths.reports_dir)
                return summary

        resolution = await self.registry.resolve(
            language_name,
            source_name=source_name,
            force_refresh=force_refresh,
        )
        if resolution is None:
            suggestions = await self.registry.suggest(language_name)
            hint = ", ".join(f"{display} ({src})" for src, display in suggestions) or "none"
            report = LanguageRunReport(
                language=language_name,
                slug=slugify(language_name),
                source="none",
                source_slug="",
                mode=mode,
                failures=[f"No source provides '{language_name}'. Closest matches: {hint}."],
            )
            summary.reports.append(report)
            if _write_reports:
                write_reports(summary, self.config.paths.reports_dir)
            return summary

        source, catalog = resolution
        report = await self._run_language(
            source=source,
            catalog=catalog,
            mode=mode,
            progress_tracker=progress_tracker,
            validate_only=validate_only,
            include_topics=include_topics,
            exclude_topics=exclude_topics,
            force_refresh=force_refresh,
        )
        summary.reports.append(report)
        if _write_reports:
            write_reports(summary, self.config.paths.reports_dir)
        return summary

    def _validate_local_output(self, *, language_name: str, mode: CrawlMode) -> LanguageRunReport | None:
        language_slug = slugify(language_name)
        language_dir = self.config.paths.markdown_dir / language_slug
        consolidated_path = language_dir / f"{language_slug}.md"
        meta_path = language_dir / "_meta.json"
        state_path = self.config.paths.state_dir / f"{language_slug}.json"

        has_local_metadata = meta_path.exists() or state_path.exists()
        has_output = consolidated_path.exists()
        if not has_local_metadata and not has_output:
            return None

        warnings: list[str] = []
        try:
            meta = read_json(meta_path, {}) if meta_path.exists() else {}
        except Exception as exc:
            meta = {}
            warnings.append(f"Failed to read local metadata {meta_path}: {type(exc).__name__}: {exc}")
        state_store = RunStateStore(state_path)
        meta_mode = meta.get("mode")
        state_mode = cast(CrawlMode, meta_mode) if meta_mode in ("important", "full") else mode
        default_state = LanguageRunState(
            language=str(meta.get("language") or language_name),
            slug=language_slug,
            source=str(meta.get("source") or "local"),
            source_slug=str(meta.get("source_slug") or ""),
            source_url=str(meta.get("source_url") or ""),
            mode=state_mode,
        )
        state = state_store.load(default=default_state)

        topics = state.topics or [
            TopicStats.model_validate(item) for item in meta.get("topics", []) if isinstance(item, dict)
        ]
        total_documents = state.total_documents or int(meta.get("total_documents") or 0)
        output_path = Path(state.output_path) if state.output_path else consolidated_path

        report = LanguageRunReport(
            language=state.language,
            slug=state.slug or language_slug,
            source=state.source or str(meta.get("source") or "local"),
            source_slug=state.source_slug or str(meta.get("source_slug") or ""),
            source_url=state.source_url or str(meta.get("source_url") or ""),
            mode=state.mode,
            output_path=output_path if output_path.exists() else None,
            total_documents=total_documents,
            topics=topics,
            warnings=warnings,
        )
        started = time.perf_counter()
        if report.output_path is None:
            report.failures.append("No compiled output found for this language.")
        else:
            report.validation = validate_output(
                language=report.language,
                output_path=report.output_path,
                total_documents=total_documents,
                topics=topics,
                source=report.source,
                source_slug=report.source_slug,
                source_diagnostics=state.source_diagnostics,
            )
        report.duration_seconds = time.perf_counter() - started
        return report

    async def _run_language(
        self,
        *,
        source: DocumentationSource,
        catalog: LanguageCatalog,
        mode: CrawlMode,
        progress_tracker: CrawlProgressTracker | None,
        validate_only: bool,
        include_topics: list[str] | None = None,
        exclude_topics: list[str] | None = None,
        force_refresh: bool = False,
    ) -> LanguageRunReport:
        language_slug = slugify(catalog.display_name)
        output_root = self.config.paths.markdown_dir
        language_dir = output_root / language_slug
        consolidated_path = language_dir / f"{language_slug}.md"
        state_path = self.config.paths.state_dir / f"{language_slug}.json"
        state_store = RunStateStore(state_path)
        checkpoint_path = self.config.paths.checkpoints_dir / f"{language_slug}.json"
        checkpoint_store = RunCheckpointStore(checkpoint_path)

        started = time.perf_counter()
        report = LanguageRunReport(
            language=catalog.display_name,
            slug=language_slug,
            source=source.name,
            source_slug=catalog.slug,
            source_url=catalog.homepage,
            mode=mode,
        )
        previous_checkpoint = checkpoint_store.load()
        resume_artifacts: list[DocumentArtifactCheckpoint] = []
        resume_boundary: ResumeBoundary | None = None
        if previous_checkpoint is not None and previous_checkpoint.phase != "completed":
            report.warnings.append(
                "Previous incomplete checkpoint found: "
                f"phase={previous_checkpoint.phase}, "
                f"emitted={previous_checkpoint.emitted_document_count}, "
                f"position={previous_checkpoint.document_inventory_position}."
            )
            resume_artifacts, resume_boundary = _validated_resume(
                previous_checkpoint,
                language_slug=language_slug,
                source=source.name,
                source_slug=catalog.slug,
                mode=mode,
                output_path=consolidated_path,
            )
            if resume_boundary is None:
                report.warnings.append("Checkpoint resume artifacts were missing or stale; replaying from the start.")
            else:
                report.warnings.append(
                    "Resuming from checkpoint boundary "
                    f"position={resume_boundary.document_inventory_position}, "
                    f"emitted={resume_boundary.emitted_document_count}."
                )

        if validate_only:
            report.output_path = consolidated_path if consolidated_path.exists() else None
            if report.output_path is None:
                report.failures.append("No compiled output found for this language.")
            else:
                prior = state_store.load(
                    default=LanguageRunState(
                        language=catalog.display_name,
                        slug=language_slug,
                        source=source.name,
                        source_slug=catalog.slug,
                    )
                )
                report.validation = validate_output(
                    language=catalog.display_name,
                    output_path=consolidated_path,
                    total_documents=prior.total_documents,
                    topics=prior.topics,
                    source=source.name,
                    source_slug=catalog.slug,
                    source_diagnostics=prior.source_diagnostics,
                )
                report.total_documents = prior.total_documents
                report.topics = prior.topics
                report.runtime_telemetry = _telemetry_snapshot(self.runtime)
            report.duration_seconds = time.perf_counter() - started
            return report

        if progress_tracker is not None:
            await progress_tracker.register_language(language_slug, catalog.display_name)

        diagnostics = SourceRunDiagnostics()
        document_warnings: list[SourceWarningRecord] = []
        asset_events: list[AssetEvent] = []
        include_topic_set = _normalize_topic_filter(include_topics)
        exclude_topic_set = _normalize_topic_filter(exclude_topics)

        checkpoint = LanguageRunCheckpoint(
            language=catalog.display_name,
            slug=language_slug,
            source=source.name,
            source_slug=catalog.slug,
            source_url=catalog.homepage,
            mode=mode,
            phase="initialized",
            output_path=str(consolidated_path),
            emitted_documents=list(resume_artifacts),
        )
        if resume_boundary is not None:
            checkpoint.document_inventory_position = resume_boundary.document_inventory_position
            checkpoint.emitted_document_count = resume_boundary.emitted_document_count
            checkpoint.last_document = resume_artifacts[-1]
        checkpoint_store.save(checkpoint)

        async def _on_document(doc: Document, artifact: CompilationDocument) -> None:
            checkpoint_store.record_document_artifact(
                checkpoint,
                artifact_checkpoint(artifact, topic=doc.topic),
            )
            if progress_tracker is not None:
                await progress_tracker.on_document_completed(language_slug)

        try:
            checkpoint_store.update_phase(checkpoint, "fetching", output_path=str(consolidated_path))
            documents = _filtered_documents(
                _documents_from_events(
                    _fetch_events(
                        source,
                        catalog,
                        mode,
                        diagnostics,
                        resume_boundary=resume_boundary,
                        force_refresh=force_refresh,
                    ),
                    diagnostics=diagnostics,
                    warnings=report.warnings,
                    document_warnings=document_warnings,
                    assets=asset_events,
                ),
                diagnostics=diagnostics,
                include_topics=include_topic_set,
                exclude_topics=exclude_topic_set,
            )
            compiled = await compile_from_stream(
                language_display=catalog.display_name,
                language_slug=language_slug,
                source=source.name,
                source_slug=catalog.slug,
                source_url=catalog.homepage,
                mode=mode,
                output_root=output_root,
                documents=documents,
                on_document=_on_document,
                resume_artifacts=resume_artifacts,
                durability=self.config.generated_markdown_durability,
                emit_document_frontmatter=self.config.emit_document_frontmatter,
                emit_chunks=self.config.emit_chunks,
                chunk_max_chars=self.config.chunk_max_chars,
                chunk_overlap_chars=self.config.chunk_overlap_chars,
                chunk_strategy=self.config.chunk_strategy,
                chunk_max_tokens=self.config.chunk_max_tokens,
                chunk_overlap_tokens=self.config.chunk_overlap_tokens,
                assets=asset_events,
            )
        except Exception as exc:
            LOGGER.exception("Failed to compile %s from %s", catalog.display_name, source.name)
            report.failures.append(f"{type(exc).__name__}: {exc}")
            report.document_warnings = document_warnings
            checkpoint_store.record_failure(
                checkpoint,
                phase=checkpoint.phase,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language_slug, report)
            report.runtime_telemetry = _telemetry_snapshot(self.runtime)
            report.duration_seconds = time.perf_counter() - started
            return report

        report.output_path = compiled.output_path
        report.total_documents = compiled.total_documents
        report.source_diagnostics = diagnostics
        report.document_warnings = document_warnings
        report.runtime_telemetry = _telemetry_snapshot(self.runtime)
        report.asset_inventory = compiled.asset_inventory
        report.topics = compiled.topics
        try:
            checkpoint_store.update_phase(checkpoint, "validating", output_path=str(compiled.output_path))
            report.validation = validate_output(
                language=catalog.display_name,
                output_path=compiled.output_path,
                total_documents=compiled.total_documents,
                topics=compiled.topics,
                source=source.name,
                source_slug=catalog.slug,
                source_diagnostics=diagnostics,
            )

            state_store.save(
                LanguageRunState(
                    language=catalog.display_name,
                    slug=language_slug,
                    source=source.name,
                    source_slug=catalog.slug,
                    source_url=catalog.homepage,
                    mode=mode,
                    topics=compiled.topics,
                    total_documents=compiled.total_documents,
                    source_diagnostics=diagnostics,
                    output_path=str(compiled.output_path),
                    document_warnings=document_warnings,
                    runtime_telemetry=report.runtime_telemetry,
                    asset_inventory=report.asset_inventory,
                    completed=True,
                )
            )
        except Exception as exc:
            LOGGER.exception("Failed to finalize %s from %s", catalog.display_name, source.name)
            report.failures.append(f"{type(exc).__name__}: {exc}")
            checkpoint_store.record_failure(
                checkpoint,
                phase=checkpoint.phase,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language_slug, report)
            report.runtime_telemetry = _telemetry_snapshot(self.runtime)
            report.duration_seconds = time.perf_counter() - started
            return report

        if progress_tracker is not None:
            await progress_tracker.on_language_complete(language_slug, report)

        checkpoint_store.update_phase(checkpoint, "completed", output_path=str(compiled.output_path))
        checkpoint_store.delete()

        report.duration_seconds = time.perf_counter() - started
        return report


def _normalize_topic_filter(values: list[str] | None) -> set[str]:
    return {value.strip().lower() for value in values or [] if value.strip()}


def _validated_resume(
    checkpoint: LanguageRunCheckpoint,
    *,
    language_slug: str,
    source: str,
    source_slug: str,
    mode: CrawlMode,
    output_path: Path,
) -> tuple[list[DocumentArtifactCheckpoint], ResumeBoundary | None]:
    if checkpoint.slug != language_slug:
        return [], None
    if checkpoint.source != source or checkpoint.source_slug != source_slug or checkpoint.mode != mode:
        return [], None
    if checkpoint.output_path and Path(checkpoint.output_path) != output_path:
        return [], None
    if checkpoint.document_inventory_position is None or not checkpoint.emitted_documents:
        return [], None

    artifacts = checkpoint.emitted_documents
    for artifact in artifacts:
        if not Path(artifact.path).exists() or not Path(artifact.fragment_path).exists():
            return [], None

    return artifacts, ResumeBoundary(
        document_inventory_position=checkpoint.document_inventory_position,
        emitted_document_count=checkpoint.emitted_document_count,
    )


def _telemetry_snapshot(runtime: SourceRuntime) -> RuntimeTelemetrySnapshot:
    telemetry = runtime.telemetry
    return RuntimeTelemetrySnapshot(
        requests=telemetry.requests,
        retries=telemetry.retries,
        bytes_observed=telemetry.bytes_observed,
        failures=telemetry.failures,
        cache_hits=telemetry.cache_hits,
        cache_refreshes=telemetry.cache_refreshes,
    )


async def _fetch_events(
    source: DocumentationSource,
    catalog: LanguageCatalog,
    mode: CrawlMode,
    diagnostics: SourceRunDiagnostics,
    resume_boundary: ResumeBoundary | None = None,
    force_refresh: bool = False,
) -> AsyncIterator[AdapterEvent]:
    events = getattr(source, "events", None)
    if events is not None:
        try:
            async for event in events(
                catalog,
                mode,
                diagnostics=diagnostics,
                resume_boundary=resume_boundary,
                force_refresh=force_refresh,
            ):
                yield event
            return
        except TypeError:
            try:
                async for event in events(catalog, mode, diagnostics=diagnostics):
                    yield event
                return
            except TypeError:
                async for event in events(catalog, mode):
                    yield event
                return

    try:
        documents = source.fetch(
            catalog,
            mode,
            diagnostics=diagnostics,
            resume_boundary=resume_boundary,
            force_refresh=force_refresh,
        )
    except TypeError:
        try:
            documents = source.fetch(catalog, mode, diagnostics=diagnostics)
        except TypeError:
            documents = source.fetch(catalog, mode)
    async for event in document_events(documents):
        yield event


async def _documents_from_events(
    events: AsyncIterator[AdapterEvent],
    *,
    diagnostics: SourceRunDiagnostics,
    warnings: list[str],
    document_warnings: list[SourceWarningRecord] | None = None,
    assets: list[AssetEvent] | None = None,
) -> AsyncIterator[Document]:
    async for event in events:
        if isinstance(event, DocumentEvent):
            yield event.document
        elif isinstance(event, WarningEvent):
            detail = f"{event.code}: {event.message}"
            if event.source_url:
                detail = f"{detail} ({event.source_url})"
            warnings.append(detail)
        elif isinstance(event, DocumentWarningEvent):
            record = SourceWarningRecord(
                code=event.code,
                message=event.message,
                source_url=event.source_url,
                topic=event.topic,
                slug=event.slug,
                title=event.title,
                order_hint=event.order_hint,
            )
            if document_warnings is not None:
                document_warnings.append(record)
            subject = event.title or event.slug or event.source_url or "document"
            warnings.append(f"{event.code}: {subject}: {event.message}")
        elif isinstance(event, SkippedEvent):
            diagnostics.skip(event.reason, event.count)
        elif isinstance(event, SourceStatsEvent):
            diagnostics.discovered += event.discovered
            diagnostics.emitted += event.emitted
        elif isinstance(event, AssetEvent):
            if assets is not None:
                assets.append(event)
            diagnostics.skip("asset_event", 1)


async def _filtered_documents(
    documents: AsyncIterator[Document],
    *,
    diagnostics: SourceRunDiagnostics,
    include_topics: set[str],
    exclude_topics: set[str],
) -> AsyncIterator[Document]:
    async for document in documents:
        topic = document.topic.strip().lower()
        if include_topics and topic not in include_topics:
            diagnostics.skip("filtered_topic_include")
            continue
        if exclude_topics and topic in exclude_topics:
            diagnostics.skip("filtered_topic_exclude")
            continue
        yield document
