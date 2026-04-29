from __future__ import annotations

import logging
import re
import unicodedata
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
_CANONICAL_LANGUAGE_ALIASES = {
    "cplusplus": "cpp",
    "cs": "csharp",
    "dotnet": "net",
    "ecmascript": "javascript",
    "golang": "go",
    "javascript": "javascript",
    "js": "javascript",
    "node": "nodejs",
    "nodejs": "nodejs",
    "py": "python",
    "python": "python",
    "ts": "typescript",
    "typescript": "typescript",
}
_TRAILING_DIGITS_RE = re.compile(r"^(?P<base>[a-z][a-z0-9]*?)(?P<digits>\d+)$")


class SourceRegistry:
    def __init__(
        self, *, cache_dir: Path, package_root: Path | None = None, runtime: SourceRuntime | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.runtime = runtime or SourceRuntime()
        source_root = package_root or Path(__file__).parent
        core_topics_path = source_root / "devdocs_core.json"
        self.sources: list[DocumentationSource] = [
            DevDocsSource(cache_dir=cache_dir, core_topics_path=core_topics_path, runtime=self.runtime),
            MdnContentSource(cache_dir=cache_dir, runtime=self.runtime),
            DashFeedSource(cache_dir=cache_dir, runtime=self.runtime),
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

    async def catalog(
        self,
        *,
        force_refresh: bool = False,
        source_name: str | None = None,
    ) -> dict[str, list[LanguageCatalog]]:
        result: dict[str, list[LanguageCatalog]] = {}
        sources = self.sources
        if source_name is not None:
            source = self.get(source_name)
            sources = [source] if source is not None else []
        for source in sources:
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
        catalogs = await self.catalog(force_refresh=force_refresh, source_name=source_name)

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
                aliases = [alias.lower() for alias in entry.aliases]
                pool.append((display, slug, family, source_name, entry))
                bucket = _suggestion_bucket(needle=needle, display=display, slug=slug, family=family, aliases=aliases)
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


def _normalise_lang(s: str) -> str:
    """Normalise a language name token for fuzzy matching.

    Maps common display-name conventions to the slug-style form used by source
    catalogs, e.g. "C++" → "cpp", "C#" → "csharp", "Node.js" → "nodejs".
    """
    normalized = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = normalized.replace("++", "pp")  # C++ → cpp
    normalized = normalized.replace("#", "sharp")  # C# → csharp
    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("/", " ")
    normalized = normalized.replace("\\", " ")
    normalized = normalized.replace(".", " ")
    normalized = normalized.replace("-", " ")
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\bversion\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    normalized = _canonical_language_alias(normalized)
    match = _TRAILING_DIGITS_RE.match(normalized)
    if match:
        normalized = _canonical_language_alias(match.group("base")) + match.group("digits")
    return normalized


def _canonical_language_alias(token: str) -> str:
    return _CANONICAL_LANGUAGE_ALIASES.get(token, token)


def _version_digits(version: str) -> set[str]:
    digits = [chunk for chunk in ("".join(ch for ch in part if ch.isdigit()) for part in version.split(".")) if chunk]
    if not digits:
        return set()
    out = {"".join(digits)}
    if digits[0]:
        out.add(digits[0])
    return out


def _match_terms(entry: LanguageCatalog) -> tuple[set[str], set[str], set[str]]:
    raw_terms = {
        token
        for token in {
            entry.display_name.lower(),
            entry.slug.lower(),
            entry.slug.lower().split("~", 1)[0],
            *(alias.lower() for alias in entry.aliases),
        }
        if token
    }
    base_terms = {_normalise_lang(token) for token in raw_terms if token}
    version_terms = {
        f"{base}{suffix}" for base in base_terms for suffix in _version_digits(entry.version or "") if base and suffix
    }
    return raw_terms, base_terms, version_terms


def _has_trailing_version_suffix(needle_norm: str, token_norm: str) -> bool:
    if not needle_norm or not token_norm or not needle_norm.startswith(token_norm):
        return False
    suffix = needle_norm[len(token_norm) :]
    return bool(suffix) and suffix.isdigit()


def _exact_match(entries: list[LanguageCatalog], needle: str) -> LanguageCatalog | None:
    if not entries:
        return None
    needle_norm = _normalise_lang(needle)
    exact_version: list[LanguageCatalog] = []
    exact: list[LanguageCatalog] = []
    version_fallback: list[LanguageCatalog] = []
    prefix: list[LanguageCatalog] = []
    contains: list[LanguageCatalog] = []
    for entry in entries:
        raw_terms, base_terms, version_terms = _match_terms(entry)
        normalized_terms = base_terms | version_terms
        if needle_norm and needle_norm in version_terms:
            exact_version.append(entry)
        elif needle in raw_terms or (needle_norm and needle_norm in normalized_terms):
            exact.append(entry)
        elif needle_norm and any(_has_trailing_version_suffix(needle_norm, token) for token in base_terms):
            version_fallback.append(entry)
        elif any(token.startswith(needle) for token in raw_terms) or (
            needle_norm and any(token.startswith(needle_norm) for token in normalized_terms)
        ):
            prefix.append(entry)
        elif any(needle in token for token in raw_terms) or (
            needle_norm and any(needle_norm in token for token in normalized_terms)
        ):
            contains.append(entry)

    def _best(bucket: list[LanguageCatalog]) -> LanguageCatalog | None:
        if not bucket:
            return None
        return sorted(bucket, key=_version_key, reverse=True)[0]

    return _best(exact_version) or _best(exact) or _best(version_fallback) or _best(prefix) or _best(contains)


def _suggestion_bucket(*, needle: str, display: str, slug: str, family: str, aliases: list[str]) -> int | None:
    raw_terms = {display, slug, family, *aliases}
    base_terms = {_normalise_lang(token) for token in raw_terms if token}
    needle_norm = _normalise_lang(needle)
    if (
        needle in raw_terms
        or (needle_norm and needle_norm in base_terms)
        or (needle_norm and any(_has_trailing_version_suffix(needle_norm, token) for token in base_terms))
    ):
        return 0
    if any(token.startswith(needle) for token in raw_terms) or (
        needle_norm and any(token.startswith(needle_norm) for token in base_terms)
    ):
        return 1
    if any(needle in token for token in raw_terms) or (
        needle_norm and any(needle_norm in token for token in base_terms)
    ):
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
