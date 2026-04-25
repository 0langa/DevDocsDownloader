from __future__ import annotations

import logging
from difflib import get_close_matches
from pathlib import Path

from .base import DocumentationSource, LanguageCatalog
from .dash import DashFeedSource
from .devdocs import DevDocsSource
from .mdn import MdnContentSource

LOGGER = logging.getLogger("doc_ingest.sources.registry")

# Names where MDN should be preferred over DevDocs/Dash.
_MDN_PREFERRED = {"html", "css", "http", "web-apis", "webassembly"}


class SourceRegistry:
    def __init__(self, *, cache_dir: Path, package_root: Path | None = None) -> None:
        self.cache_dir = cache_dir
        source_root = package_root or Path(__file__).parent
        core_topics_path = source_root / "devdocs_core.json"
        dash_seed_path = source_root / "dash_seed.json"
        self.sources: list[DocumentationSource] = [
            DevDocsSource(cache_dir=cache_dir, core_topics_path=core_topics_path),
            MdnContentSource(cache_dir=cache_dir),
            DashFeedSource(cache_dir=cache_dir, catalog_seed=dash_seed_path),
        ]

    def get(self, name: str) -> DocumentationSource | None:
        for source in self.sources:
            if source.name == name:
                return source
        return None

    async def catalog(self, *, force_refresh: bool = False) -> dict[str, list[LanguageCatalog]]:
        result: dict[str, list[LanguageCatalog]] = {}
        for source in self.sources:
            try:
                result[source.name] = await source.list_languages(force_refresh=force_refresh)
            except Exception as exc:
                LOGGER.warning("Failed to load %s catalog: %s", source.name, exc)
                result[source.name] = []
        return result

    async def resolve(
        self,
        language: str,
        *,
        source_name: str | None = None,
        force_refresh: bool = False,
    ) -> tuple[DocumentationSource, LanguageCatalog] | None:
        needle = language.strip().lower()
        catalogs = await self.catalog(force_refresh=force_refresh)

        if source_name:
            entries = catalogs.get(source_name, [])
            match = _exact_match(entries, needle)
            if match:
                return self.get(source_name), match
            return None

        priority = ["mdn", "devdocs", "dash"] if needle in _MDN_PREFERRED else ["devdocs", "mdn", "dash"]
        for name in priority:
            match = _exact_match(catalogs.get(name, []), needle)
            if match:
                return self.get(name), match
        return None

    async def resolve_many(
        self, language_names: list[str], *, force_refresh: bool = False,
    ) -> tuple[list[tuple[str, DocumentationSource, LanguageCatalog]], list[str]]:
        """Resolve a list of language names, deduplicating by catalog slug."""
        resolved: list[tuple[str, DocumentationSource, LanguageCatalog]] = []
        missing: list[str] = []
        seen_keys: set[tuple[str, str]] = set()
        for name in language_names:
            match = await self.resolve(name, force_refresh=force_refresh)
            if match is None:
                missing.append(name)
                continue
            source, catalog = match
            key = (source.name, catalog.slug)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            resolved.append((name, source, catalog))
        return resolved, missing

    async def all_languages(self, *, force_refresh: bool = False) -> list[tuple[DocumentationSource, LanguageCatalog]]:
        """Every language across every source, deduplicated on display name (best pick per name)."""
        catalogs = await self.catalog(force_refresh=force_refresh)
        picked: dict[str, tuple[DocumentationSource, LanguageCatalog]] = {}
        priority = {name: idx for idx, name in enumerate(["devdocs", "mdn", "dash"])}
        for source_name, entries in catalogs.items():
            source = self.get(source_name)
            if source is None:
                continue
            for entry in entries:
                key = entry.display_name.lower()
                existing = picked.get(key)
                if existing is None:
                    picked[key] = (source, entry)
                    continue
                existing_source, existing_entry = existing
                if priority.get(source_name, 99) < priority.get(existing_source.name, 99):
                    picked[key] = (source, entry)
                elif source_name == existing_source.name and _version_key(entry) > _version_key(existing_entry):
                    picked[key] = (source, entry)
        return list(picked.values())

    async def suggest(self, language: str, *, limit: int = 8) -> list[tuple[str, str]]:
        catalogs = await self.catalog()
        pool: list[tuple[str, str, str]] = []
        for source_name, entries in catalogs.items():
            for entry in entries:
                pool.append((entry.display_name.lower(), source_name, entry.display_name))
        names = [item[0] for item in pool]
        matches = get_close_matches(language.lower(), names, n=limit, cutoff=0.5)
        out: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for match in matches:
            for lowered, source_name, display in pool:
                if lowered == match and (source_name, display) not in seen:
                    out.append((source_name, display))
                    seen.add((source_name, display))
                    break
        return out


def _version_key(catalog: LanguageCatalog) -> tuple:
    version = catalog.version or ""
    parts: list[int] = []
    for chunk in version.replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return (tuple(parts), version)


def _exact_match(entries: list[LanguageCatalog], needle: str) -> LanguageCatalog | None:
    if not entries:
        return None
    exact: list[LanguageCatalog] = []
    prefix: list[LanguageCatalog] = []
    contains: list[LanguageCatalog] = []
    for entry in entries:
        display = entry.display_name.lower()
        slug = entry.slug.lower()
        family = slug.split("~", 1)[0]
        if display == needle or slug == needle or family == needle:
            exact.append(entry)
        elif display.startswith(needle) or family.startswith(needle):
            prefix.append(entry)
        elif needle in display or needle in slug:
            contains.append(entry)

    def _best(bucket: list[LanguageCatalog]) -> LanguageCatalog | None:
        if not bucket:
            return None
        return sorted(bucket, key=_version_key, reverse=True)[0]

    return _best(exact) or _best(prefix) or _best(contains)
