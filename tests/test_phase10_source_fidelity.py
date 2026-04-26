from __future__ import annotations

import asyncio
import builtins
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from doc_ingest.compiler import LanguageOutputBuilder, write_streamed_compilation
from doc_ingest.config import load_config
from doc_ingest.models import SourceRunDiagnostics
from doc_ingest.pipeline import DocumentationPipeline
from doc_ingest.services import DocumentationService
from doc_ingest.sources import registry as registry_module
from doc_ingest.sources.base import AdapterEvent, AssetEvent, Document, DocumentEvent, LanguageCatalog, document_events
from doc_ingest.sources.registry import SourceRegistry
from doc_ingest.utils.filesystem import read_json

from .helpers import FixtureSource, long_markdown


@dataclass
class PluginSource:
    name: str = "plugin"

    async def list_languages(self, *, force_refresh: bool = False) -> list[LanguageCatalog]:
        return [LanguageCatalog(source=self.name, slug="plugin-lang", display_name="Plugin Lang")]

    def fetch(
        self,
        language: LanguageCatalog,
        mode: str,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[Document]:
        async def iterator() -> AsyncIterator[Document]:
            yield Document(topic="Reference", slug="intro", title="Intro", markdown=long_markdown("Intro"))

        return iterator()

    def events(
        self,
        language: LanguageCatalog,
        mode: str,
        diagnostics: SourceRunDiagnostics | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        return document_events(self.fetch(language, mode, diagnostics=diagnostics))


class FakeEntryPoint:
    def __init__(self, name: str, factory: Any) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> Any:
        return self._factory


class FakeEntryPoints(list):
    def select(self, *, group: str):
        assert group == "devdocsdownloader.sources"
        return self


def test_source_registry_loads_entry_point_plugins_and_isolates_failures(monkeypatch, tmp_path: Path) -> None:
    def plugin_factory(*, cache_dir: Path, runtime):
        assert cache_dir == tmp_path
        assert runtime is not None
        return PluginSource()

    def duplicate_factory(*, cache_dir: Path, runtime):
        return PluginSource(name="devdocs")

    def failing_factory(*, cache_dir: Path, runtime):
        raise RuntimeError("bad plugin")

    monkeypatch.setattr(
        registry_module.metadata,
        "entry_points",
        lambda: FakeEntryPoints(
            [
                FakeEntryPoint("plugin", plugin_factory),
                FakeEntryPoint("duplicate", duplicate_factory),
                FakeEntryPoint("failing", failing_factory),
            ]
        ),
    )

    registry = SourceRegistry(cache_dir=tmp_path)
    names = [source.name for source in registry.sources]

    assert names[:3] == ["devdocs", "mdn", "dash"]
    assert names.count("plugin") == 1
    assert names.count("devdocs") == 1
    assert asyncio.run(registry.resolve("Plugin Lang", source_name="plugin")) is not None


def test_service_catalog_includes_plugin_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        registry_module.metadata,
        "entry_points",
        lambda: FakeEntryPoints([FakeEntryPoint("plugin", lambda **_kwargs: PluginSource())]),
    )

    service = DocumentationService(load_config(root=tmp_path))
    rows = asyncio.run(service.list_languages(source="plugin"))

    assert [(row.language, row.source, row.slug) for row in rows] == [("Plugin Lang", "plugin", "plugin-lang")]


def test_cross_document_link_rewriting_exact_targets_and_code_fences(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="fixture", slug="link-lang", display_name="Link Lang")
    docs = [
        Document(
            topic="Reference",
            slug="alpha",
            title="Alpha",
            source_url="https://example.invalid/docs/alpha",
            markdown="\n".join(
                [
                    "# Alpha",
                    "",
                    "[Beta](https://example.invalid/docs/beta)",
                    "[Unknown](https://example.invalid/docs/missing)",
                    "![Diagram](https://example.invalid/assets/diagram.png)",
                    "",
                    "```markdown",
                    "[Beta](https://example.invalid/docs/beta)",
                    "```",
                    "",
                    "x" * 2500,
                ]
            ),
        ),
        Document(
            topic="Reference",
            slug="beta",
            title="Beta",
            source_url="https://example.invalid/docs/beta",
            markdown=long_markdown("Beta"),
        ),
    ]

    asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=FixtureSource("fixture", catalog, docs),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    alpha = (config.paths.markdown_dir / "link-lang" / "reference" / "alpha.md").read_text(encoding="utf-8")
    assert "[Beta](beta.md)" in alpha
    assert "[Unknown](https://example.invalid/docs/missing)" in alpha
    assert "![Diagram](https://example.invalid/assets/diagram.png)" in alpha
    assert "```markdown\n[Beta](https://example.invalid/docs/beta)\n```" in alpha


def test_asset_inventory_copies_deduplicates_and_rewrites_known_assets(tmp_path: Path) -> None:
    config = load_config(root=tmp_path)
    catalog = LanguageCatalog(source="fixture", slug="asset-lang", display_name="Asset Lang")

    class AssetSource(FixtureSource):
        def events(
            self,
            language: LanguageCatalog,
            mode: str,
            diagnostics: SourceRunDiagnostics | None = None,
        ) -> AsyncIterator[AdapterEvent]:
            async def iterator() -> AsyncIterator[AdapterEvent]:
                payload = b"diagram-bytes"
                yield AssetEvent(
                    path="diagram.png",
                    source_url="https://example.invalid/assets/diagram.png",
                    media_type="image/png",
                    content=payload,
                )
                yield AssetEvent(
                    path="diagram-copy.png",
                    source_url="https://example.invalid/assets/diagram-copy.png",
                    media_type="image/png",
                    content=payload,
                )
                yield AssetEvent(path="remote-only.png", source_url="https://example.invalid/assets/remote-only.png")
                yield DocumentEvent(
                    Document(
                        topic="Reference",
                        slug="assets",
                        title="Assets",
                        source_url="https://example.invalid/docs/assets",
                        markdown="![Diagram](https://example.invalid/assets/diagram.png)\n\n" + ("x" * 2500),
                    )
                )

            return iterator()

    report = asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=AssetSource("fixture", catalog, []),
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    language_dir = config.paths.markdown_dir / "asset-lang"
    manifest = read_json(language_dir / "assets" / "manifest.json", {})
    markdown = (language_dir / "reference" / "assets.md").read_text(encoding="utf-8")

    assert report.failures == []
    copied = [record for record in manifest["assets"] if record["status"] == "copied"]
    referenced = [record for record in manifest["assets"] if record["status"] == "referenced"]
    copied_paths = {record["output_path"] for record in copied}

    assert report.asset_inventory is not None
    assert report.asset_inventory.total == 3
    assert report.asset_inventory.copied == 2
    assert len(copied_paths) == 1
    assert referenced[0]["reason"] == "no local payload"
    assert "![Diagram](../assets/" in markdown
    assert read_json(language_dir / "_meta.json", {})["outputs"]["assets"]["total"] == 3


def test_asset_local_path_with_traversal_is_not_read(tmp_path: Path) -> None:
    builder = LanguageOutputBuilder(
        language_display="Asset Safety",
        language_slug="asset-safety",
        source="fixture",
        source_slug="asset-safety",
        source_url="",
        mode="full",
        output_root=tmp_path,
        assets=[AssetEvent(path="bad.png", local_path="../bad.png")],
    )
    builder.add(Document(topic="Reference", slug="safe", title="Safe", markdown=long_markdown("Safe")))
    plan = builder.build_plan()
    summary = write_streamed_compilation(plan)

    manifest = read_json(tmp_path / "asset-safety" / "assets" / "manifest.json", {})
    assert summary is not None
    assert summary.referenced == 1
    assert manifest["assets"][0]["status"] == "referenced"


def test_token_chunking_adds_token_fields_when_tiktoken_is_available(tmp_path: Path) -> None:
    pytest.importorskip("tiktoken")
    config = load_config(root=tmp_path)
    config.emit_chunks = True
    config.chunk_strategy = "tokens"
    config.chunk_max_tokens = 40
    config.chunk_overlap_tokens = 5
    catalog = LanguageCatalog(source="fixture", slug="token-lang", display_name="Token Lang")
    source = FixtureSource(
        "fixture",
        catalog,
        [Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha", repeat=20))],
    )

    asyncio.run(
        DocumentationPipeline(config)._run_language(
            source=source,
            catalog=catalog,
            mode="full",
            progress_tracker=None,
            validate_only=False,
        )
    )

    records = [
        json.loads(line)
        for line in (config.paths.markdown_dir / "token-lang" / "chunks" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert records
    assert records[0]["chunk_strategy"] == "tokens"
    assert records[0]["token_count"] <= 40
    assert "token_start" in records[0]
    assert (
        read_json(config.paths.markdown_dir / "token-lang" / "_meta.json", {})["outputs"]["chunks"]["strategy"]
        == "tokens"
    )


def test_token_chunking_missing_dependency_has_actionable_error(monkeypatch, tmp_path: Path) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    builder = LanguageOutputBuilder(
        language_display="Token Missing",
        language_slug="token-missing",
        source="fixture",
        source_slug="token-missing",
        source_url="",
        mode="full",
        output_root=tmp_path,
        emit_chunks=True,
        chunk_strategy="tokens",
    )
    builder.add(Document(topic="Reference", slug="alpha", title="Alpha", markdown=long_markdown("Alpha")))

    with pytest.raises(RuntimeError, match=r"pip install -e \.\[tokenizer\]"):
        builder.finalize()
