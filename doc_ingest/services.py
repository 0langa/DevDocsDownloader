from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .config import AppConfig
from .models import CacheFreshnessPolicy, CrawlMode, RunSummary
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker
from .runtime import SourceRuntime
from .sources.presets import PRESETS
from .sources.registry import SourceRegistry


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
    cache_policy: CacheFreshnessPolicy = "use-if-present"
    cache_ttl_hours: int | None = None


class BulkRunRequest(BaseModel):
    languages: list[str]
    mode: CrawlMode = "important"
    force_refresh: bool = False
    language_concurrency: int = 3
    include_topics: list[str] | None = None
    exclude_topics: list[str] | None = None
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
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


class DocumentationService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def run_language(
        self,
        request: RunLanguageRequest,
        *,
        progress_tracker: CrawlProgressTracker | None = None,
    ) -> RunSummary:
        self._apply_output_options(request)
        pipeline = DocumentationPipeline(self.config)
        try:
            return await pipeline.run(
                language_name=request.language,
                mode=request.mode,
                source_name=request.source,
                force_refresh=request.force_refresh,
                progress_tracker=progress_tracker,
                validate_only=request.validate_only,
                include_topics=request.include_topics,
                exclude_topics=request.exclude_topics,
            )
        finally:
            await pipeline.close()

    async def run_bulk(
        self,
        request: BulkRunRequest,
        *,
        progress_tracker: CrawlProgressTracker | None = None,
    ) -> RunSummary:
        self._apply_output_options(request)
        self.config.language_concurrency = max(1, request.language_concurrency)
        pipeline = DocumentationPipeline(self.config)
        try:
            return await pipeline.run_many(
                language_names=request.languages,
                mode=request.mode,
                force_refresh=request.force_refresh,
                progress_tracker=progress_tracker,
                language_concurrency=request.language_concurrency,
                include_topics=request.include_topics,
                exclude_topics=request.exclude_topics,
            )
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
        )

    def _apply_output_options(self, request: RunLanguageRequest | BulkRunRequest) -> None:
        self.config.emit_document_frontmatter = request.emit_document_frontmatter
        self.config.emit_chunks = request.emit_chunks
        self.config.chunk_max_chars = request.chunk_max_chars
        self.config.chunk_overlap_chars = request.chunk_overlap_chars
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
