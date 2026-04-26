from __future__ import annotations

import logging
from difflib import get_close_matches
from importlib import metadata
from pathlib import Path
from typing import Any

from ..runtime import SourceRuntime
from .base import DocumentationSource, LanguageCatalog
from .dash import DashFeedSource
from .devdocs import DevDocsSource
from .mdn import MdnContentSource

LOGGER = logging.getLogger("doc_ingest.sources.registry")

# Names where MDN should be preferred over DevDocs/Dash.
_MDN_PREFERRED = {"html", "css", "http", "web-apis", "webassembly"}
ENTRY_POINT_GROUP = "devdocsdownloader.sources"


class SourceRegistry:
    def __init__(
        self, *, cache_dir: Path, package_root: Path | None = None, runtime: SourceRuntime | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.runtime = runtime or SourceRuntime()
        source_root = package_root or Path(__file__).parent
        core_topics_path = source_root / "devdocs_core.json"
        dash_seed_path = source_root / "dash_seed.json"
        self.sources: list[DocumentationSource] = [
            DevDocsSource(cache_dir=cache_dir, core_topics_path=core_topics_path, runtime=self.runtime),
            MdnContentSource(cache_dir=cache_dir, runtime=self.runtime),
            DashFeedSource(cache_dir=cache_dir, catalog_seed=dash_seed_path, runtime=self.runtime),
        ]
        self._load_entry_point_sources()

    def _load_entry_point_sources(self) -> None:
        known_names = {source.name for source in self.sources}
        try:
            entry_points = metadata.entry_points()
            selected = entry_points.select(group=ENTRY_POINT_GROUP)
        except Exception as exc:
            LOGGER.warning("Failed to inspect source plugins: %s", exc)
            return
        for entry_point in selected:
            try:
                factory = entry_point.load()
                source = _call_source_factory(factory, cache_dir=self.cache_dir, runtime=self.runtime)
            except Exception as exc:
                LOGGER.warning("Failed to load source plugin %s: %s", entry_point.name, exc)
                continue
            if source.name in known_names:
                LOGGER.warning(
                    "Skipping source plugin %s because source name %s already exists", entry_point.name, source.name
                )
                continue
            known_names.add(source.name)
            self.sources.append(source)

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
                source = self.get(source_name)
                if source is not None:
                    return source, match
            return None

        priority = ["mdn", "devdocs", "dash"] if needle in _MDN_PREFERRED else ["devdocs", "mdn", "dash"]
        for name in priority:
            match = _exact_match(catalogs.get(name, []), needle)
            if match:
                source = self.get(name)
                if source is not None:
                    return source, match
        return None

    async def resolve_many(
        self,
        language_names: list[str],
        *,
        force_refresh: bool = False,
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
        needle = language.strip().lower()
        priority = {
            name: idx
            for idx, name in enumerate(
                ["mdn", "devdocs", "dash"] if needle in _MDN_PREFERRED else ["devdocs", "mdn", "dash"]
            )
        }
        scored: list[tuple[tuple[int, int, str, tuple, str], str, str]] = []
        pool: list[tuple[str, str, str, str, LanguageCatalog]] = []
        for source_name, entries in catalogs.items():
            for entry in entries:
                display = entry.display_name.lower()
                slug = entry.slug.lower()
                family = slug.split("~", 1)[0]
                pool.append((display, slug, family, source_name, entry))
                bucket = _suggestion_bucket(needle=needle, display=display, slug=slug, family=family)
                if bucket is not None:
                    scored.append(
                        (
                            (
                                bucket,
                                priority.get(source_name, 99),
                                entry.display_name.lower(),
                                _version_key(entry),
                                source_name,
                            ),
                            source_name,
                            entry.display_name,
                        )
                    )
        names = [item[0] for item in pool]
        matches = get_close_matches(language.lower(), names, n=limit, cutoff=0.5)
        matched_names = set(matches)
        for display, _slug, _family, source_name, entry in pool:
            if display in matched_names:
                scored.append(
                    (
                        (
                            4,
                            priority.get(source_name, 99),
                            entry.display_name.lower(),
                            _version_key(entry),
                            source_name,
                        ),
                        source_name,
                        entry.display_name,
                    )
                )
        out: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for _score, source_name, display in sorted(scored):
            if (source_name, display) not in seen:
                out.append((source_name, display))
                seen.add((source_name, display))
            if len(out) >= limit:
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


def _suggestion_bucket(*, needle: str, display: str, slug: str, family: str) -> int | None:
    if display == needle or slug == needle or family == needle:
        return 0
    if display.startswith(needle) or family.startswith(needle):
        return 1
    if needle in display or needle in slug:
        return 2
    return None


def _call_source_factory(factory: Any, *, cache_dir: Path, runtime: SourceRuntime) -> DocumentationSource:
    try:
        source = factory(cache_dir=cache_dir, runtime=runtime)
    except TypeError:
        source = factory(cache_dir, runtime)
    if not hasattr(source, "name"):
        raise TypeError("Source plugin factory did not return a DocumentationSource-like object")
    return source
