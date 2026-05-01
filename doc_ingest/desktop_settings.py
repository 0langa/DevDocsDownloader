from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .config import AppConfig
from .models import BulkConcurrencyPolicy, CacheFreshnessPolicy, CrawlMode
from .utils.filesystem import read_json, write_json


class DesktopSettings(BaseModel):
    output_dir: Path | None = None
    cache_policy: CacheFreshnessPolicy = "use-if-present"
    cache_ttl_hours: int | None = None
    max_cache_size_mb: int = 2048
    default_mode: CrawlMode = "important"
    source_preference: str | None = None
    language_tree_mode: str = "source"
    language_search: str = ""
    last_output_language_slug: str = ""
    last_output_relative_path: str = ""
    last_selected_preset: str = ""
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
    chunk_strategy: str = "chars"
    chunk_max_tokens: int = 1_000
    chunk_overlap_tokens: int = 100
    output_template: str = "default"
    output_formats: list[str] = Field(default_factory=lambda: ["markdown"])
    language_concurrency: int = 3
    bulk_concurrency_policy: BulkConcurrencyPolicy = "static"
    adaptive_min_concurrency: int = 1
    adaptive_max_concurrency: int = 6
    catalog_stale_warning_days: int = 7
    dash_large_docset_warning_mb: int = 50
    dash_warning_suppressed_slugs: list[str] = Field(default_factory=list)
    dash_profile_overrides: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


class DesktopSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, default: DesktopSettings | None = None) -> DesktopSettings:
        raw = read_json(self.path, {})
        if not isinstance(raw, dict):
            raw = {}
        if default is None:
            return DesktopSettings.model_validate(raw)
        merged = default.model_dump(mode="json")
        merged.update(raw)
        return DesktopSettings.model_validate(merged)

    def save(self, settings: DesktopSettings) -> None:
        write_json(self.path, settings.model_dump(mode="json"))


def settings_from_config(config: AppConfig) -> DesktopSettings:
    return DesktopSettings(
        output_dir=config.paths.output_dir,
        cache_policy=config.cache_policy,
        cache_ttl_hours=config.cache_ttl_hours,
        max_cache_size_mb=config.max_cache_size_mb,
        default_mode="important",
        emit_document_frontmatter=config.emit_document_frontmatter,
        emit_chunks=config.emit_chunks,
        chunk_max_chars=config.chunk_max_chars,
        chunk_overlap_chars=config.chunk_overlap_chars,
        chunk_strategy=config.chunk_strategy,
        chunk_max_tokens=config.chunk_max_tokens,
        chunk_overlap_tokens=config.chunk_overlap_tokens,
        output_template=config.output_template,
        output_formats=list(config.output_formats),
        language_concurrency=config.language_concurrency,
        bulk_concurrency_policy=config.bulk_concurrency_policy,
        adaptive_min_concurrency=config.adaptive_min_concurrency,
        adaptive_max_concurrency=config.adaptive_max_concurrency,
    )
