from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..utils.filesystem import read_json, write_json
from .base import LanguageCatalog


@dataclass(slots=True)
class DiscoveryManifest:
    source: str
    source_root_url: str
    discovery_strategy: str
    entries: list[LanguageCatalog] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


def load_manifest(path: Path) -> DiscoveryManifest | None:
    payload = read_json(path, None)
    if not isinstance(payload, dict):
        return None
    entries_payload = payload.get("entries")
    if not isinstance(entries_payload, list):
        return None
    try:
        entries = [_catalog_from_dict(entry) for entry in entries_payload if isinstance(entry, dict)]
    except Exception:
        return None
    return DiscoveryManifest(
        source=str(payload.get("source") or ""),
        source_root_url=str(payload.get("source_root_url") or ""),
        discovery_strategy=str(payload.get("discovery_strategy") or ""),
        entries=entries,
        fetched_at=str(payload.get("fetched_at") or datetime.now(UTC).isoformat()),
        warnings=_string_list(payload.get("warnings")),
        errors=_string_list(payload.get("errors")),
        fallback_used=bool(payload.get("fallback_used", False)),
        fallback_reason=str(payload.get("fallback_reason") or ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
    )


def save_manifest(path: Path, manifest: DiscoveryManifest) -> None:
    write_json(
        path,
        {
            "source": manifest.source,
            "source_root_url": manifest.source_root_url,
            "discovery_strategy": manifest.discovery_strategy,
            "fetched_at": manifest.fetched_at,
            "entries": [_catalog_to_dict(entry) for entry in manifest.entries],
            "warnings": manifest.warnings,
            "errors": manifest.errors,
            "fallback_used": manifest.fallback_used,
            "fallback_reason": manifest.fallback_reason,
            "diagnostics": manifest.diagnostics,
        },
    )


def manifest_languages(path: Path) -> list[LanguageCatalog]:
    manifest = load_manifest(path)
    if manifest is None:
        return []
    return [entry for entry in manifest.entries if entry.support_level != "ignored"]


def _catalog_to_dict(entry: LanguageCatalog) -> dict[str, Any]:
    return {
        "source": entry.source,
        "slug": entry.slug,
        "display_name": entry.display_name,
        "version": entry.version,
        "core_topics": list(entry.core_topics),
        "all_topics": list(entry.all_topics),
        "size_hint": entry.size_hint,
        "homepage": entry.homepage,
        "aliases": list(entry.aliases),
        "support_level": entry.support_level,
        "discovery_reason": entry.discovery_reason,
        "discovery_metadata": dict(entry.discovery_metadata),
    }


def _catalog_from_dict(payload: dict[str, Any]) -> LanguageCatalog:
    return LanguageCatalog(
        source=str(payload.get("source") or ""),
        slug=str(payload.get("slug") or ""),
        display_name=str(payload.get("display_name") or payload.get("slug") or ""),
        version=str(payload.get("version") or ""),
        core_topics=list(payload.get("core_topics") or []),
        all_topics=list(payload.get("all_topics") or []),
        size_hint=int(payload.get("size_hint") or 0),
        homepage=str(payload.get("homepage") or ""),
        aliases=_string_list(payload.get("aliases")),
        support_level=str(payload.get("support_level") or "supported"),  # type: ignore[arg-type]
        discovery_reason=str(payload.get("discovery_reason") or ""),
        discovery_metadata=dict(payload.get("discovery_metadata") or {}),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
