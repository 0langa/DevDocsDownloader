from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    root: Path
    input_file: Path
    output_dir: Path
    markdown_dir: Path
    cache_dir: Path
    crawl_cache_dir: Path
    logs_dir: Path
    state_dir: Path
    tmp_dir: Path
    reports_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "PathsConfig":
        output_dir = root / "output"
        return cls(
            root=root,
            input_file=root / "top_50_programming_languages_with_official_docs.txt",
            output_dir=output_dir,
            markdown_dir=output_dir / "markdown",
            cache_dir=root / "cache",
            crawl_cache_dir=root / "cache" / "discovered_links",
            logs_dir=root / "logs",
            state_dir=root / "state",
            tmp_dir=root / "tmp",
            reports_dir=output_dir / "reports",
        )

    def ensure(self) -> None:
        for path in [
            self.output_dir,
            self.markdown_dir,
            self.cache_dir,
            self.crawl_cache_dir,
            self.logs_dir,
            self.state_dir,
            self.tmp_dir,
            self.reports_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class CrawlConfig(BaseModel):
    max_concurrency: int = 6
    language_concurrency: int = 3
    request_timeout_seconds: float = 30.0
    total_timeout_seconds: float = 60.0
    retries: int = 4
    backoff_base_seconds: float = 1.2
    per_host_delay_seconds: float = 0.1
    max_pages_per_language: int = 2000
    max_assets_per_language: int = 300
    max_discovered_urls_per_language: int = 5000
    max_queue_size_per_language: int = 1500
    user_agent: str = "DocIngestBot/1.0 (+local documentation ingestion)"
    browser_enabled: bool = True
    browser_timeout_seconds: float = 45.0
    duplicate_similarity_threshold: float = 0.96
    tiny_output_char_threshold: int = 2000
    smart_mode: bool = False
    smart_min_page_concurrency: int = 2
    smart_max_page_concurrency: int = 24
    smart_min_language_concurrency: int = 1
    smart_max_language_concurrency: int = 8
    smart_min_per_host_delay_seconds: float = 0.01
    smart_max_per_host_delay_seconds: float = 1.5
    smart_max_pages_per_language: int = 20000
    smart_max_discovered_urls_per_language: int = 50000


class PlannerConfig(BaseModel):
    prefer_current_stable: bool = True
    allow_external_same_org_docs: bool = True
    honor_sitemaps: bool = True
    discover_search_indexes: bool = True
    max_depth_default: int = 8
    crawl_mode: str = "full"
    preferred_locale: str = "en"
    locale_aliases: list[str] = Field(default_factory=lambda: ["en", "en-us", "en-gb", "english"])
    common_nonpreferred_locales: list[str] = Field(
        default_factory=lambda: [
            "de",
            "fr",
            "es",
            "it",
            "pt",
            "pt-br",
            "ja",
            "ko",
            "zh",
            "zh-cn",
            "zh-tw",
            "ru",
            "tr",
            "pl",
            "cs",
            "nl",
            "uk",
            "vi",
            "id",
        ]
    )
    important_path_keywords: list[str] = Field(
        default_factory=lambda: [
            "getting-started",
            "quickstart",
            "tutorial",
            "guide",
            "language-reference",
            "reference",
            "stdlib",
            "standard-library",
            "library",
            "syntax",
            "basics",
            "overview",
            "introduction",
            "manual",
            "spec",
            "book",
        ]
    )
    important_title_keywords: list[str] = Field(
        default_factory=lambda: [
            "overview",
            "introduction",
            "tutorial",
            "guide",
            "getting started",
            "reference",
            "language reference",
            "standard library",
            "library reference",
            "manual",
            "specification",
        ]
    )


class AppConfig(BaseModel):
    paths: PathsConfig
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)


def load_config(root: Path | None = None) -> AppConfig:
    resolved_root = (root or Path(__file__).resolve().parent.parent).resolve()
    config = AppConfig(paths=PathsConfig.from_root(resolved_root))
    config.paths.ensure()
    return config