from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import AppConfig
from .models import LanguageEntry, PlannedSource
from .utils.urls import normalize_url


@dataclass(slots=True)
class SiteAdapter:
    name: str = "generic"
    preferred_extractors: list[str] = field(default_factory=list)
    content_selectors: list[str] = field(default_factory=list)
    ignored_url_patterns: list[str] = field(default_factory=list)
    ignored_path_prefixes: list[str] = field(default_factory=list)
    include_changelog: bool = False

    def augment_plan(self, plan: PlannedSource) -> PlannedSource:
        plan.preferred_extractors = list(dict.fromkeys([*self.preferred_extractors, *plan.preferred_extractors]))
        plan.content_selectors = list(dict.fromkeys([*self.content_selectors, *plan.content_selectors]))
        plan.ignored_url_patterns = list(dict.fromkeys([*self.ignored_url_patterns, *plan.ignored_url_patterns]))
        plan.ignored_path_prefixes = list(dict.fromkeys([*self.ignored_path_prefixes, *plan.ignored_path_prefixes]))
        plan.include_changelog = plan.include_changelog or self.include_changelog
        return plan

    def order_hint(self, url: str, title: str, breadcrumbs: list[str]) -> str:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        trail = breadcrumbs or ([title] if title else [])
        return "/".join([*(segment.lower() for segment in trail[:4]), *(part.lower() for part in parts[-3:])])

    def should_ignore_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(pattern.lower() in lowered for pattern in self.ignored_url_patterns)


class PythonDocsAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="python-docs",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", "div.body", "div[role='main']"],
            ignored_url_patterns=["/genindex", "/search", "/py-modindex"],
        )


class MicrosoftLearnAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="microsoft-learn",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", "#main", "[data-bi-name='content']"],
            ignored_url_patterns=["/previous-versions/", "/contributors/", "/search"],
        )


class PHPManualAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="php-manual",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["#layout-content", "main", ".refentry"],
            ignored_url_patterns=["/manual/en/indexes", "/manual/en/faq", "/manual/en/about"],
        )


class TypeScriptAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="typescript-handbook",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", ".markdown", "article"],
            ignored_url_patterns=["/play", "/download", "/community"],
        )


def _load_override_map() -> dict[str, dict]:
    path = Path(__file__).resolve().parent.parent / "doc_path_overrides.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


OVERRIDES = _load_override_map()


def _build_override_plan(source_url: str) -> dict:
    normalized = normalize_url(source_url)
    return OVERRIDES.get(normalized, {}) or OVERRIDES.get(normalized.rstrip("/"), {})


def select_adapter(language: LanguageEntry, config: AppConfig) -> tuple[SiteAdapter, dict]:
    source = normalize_url(str(language.source_url))
    host = urlparse(source).netloc
    if host.endswith("docs.python.org"):
        return PythonDocsAdapter(), _build_override_plan(source)
    if host.endswith("learn.microsoft.com"):
        return MicrosoftLearnAdapter(), _build_override_plan(source)
    if host.endswith("php.net"):
        return PHPManualAdapter(), _build_override_plan(source)
    if host.endswith("typescriptlang.org"):
        return TypeScriptAdapter(), _build_override_plan(source)
    generic = SiteAdapter(
        name="generic",
        preferred_extractors=["html_docling", "html_readability"],
        content_selectors=config.planner.content_root_selectors,
        ignored_url_patterns=config.planner.ignored_url_tokens,
    )
    return generic, _build_override_plan(source)


def apply_adapter(language: LanguageEntry, config: AppConfig, plan: PlannedSource) -> tuple[PlannedSource, SiteAdapter]:
    adapter, override = select_adapter(language, config)
    if override:
        plan.start_urls = override.get("start_urls") or plan.start_urls
        plan.allowed_path_prefixes = list(dict.fromkeys([*(override.get("allowed_path_prefixes") or []), *plan.allowed_path_prefixes]))
        plan.notes.append(override.get("note", "adapter override applied"))
        extra_domains = {urlparse(url).netloc for url in plan.start_urls}
        plan.allowed_domains = sorted(set([*plan.allowed_domains, *extra_domains]))
    plan = adapter.augment_plan(plan)
    plan.notes.append(f"Adapter: {adapter.name}")
    return plan, adapter


def compile_ignored_patterns(config: AppConfig, plan: PlannedSource) -> list[re.Pattern[str]]:
    patterns = []
    for token in [*config.planner.ignored_url_tokens, *plan.ignored_url_patterns]:
        patterns.append(re.compile(re.escape(token), re.IGNORECASE))
    return patterns

