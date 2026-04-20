from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

from ..adapters import apply_adapter
from ..config import AppConfig
from ..models import LanguageEntry, PlannedSource

KNOWN_PDF_HINTS = (".pdf", "/pdf", "manual", "spec", "standard")


class CrawlPlanner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def plan(self, language: LanguageEntry) -> PlannedSource:
        source = str(language.source_url)
        parsed = urlparse(source)
        notes: list[str] = []
        strategy = "html_recursive"

        if any(hint in source.lower() for hint in KNOWN_PDF_HINTS):
            strategy = "hybrid_manual_first"
            notes.append("Source suggests downloadable manual/specification.")
        elif parsed.netloc.endswith("learn.microsoft.com"):
            strategy = "html_recursive_with_sitemap"
            notes.append("Microsoft Learn docs often expose structured TOC and sitemap patterns.")
        elif parsed.netloc.endswith("docs.python.org") or parsed.netloc.endswith("go.dev"):
            strategy = "html_recursive_with_nav"
            notes.append("Known structured doc site with navigation-based traversal.")
        elif source.lower().endswith(".md"):
            strategy = "markdown_seed"
        elif parsed.netloc.endswith("iso.org"):
            strategy = "hybrid_manual_first"
            notes.append("Standards pages often require combining landing pages with downloadable assets.")

        allowed_domains = [parsed.netloc]
        if self.config.planner.allow_external_same_org_docs and parsed.netloc.startswith("www."):
            allowed_domains.append(parsed.netloc[4:])

        locale = self._detect_locale_hint(source)
        if locale:
            notes.append(f"Preferred locale locked to '{locale}'.")

        plan = PlannedSource(
            language=language,
            strategy=strategy,
            crawl_mode=self.config.planner.crawl_mode,
            start_urls=[source],
            notes=notes,
            allowed_domains=sorted(set(allowed_domains)),
            allowed_path_prefixes=[],
            max_depth=self.config.planner.max_depth_default,
        )
        plan, _adapter = apply_adapter(language, self.config, plan)
        return plan

    def _detect_locale_hint(self, source: str) -> str | None:
        parsed = urlparse(source)
        locale_aliases = {value.lower() for value in self.config.planner.locale_aliases}
        path_parts = [part.lower() for part in parsed.path.split("/") if part]
        for part in path_parts:
            if part in locale_aliases:
                return part

        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"lang", "locale", "hl"} and value.lower() in locale_aliases:
                return value.lower()

        return self.config.planner.preferred_locale.lower()
