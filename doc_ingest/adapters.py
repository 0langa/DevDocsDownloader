from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import AppConfig
from .models import LanguageEntry, PlannedSource
from .utils.text import slugify
from .utils.urls import normalize_url


@dataclass(slots=True)
class SiteAdapter:
    name: str = "generic"
    preferred_extractors: list[str] = field(default_factory=list)
    content_selectors: list[str] = field(default_factory=list)
    ignored_url_patterns: list[str] = field(default_factory=list)
    ignored_path_prefixes: list[str] = field(default_factory=list)
    boilerplate_patterns: list[str] = field(default_factory=list)
    ordering_keywords: list[str] = field(default_factory=list)
    nav_label_selectors: list[str] = field(default_factory=list)
    link_strip_selectors: list[str] = field(default_factory=list)
    breadcrumb_selectors: list[str] = field(default_factory=lambda: [".breadcrumb a", ".breadcrumbs a", "nav[aria-label='breadcrumb'] a"])
    section_aliases: dict[str, str] = field(default_factory=dict)
    ignored_heading_titles: list[str] = field(default_factory=list)
    similarity_threshold: float = 0.96
    browser_retry_word_count: int = 50
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
        priority = self.page_priority(url, title, breadcrumbs)
        return f"{priority:03d}/" + "/".join([*(segment.lower() for segment in trail[:4]), *(part.lower() for part in parts[-3:])])

    def should_ignore_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(pattern.lower() in lowered for pattern in self.ignored_url_patterns)

    def page_priority(self, url: str, title: str, breadcrumbs: list[str]) -> int:
        text = " ".join([url.lower(), title.lower(), *[crumb.lower() for crumb in breadcrumbs]])
        for index, keyword in enumerate(self.ordering_keywords, start=1):
            if keyword in text:
                return index
        return 999

    def clean_markdown(self, markdown: str) -> str:
        cleaned = markdown
        for pattern in self.boilerplate_patterns:
            cleaned = re.sub(pattern, "", cleaned)
        return cleaned

    def content_root_candidates(self) -> list[str]:
        return self.content_selectors or ["main", "article", "[role='main']", ".main-content", ".content", "body"]

    def discovery_strip_candidates(self) -> list[str]:
        return self.link_strip_selectors or [
            "nav",
            "header",
            "footer",
            "aside",
            ".sidebar",
            ".toc",
            ".breadcrumbs",
            ".breadcrumb",
            ".cookie",
            ".consent",
            ".advertisement",
            ".feedback",
        ]

    def breadcrumb_candidates(self) -> list[str]:
        return self.breadcrumb_selectors

    def should_retry_with_browser(self, *, asset_type: str, fetch_method: str, word_count: int, extraction_score: float | None) -> bool:
        if asset_type != "html" or fetch_method == "browser":
            return False
        if word_count < self.browser_retry_word_count:
            return True
        return (extraction_score or 0.0) < 0.28

    def canonical_section_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title).strip(" -:\t\n")
        if not cleaned:
            return "Content"
        return self.section_aliases.get(cleaned.lower(), cleaned)

    def should_ignore_heading(self, title: str) -> bool:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", title.lower())).strip()
        return normalized in {value.lower() for value in self.ignored_heading_titles}

    def section_path(self, url: str, title: str, breadcrumbs: list[str], heading: str | None = None) -> tuple[str, str]:
        cleaned_crumbs = [self.canonical_section_title(crumb) for crumb in breadcrumbs if crumb.strip()]
        fragment = self.canonical_section_title(heading or title)
        if cleaned_crumbs:
            top = cleaned_crumbs[0]
            subsection = cleaned_crumbs[1] if len(cleaned_crumbs) > 1 else fragment
            if subsection.lower() == top.lower():
                subsection = fragment
            return top, subsection

        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        ignored = {"docs", "documentation", "index", "latest", "stable", "en", "reference"}
        normalized_parts = [self.canonical_section_title(part.replace("-", " ").replace("_", " ")) for part in parts if part.lower() not in ignored and not part.isdigit()]
        top = normalized_parts[0] if normalized_parts else self.canonical_section_title(title)
        subsection = fragment
        if subsection.lower() == top.lower() and len(normalized_parts) > 1:
            subsection = normalized_parts[-1]
        return top, subsection

    def dedupe_similarity_threshold(self) -> float:
        return self.similarity_threshold

    def subsection_priority(self, section: str, subsection: str) -> tuple[int, str]:
        text = f"{section} {subsection}".lower()
        for index, keyword in enumerate(self.ordering_keywords, start=1):
            if keyword in text:
                return index, slugify(subsection)
        return 999, slugify(subsection)

    def group_name(self, url: str, title: str, breadcrumbs: list[str]) -> str:
        return self.section_path(url, title, breadcrumbs)[0]


class PythonDocsAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="python-docs",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", "div.body", "div[role='main']"],
            ignored_url_patterns=["/genindex", "/search", "/py-modindex"],
            boilerplate_patterns=[r"(?im)^next topic\s*$", r"(?im)^previous topic\s*$", r"(?im)^this page\s*$"],
            ordering_keywords=["tutorial", "using", "reference", "library", "c-api", "extending", "faq"],
            section_aliases={"library reference": "Library", "language reference": "Reference", "python setup and usage": "Using Python"},
            ignored_heading_titles=["navigation", "next topic", "previous topic", "this page"],
        )


class MicrosoftLearnAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="microsoft-learn",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", "#main", "[data-bi-name='content']"],
            ignored_url_patterns=["/previous-versions/", "/contributors/", "/search"],
            boilerplate_patterns=[r"(?im)^in this article\s*$", r"(?im)^related content\s*$", r"(?im)^additional resources\s*$"],
            ordering_keywords=["overview", "quickstart", "tutorial", "how-to", "concept", "reference"],
            link_strip_selectors=["#ms--additional-resources", "#right-container", ".buttons", "nav", "header", "footer", ".contributors-holder"],
        )


class PHPManualAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="php-manual",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["#layout-content", "main", ".refentry"],
            ignored_url_patterns=["/manual/en/indexes", "/manual/en/faq", "/manual/en/about"],
            boilerplate_patterns=[r"(?im)^user contributed notes\s*$", r"(?im)^found a problem\?\s*$"],
            ordering_keywords=["install", "language", "security", "features", "reference", "book"],
            similarity_threshold=0.94,
        )


class TypeScriptAdapter(SiteAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="typescript-handbook",
            preferred_extractors=["html_docling", "html_readability"],
            content_selectors=["main", ".markdown", "article"],
            ignored_url_patterns=["/play", "/download", "/community"],
            boilerplate_patterns=[r"(?im)^on this page\s*$", r"(?im)^give feedback\s*$"],
            ordering_keywords=["introduction", "basic", "handbook", "reference", "release notes"],
            section_aliases={"type manipulation": "Type Manipulation", "declaration files": "Declaration Files"},
            ignored_heading_titles=[
                "community",
                "customize",
                "is this page helpful",
                "next steps",
                "on this page",
                "popular documentation pages",
            ],
        )


def _load_override_map() -> dict[str, dict]:
    path = Path(__file__).resolve().parent.parent / "source-documents" / "doc_path_overrides.json"
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
