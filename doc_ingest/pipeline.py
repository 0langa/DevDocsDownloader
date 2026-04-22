from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .compiler import compile_from_stream
from .config import AppConfig
from .models import (
    CrawlMode,
    LanguageRunReport,
    LanguageRunState,
    RunSummary,
    TopicStats,
)
from .progress import CrawlProgressTracker
from .reporting import write_reports
from .sources.base import Document, DocumentationSource, LanguageCatalog
from .sources.registry import SourceRegistry
from .state import RunStateStore
from .utils.text import slugify
from .validator import validate_output

LOGGER = logging.getLogger("doc_ingest")


class DocumentationPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.registry = SourceRegistry(cache_dir=config.paths.cache_dir)

    async def close(self) -> None:
        return None

    async def run_many(
        self,
        *,
        language_names: list[str],
        mode: CrawlMode = "important",
        source_name: str | None = None,
        force_refresh: bool = False,
        progress_tracker: CrawlProgressTracker | None = None,
        validate_only: bool = False,
    ) -> RunSummary:
        summary = RunSummary()
        for name in language_names:
            partial = await self.run(
                language_name=name,
                mode=mode,
                source_name=source_name,
                force_refresh=False,
                progress_tracker=progress_tracker,
                validate_only=validate_only,
                _write_reports=False,
            )
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
        _write_reports: bool = True,
    ) -> RunSummary:
        summary = RunSummary()
        resolution = await self.registry.resolve(
            language_name, source_name=source_name, force_refresh=force_refresh,
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
        )
        summary.reports.append(report)
        if _write_reports:
            write_reports(summary, self.config.paths.reports_dir)
        return summary

    async def _run_language(
        self,
        *,
        source: DocumentationSource,
        catalog: LanguageCatalog,
        mode: CrawlMode,
        progress_tracker: CrawlProgressTracker | None,
        validate_only: bool,
    ) -> LanguageRunReport:
        language_slug = slugify(catalog.display_name)
        output_root = self.config.paths.markdown_dir
        language_dir = output_root / language_slug
        consolidated_path = language_dir / f"{language_slug}.md"
        state_path = self.config.paths.state_dir / f"{language_slug}.json"
        state_store = RunStateStore(state_path)

        started = time.perf_counter()
        report = LanguageRunReport(
            language=catalog.display_name,
            slug=language_slug,
            source=source.name,
            source_slug=catalog.slug,
            source_url=catalog.homepage,
            mode=mode,
        )

        if validate_only:
            report.output_path = consolidated_path if consolidated_path.exists() else None
            if report.output_path is None:
                report.failures.append("No compiled output found for this language.")
            else:
                prior = state_store.load(default=LanguageRunState(
                    language=catalog.display_name, slug=language_slug,
                    source=source.name, source_slug=catalog.slug,
                ))
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

        async def _on_document(_doc: Document) -> None:
            if progress_tracker is not None:
                await progress_tracker.on_document_completed(language_slug)

        try:
            compiled = await compile_from_stream(
                language_display=catalog.display_name,
                language_slug=language_slug,
                source=source.name,
                source_slug=catalog.slug,
                source_url=catalog.homepage,
                mode=mode,
                output_root=output_root,
                documents=source.fetch(catalog, mode),
                on_document=_on_document,
            )
        except Exception as exc:
            LOGGER.exception("Failed to compile %s from %s", catalog.display_name, source.name)
            report.failures.append(f"{type(exc).__name__}: {exc}")
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language_slug, report)
            report.duration_seconds = time.perf_counter() - started
            return report

        report.output_path = compiled.output_path
        report.total_documents = compiled.total_documents
        report.topics = compiled.topics
        report.validation = validate_output(
            language=catalog.display_name,
            output_path=compiled.output_path,
            total_documents=compiled.total_documents,
            topics=compiled.topics,
        )

        state_store.save(LanguageRunState(
            language=catalog.display_name,
            slug=language_slug,
            source=source.name,
            source_slug=catalog.slug,
            source_url=catalog.homepage,
            mode=mode,
            topics=compiled.topics,
            total_documents=compiled.total_documents,
            output_path=str(compiled.output_path),
            completed=True,
        ))

        if progress_tracker is not None:
            await progress_tracker.on_language_complete(language_slug, report)

        report.duration_seconds = time.perf_counter() - started
        return report
