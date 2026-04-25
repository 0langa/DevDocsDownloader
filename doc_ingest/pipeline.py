from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from .compiler import compile_from_stream
from .config import AppConfig
from .models import (
    CrawlMode,
    DocumentCheckpoint,
    LanguageRunCheckpoint,
    LanguageRunReport,
    LanguageRunState,
    RunSummary,
    SourceRunDiagnostics,
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
        self.runtime = SourceRuntime()
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
        include_topics: list[str] | None = None,
        exclude_topics: list[str] | None = None,
    ) -> RunSummary:
        summary = RunSummary()
        concurrency = max(1, language_concurrency or self.config.language_concurrency)
        semaphore = asyncio.Semaphore(concurrency)

        async def _run_one(name: str) -> RunSummary:
            async with semaphore:
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

        partials = await asyncio.gather(*(_run_one(name) for name in language_names))
        for partial in partials:
            summary.reports.extend(partial.reports)
        write_reports(summary, self.config.paths.reports_dir)
        return summary

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
        if previous_checkpoint is not None and previous_checkpoint.phase != "completed":
            report.warnings.append(
                "Previous incomplete checkpoint found: "
                f"phase={previous_checkpoint.phase}, "
                f"emitted={previous_checkpoint.emitted_document_count}, "
                f"position={previous_checkpoint.document_inventory_position}."
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
                )
                report.total_documents = prior.total_documents
                report.topics = prior.topics
            report.duration_seconds = time.perf_counter() - started
            return report

        if progress_tracker is not None:
            await progress_tracker.register_language(language_slug, catalog.display_name)

        diagnostics = SourceRunDiagnostics()
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
        )
        checkpoint_store.save(checkpoint)

        async def _on_document(doc: Document) -> None:
            checkpoint_store.record_document(
                checkpoint,
                DocumentCheckpoint(
                    topic=doc.topic,
                    slug=doc.slug,
                    title=doc.title,
                    source_url=doc.source_url,
                    order_hint=doc.order_hint,
                ),
            )
            if progress_tracker is not None:
                await progress_tracker.on_document_completed(language_slug)

        try:
            checkpoint_store.update_phase(checkpoint, "fetching", output_path=str(consolidated_path))
            documents = _filtered_documents(
                _documents_from_events(
                    _fetch_events(source, catalog, mode, diagnostics),
                    diagnostics=diagnostics,
                    warnings=report.warnings,
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
            )
        except Exception as exc:
            LOGGER.exception("Failed to compile %s from %s", catalog.display_name, source.name)
            report.failures.append(f"{type(exc).__name__}: {exc}")
            checkpoint_store.record_failure(
                checkpoint,
                phase=checkpoint.phase,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language_slug, report)
            report.duration_seconds = time.perf_counter() - started
            return report

        report.output_path = compiled.output_path
        report.total_documents = compiled.total_documents
        report.source_diagnostics = diagnostics
        report.topics = compiled.topics
        try:
            checkpoint_store.update_phase(checkpoint, "validating", output_path=str(compiled.output_path))
            report.validation = validate_output(
                language=catalog.display_name,
                output_path=compiled.output_path,
                total_documents=compiled.total_documents,
                topics=compiled.topics,
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


async def _fetch_events(
    source: DocumentationSource,
    catalog: LanguageCatalog,
    mode: CrawlMode,
    diagnostics: SourceRunDiagnostics,
) -> AsyncIterator[AdapterEvent]:
    events = getattr(source, "events", None)
    if events is not None:
        try:
            async for event in events(catalog, mode, diagnostics=diagnostics):
                yield event
            return
        except TypeError:
            async for event in events(catalog, mode):
                yield event
            return

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
) -> AsyncIterator[Document]:
    async for event in events:
        if isinstance(event, DocumentEvent):
            yield event.document
        elif isinstance(event, WarningEvent):
            detail = f"{event.code}: {event.message}"
            if event.source_url:
                detail = f"{detail} ({event.source_url})"
            warnings.append(detail)
        elif isinstance(event, SkippedEvent):
            diagnostics.skip(event.reason, event.count)
        elif isinstance(event, SourceStatsEvent):
            diagnostics.discovered += event.discovered
            diagnostics.emitted += event.emitted
        elif isinstance(event, AssetEvent):
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
