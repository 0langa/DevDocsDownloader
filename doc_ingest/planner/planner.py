from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from ..config import AppConfig
from ..models import LanguageEntry, PlannedSource

# Loaded once at import time.  Keys are normalised source URLs (no trailing slash).
_OVERRIDES_PATH = Path(__file__).parent.parent.parent / "doc_path_overrides.json"
_PATH_OVERRIDES: dict[str, dict] = {}
if _OVERRIDES_PATH.exists():
    try:
        _PATH_OVERRIDES = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass


def _norm_url(url: str) -> str:
    return url.rstrip("/")


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

        # Apply path-prefix overrides derived from doc_path_overrides.json
        override_entry = _PATH_OVERRIDES.get(_norm_url(source), {})
        override_start_urls: list[str] = override_entry.get("start_urls") or [source]
        override_path_prefixes: list[str] = override_entry.get("allowed_path_prefixes") or []
        if override_entry:
            # Expand allowed_domains to cover any extra hosts in override_start_urls
            for s_url in override_start_urls:
                extra = urlparse(s_url).netloc
                if extra:
                    allowed_domains.append(extra)
            if override_entry.get("note"):
                notes.append(f"Path override: {override_entry['note']}")

        return PlannedSource(
            language=language,
            strategy=strategy,
            crawl_mode=self.config.planner.crawl_mode, 
            start_urls=override_start_urls,
            notes=notes,
            allowed_domains=sorted(set(allowed_domains)),
            allowed_path_prefixes=override_path_prefixes,
            max_depth=self.config.planner.max_depth_default,
        )

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