from __future__ import annotations

import asyncio
import json
from pathlib import Path

from doc_ingest.sources.base import LanguageCatalog
from doc_ingest.sources.registry import SourceRegistry, _normalise_lang


class _StaticSource:
    def __init__(self, name: str, entries: list[LanguageCatalog]) -> None:
        self.name = name
        self._entries = entries

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return self._entries


def test_normalise_lang_handles_aliases_unicode_and_version_suffixes() -> None:
    assert _normalise_lang("Node.js") == "nodejs"
    assert _normalise_lang("node 20") == "nodejs20"
    assert _normalise_lang("py 3.12") == "python312"
    assert _normalise_lang("C＋＋") == "cpp"
    assert _normalise_lang(".NET") == "net"


def test_registry_resolves_common_aliases_and_versioned_inputs(tmp_path: Path) -> None:
    registry = SourceRegistry(cache_dir=tmp_path)
    registry.sources = [
        _StaticSource(
            "devdocs",
            [
                LanguageCatalog(source="devdocs", slug="python~3.12", display_name="Python", version="3.12"),
                LanguageCatalog(source="devdocs", slug="python~3.13", display_name="Python", version="3.13"),
                LanguageCatalog(source="devdocs", slug="typescript", display_name="TypeScript"),
                LanguageCatalog(source="devdocs", slug="net", display_name=".NET"),
            ],
        ),
        _StaticSource(
            "mdn",
            [
                LanguageCatalog(source="mdn", slug="javascript", display_name="JavaScript", aliases=["js"]),
                LanguageCatalog(source="mdn", slug="web-apis", display_name="Web APIs", aliases=["api", "web api"]),
            ],
        ),
        _StaticSource("dash", [LanguageCatalog(source="dash", slug="Vue", display_name="Vue.js")]),
    ]

    py_source, py_catalog = asyncio.run(registry.resolve("py"))
    js_source, js_catalog = asyncio.run(registry.resolve("js"))
    versioned_source, versioned_catalog = asyncio.run(registry.resolve("python 3.12"))
    fallback_source, fallback_catalog = asyncio.run(registry.resolve("vue 3"))
    dotnet_source, dotnet_catalog = asyncio.run(registry.resolve(".NET"))

    assert (py_source.name, py_catalog.slug) == ("devdocs", "python~3.13")
    assert (js_source.name, js_catalog.slug) == ("mdn", "javascript")
    assert (versioned_source.name, versioned_catalog.slug) == ("devdocs", "python~3.12")
    assert (fallback_source.name, fallback_catalog.slug) == ("dash", "Vue")
    assert (dotnet_source.name, dotnet_catalog.slug) == ("devdocs", "net")


def test_registry_suggestions_include_alias_and_version_variants(tmp_path: Path) -> None:
    registry = SourceRegistry(cache_dir=tmp_path)
    registry.sources = [
        _StaticSource("devdocs", [LanguageCatalog(source="devdocs", slug="python~3.13", display_name="Python")]),
        _StaticSource("mdn", [LanguageCatalog(source="mdn", slug="javascript", display_name="JavaScript")]),
    ]

    py_suggestions = asyncio.run(registry.suggest("py3", limit=4))
    js_suggestions = asyncio.run(registry.suggest("js", limit=4))

    assert ("devdocs", "Python") in py_suggestions
    assert ("mdn", "JavaScript") in js_suggestions


def test_registry_prefers_higher_quality_score_when_multiple_sources_match(tmp_path: Path) -> None:
    quality_history = tmp_path / "logs" / "quality_history.jsonl"
    quality_history.parent.mkdir(parents=True, exist_ok=True)
    quality_history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "language": "Python",
                        "source": "devdocs",
                        "slug": "python~3.13",
                        "run_date": "2026-05-01T00:00:00+00:00",
                        "validation_score": 0.72,
                    }
                ),
                json.dumps(
                    {
                        "language": "Python",
                        "source": "mdn",
                        "slug": "python",
                        "run_date": "2026-05-01T00:00:00+00:00",
                        "validation_score": 0.91,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(cache_dir=tmp_path, quality_history_path=quality_history)
    registry.sources = [
        _StaticSource("devdocs", [LanguageCatalog(source="devdocs", slug="python~3.13", display_name="Python")]),
        _StaticSource("mdn", [LanguageCatalog(source="mdn", slug="python", display_name="Python")]),
    ]
    source, catalog = asyncio.run(registry.resolve("python"))
    assert source.name == "mdn"
    assert catalog.slug == "python"
