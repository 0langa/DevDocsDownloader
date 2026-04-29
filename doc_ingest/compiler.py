from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlparse

import yaml  # type: ignore[import-untyped]

from .models import AssetInventorySummary, AssetRecord, DocumentArtifactCheckpoint, TopicStats
from .sources.base import AssetEvent, Document
from .utils.filesystem import DurabilityMode, write_bytes, write_json, write_text, write_text_parts
from .utils.text import slugify


class CompiledOutput:
    def __init__(
        self,
        *,
        total_documents: int,
        topics: list[TopicStats],
        output_path: Path,
        asset_inventory: AssetInventorySummary | None = None,
    ) -> None:
        self.total_documents = total_documents
        self.topics = topics
        self.output_path = output_path
        self.asset_inventory = asset_inventory


@dataclass(slots=True)
class CompilationDocument:
    title: str
    slug: str
    source_url: str
    order_hint: int
    path: Path
    fragment_path: Path | None = None
    document: Document | None = None


@dataclass(slots=True)
class CompilationTopic:
    name: str
    slug: str
    directory: Path
    documents: list[CompilationDocument] = field(default_factory=list)


@dataclass(slots=True)
class CompilationPlan:
    language_display: str
    language_slug: str
    source: str
    source_slug: str
    source_url: str
    mode: str
    language_dir: Path
    consolidated_path: Path
    topics: list[CompilationTopic]
    topic_stats: list[TopicStats]
    total_documents: int
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
    chunk_strategy: str = "chars"
    chunk_max_tokens: int = 1_000
    chunk_overlap_tokens: int = 100
    assets: list[AssetEvent] = field(default_factory=list)


@dataclass(slots=True)
class RenderedCompilation:
    files: dict[Path, str]
    meta_path: Path
    meta: dict[str, Any]
    output_path: Path
    topic_stats: list[TopicStats]
    total_documents: int
    asset_inventory: AssetInventorySummary | None = None


class LanguageOutputBuilder:
    def __init__(
        self,
        *,
        language_display: str,
        language_slug: str,
        source: str,
        source_slug: str,
        source_url: str,
        mode: str,
        output_root: Path,
        durability: DurabilityMode = "balanced",
        emit_document_frontmatter: bool = False,
        emit_chunks: bool = False,
        chunk_max_chars: int = 8_000,
        chunk_overlap_chars: int = 400,
        chunk_strategy: str = "chars",
        chunk_max_tokens: int = 1_000,
        chunk_overlap_tokens: int = 100,
        assets: list[AssetEvent] | None = None,
    ) -> None:
        self.language_display = language_display
        self.language_slug = language_slug
        self.source = source
        self.source_slug = source_slug
        self.source_url = source_url
        self.mode = mode
        self.durability = durability
        self.emit_document_frontmatter = emit_document_frontmatter
        self.emit_chunks = emit_chunks
        self.chunk_max_chars = chunk_max_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.chunk_strategy = chunk_strategy
        self.chunk_max_tokens = chunk_max_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.assets = list(assets or [])
        self.language_dir = output_root / language_slug
        self.language_dir.mkdir(parents=True, exist_ok=True)
        self.fragments_dir = self.language_dir / "_fragments"
        self.fragments_dir.mkdir(parents=True, exist_ok=True)

        self._topic_docs: dict[str, list[CompilationDocument]] = {}
        self._topic_order: list[str] = []
        self._used_slugs: dict[str, set[str]] = {}
        self.total_documents = 0

    def add(self, document: Document) -> CompilationDocument:
        topic = document.topic.strip() or "Reference"
        if topic not in self._topic_docs:
            self._topic_docs[topic] = []
            self._topic_order.append(topic)
            self._used_slugs[topic] = set()

        slug_base = slugify(document.slug or document.title)
        slug = _unique_slug(slug_base, self._used_slugs[topic])
        self._used_slugs[topic].add(slug)
        document.slug = slug

        topic_slug = slugify(topic)
        topic_dir = self.language_dir / topic_slug
        per_doc_path = topic_dir / f"{document.slug}.md"
        fragment_path = self.fragments_dir / f"{self.total_documents:08d}-{topic_slug}-{document.slug}.md"
        write_text(
            per_doc_path,
            render_document(
                document,
                topic=topic,
                language=self.language_display,
                language_slug=self.language_slug,
                source=self.source,
                source_slug=self.source_slug,
                mode=self.mode,
                emit_frontmatter=self.emit_document_frontmatter,
            ),
            durability=self.durability,
        )
        write_text(fragment_path, render_consolidated_document_fragment(document), durability=self.durability)
        artifact = CompilationDocument(
            title=document.title,
            slug=document.slug,
            source_url=document.source_url,
            order_hint=document.order_hint,
            path=per_doc_path,
            fragment_path=fragment_path,
            document=document,
        )
        self._topic_docs[topic].append(artifact)
        self.total_documents += 1
        return artifact

    def preload_artifact(self, artifact: DocumentArtifactCheckpoint) -> None:
        topic = artifact.topic.strip() or "Reference"
        if topic not in self._topic_docs:
            self._topic_docs[topic] = []
            self._topic_order.append(topic)
            self._used_slugs[topic] = set()
        self._used_slugs[topic].add(artifact.slug)
        fragment_path = Path(artifact.fragment_path)
        self._topic_docs[topic].append(
            CompilationDocument(
                title=artifact.title,
                slug=artifact.slug,
                source_url=artifact.source_url,
                order_hint=artifact.order_hint,
                path=Path(artifact.path),
                fragment_path=fragment_path if fragment_path.exists() else None,
                document=None,
            )
        )
        self.total_documents += 1

    def finalize(self) -> CompiledOutput:
        plan = self.build_plan()
        asset_inventory = write_streamed_compilation(plan, durability=self.durability)
        return CompiledOutput(
            total_documents=plan.total_documents,
            topics=plan.topic_stats,
            output_path=plan.consolidated_path,
            asset_inventory=asset_inventory,
        )

    def build_plan(self) -> CompilationPlan:
        topic_stats: list[TopicStats] = []
        planned_topics: list[CompilationTopic] = []

        for topic in self._topic_order:
            topic_slug = slugify(topic)
            topic_dir = self.language_dir / topic_slug
            documents = self._topic_docs[topic]
            planned_topic = CompilationTopic(name=topic, slug=topic_slug, directory=topic_dir)
            for doc in documents:
                planned_topic.documents.append(doc)
            planned_topics.append(planned_topic)
            topic_stats.append(TopicStats(topic=topic, document_count=len(documents)))

        return CompilationPlan(
            language_display=self.language_display,
            language_slug=self.language_slug,
            source=self.source,
            source_slug=self.source_slug,
            source_url=self.source_url,
            mode=self.mode,
            language_dir=self.language_dir,
            consolidated_path=self.language_dir / f"{self.language_slug}.md",
            topics=planned_topics,
            topic_stats=topic_stats,
            total_documents=self.total_documents,
            emit_document_frontmatter=self.emit_document_frontmatter,
            emit_chunks=self.emit_chunks,
            chunk_max_chars=self.chunk_max_chars,
            chunk_overlap_chars=self.chunk_overlap_chars,
            chunk_strategy=self.chunk_strategy,
            chunk_max_tokens=self.chunk_max_tokens,
            chunk_overlap_tokens=self.chunk_overlap_tokens,
            assets=self.assets,
        )


def render_compilation(plan: CompilationPlan) -> RenderedCompilation:
    files: dict[Path, str] = {}
    topic_docs = {
        topic.name: [
            item.document
            or Document(
                topic=topic.name,
                slug=item.slug,
                title=item.title,
                markdown=_artifact_fragment_text(item),
                source_url=item.source_url,
                order_hint=item.order_hint,
            )
            for item in topic.documents
        ]
        for topic in plan.topics
    }
    topic_order = [topic.name for topic in plan.topics]

    for topic in plan.topics:
        section_lines = [
            f"# {topic.name}",
            "",
            f"_{len(topic.documents)} document(s) from {plan.source}_",
            "",
            "## Contents",
            "",
        ]
        for planned_doc in topic.documents:
            doc = planned_doc.document
            if doc is not None:
                files[planned_doc.path] = render_document(
                    doc,
                    topic=topic.name,
                    language=plan.language_display,
                    language_slug=plan.language_slug,
                    source=plan.source,
                    source_slug=plan.source_slug,
                    mode=plan.mode,
                    emit_frontmatter=plan.emit_document_frontmatter,
                )
            section_lines.append(f"- [{planned_doc.title}]({planned_doc.slug}.md)")
        section_lines.append("")
        files[topic.directory / "_section.md"] = "\n".join(section_lines) + "\n"

    files[plan.language_dir / "index.md"] = _render_index(
        language=plan.language_display,
        slug=plan.language_slug,
        source=plan.source,
        source_slug=plan.source_slug,
        source_url=plan.source_url,
        mode=plan.mode,
        topic_stats=plan.topic_stats,
        topic_order=topic_order,
    )
    files[plan.consolidated_path] = _render_consolidated(
        language=plan.language_display,
        slug=plan.language_slug,
        source=plan.source,
        source_slug=plan.source_slug,
        source_url=plan.source_url,
        mode=plan.mode,
        total_documents=plan.total_documents,
        topics=topic_order,
        topic_docs=topic_docs,
    )
    meta = _render_meta(plan, chunk_count=0)
    return RenderedCompilation(
        files=files,
        meta_path=plan.language_dir / "_meta.json",
        meta=meta,
        output_path=plan.consolidated_path,
        topic_stats=plan.topic_stats,
        total_documents=plan.total_documents,
    )


def write_rendered_compilation(rendered: RenderedCompilation, *, durability: DurabilityMode = "balanced") -> None:
    for path, content in rendered.files.items():
        write_text(path, content, durability=durability)
    write_json(rendered.meta_path, rendered.meta)


def write_streamed_compilation(
    plan: CompilationPlan, *, durability: DurabilityMode = "balanced"
) -> AssetInventorySummary | None:
    target_map = _build_link_target_map(plan)
    asset_records, asset_rewrites = write_assets(plan, durability=durability)
    for topic in plan.topics:
        section_lines = [
            f"# {topic.name}",
            "",
            f"_{len(topic.documents)} document(s) from {plan.source}_",
            "",
            "## Contents",
            "",
        ]
        for planned_doc in topic.documents:
            section_lines.append(f"- [{planned_doc.title}]({planned_doc.slug}.md)")
            if planned_doc.document is not None:
                markdown = _rewrite_document_markdown(
                    planned_doc.document.markdown,
                    current_path=planned_doc.path,
                    language_dir=plan.language_dir,
                    target_map=target_map,
                    asset_rewrites=asset_rewrites,
                )
                rewritten_doc = Document(
                    topic=planned_doc.document.topic,
                    slug=planned_doc.document.slug,
                    title=planned_doc.document.title,
                    markdown=markdown,
                    source_url=planned_doc.document.source_url,
                    order_hint=planned_doc.document.order_hint,
                )
                write_text(
                    planned_doc.path,
                    render_document(
                        rewritten_doc,
                        topic=topic.name,
                        language=plan.language_display,
                        language_slug=plan.language_slug,
                        source=plan.source,
                        source_slug=plan.source_slug,
                        mode=plan.mode,
                        emit_frontmatter=plan.emit_document_frontmatter,
                    ),
                    durability=durability,
                )
                if planned_doc.fragment_path is not None:
                    write_text(
                        planned_doc.fragment_path,
                        render_consolidated_document_fragment(rewritten_doc),
                        durability=durability,
                    )
        section_lines.append("")
        write_text(topic.directory / "_section.md", "\n".join(section_lines) + "\n", durability=durability)

    topic_order = [topic.name for topic in plan.topics]
    write_text(
        plan.language_dir / "index.md",
        _render_index(
            language=plan.language_display,
            slug=plan.language_slug,
            source=plan.source,
            source_slug=plan.source_slug,
            source_url=plan.source_url,
            mode=plan.mode,
            topic_stats=plan.topic_stats,
            topic_order=topic_order,
        ),
        durability=durability,
    )
    write_text_parts(plan.consolidated_path, iter_consolidated_parts(plan), durability=durability)
    chunk_count = write_chunks(plan, durability=durability) if plan.emit_chunks else 0
    write_json(
        plan.language_dir / "_meta.json",
        _render_meta(plan, chunk_count=chunk_count, asset_inventory=_asset_summary(asset_records)),
    )
    shutil.rmtree(plan.language_dir / "_fragments", ignore_errors=True)
    return _asset_summary(asset_records)


def iter_consolidated_parts(plan: CompilationPlan) -> Iterable[str]:
    topic_order = [topic.name for topic in plan.topics]
    anchors = _consolidated_anchors(plan)
    yield _render_consolidated_header(
        language=plan.language_display,
        source=plan.source,
        source_slug=plan.source_slug,
        source_url=plan.source_url,
        mode=plan.mode,
        total_documents=plan.total_documents,
        topics=topic_order,
        topic_docs={
            topic.name: [
                Document(
                    topic=topic.name,
                    slug=planned_doc.slug,
                    title=planned_doc.title,
                    markdown="",
                    source_url=planned_doc.source_url,
                    order_hint=planned_doc.order_hint,
                )
                for planned_doc in topic.documents
            ]
            for topic in plan.topics
        },
        anchors=anchors,
    )
    for topic in plan.topics:
        yield f'<a id="{anchors.topic_anchors[topic.name]}"></a>\n\n'
        yield f"### {topic.name}\n\n"
        for planned_doc in topic.documents:
            yield f'<a id="{anchors.document_anchors[(topic.name, planned_doc.order_hint, planned_doc.slug)]}"></a>\n\n'
            yield _artifact_fragment_text(planned_doc)


def _render_meta(
    plan: CompilationPlan,
    *,
    chunk_count: int = 0,
    asset_inventory: AssetInventorySummary | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "language": plan.language_display,
        "slug": plan.language_slug,
        "source": plan.source,
        "source_slug": plan.source_slug,
        "source_url": plan.source_url,
        "mode": plan.mode,
        "total_documents": plan.total_documents,
        "topics": [{"topic": s.topic, "document_count": s.document_count} for s in plan.topic_stats],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    outputs: dict[str, Any] = {}
    if plan.emit_document_frontmatter:
        outputs["document_frontmatter"] = True
    if plan.emit_chunks:
        outputs["chunks"] = {
            "enabled": True,
            "manifest_path": "chunks/manifest.jsonl",
            "chunk_count": chunk_count,
            "max_chars": plan.chunk_max_chars,
            "overlap_chars": plan.chunk_overlap_chars,
            "strategy": plan.chunk_strategy,
        }
        if plan.chunk_strategy == "tokens":
            outputs["chunks"]["max_tokens"] = plan.chunk_max_tokens
            outputs["chunks"]["overlap_tokens"] = plan.chunk_overlap_tokens
    if asset_inventory is not None:
        outputs["assets"] = asset_inventory.model_dump(mode="json")
    if outputs:
        meta["outputs"] = outputs
    return meta


async def compile_from_stream(
    *,
    language_display: str,
    language_slug: str,
    source: str,
    source_slug: str,
    source_url: str,
    mode: str,
    output_root: Path,
    documents: AsyncIterator[Document],
    on_document=None,
    resume_artifacts: list[DocumentArtifactCheckpoint] | None = None,
    durability: DurabilityMode = "balanced",
    emit_document_frontmatter: bool = False,
    emit_chunks: bool = False,
    chunk_max_chars: int = 8_000,
    chunk_overlap_chars: int = 400,
    chunk_strategy: str = "chars",
    chunk_max_tokens: int = 1_000,
    chunk_overlap_tokens: int = 100,
    assets: list[AssetEvent] | None = None,
) -> CompiledOutput:
    builder = LanguageOutputBuilder(
        language_display=language_display,
        language_slug=language_slug,
        source=source,
        source_slug=source_slug,
        source_url=source_url,
        mode=mode,
        output_root=output_root,
        durability=durability,
        emit_document_frontmatter=emit_document_frontmatter,
        emit_chunks=emit_chunks,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
        chunk_strategy=chunk_strategy,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        assets=assets,
    )
    for checkpoint_artifact in resume_artifacts or []:
        builder.preload_artifact(checkpoint_artifact)
    async for document in documents:
        artifact = builder.add(document)
        if on_document is not None:
            await on_document(document, artifact)
    if assets is not None:
        builder.assets = list(assets)
    return builder.finalize()


def artifact_checkpoint(document: CompilationDocument, *, topic: str) -> DocumentArtifactCheckpoint:
    if document.fragment_path is None:
        raise RuntimeError("Cannot checkpoint a document without a consolidated fragment path")
    return DocumentArtifactCheckpoint(
        topic=topic,
        slug=document.slug,
        title=document.title,
        source_url=document.source_url,
        order_hint=document.order_hint,
        path=str(document.path),
        fragment_path=str(document.fragment_path),
    )


def _unique_slug(base: str, used: set[str]) -> str:
    base = base or "doc"
    if base not in used:
        return base
    i = 2
    while f"{base}-{i}" in used:
        i += 1
    return f"{base}-{i}"


def render_document(
    doc: Document,
    *,
    topic: str,
    language: str,
    language_slug: str = "",
    source: str = "",
    source_slug: str = "",
    mode: str = "",
    emit_frontmatter: bool = False,
) -> str:
    header = [
        f"# {doc.title}",
        "",
        f"_Language: {language} · Topic: {topic}_",
    ]
    if doc.source_url:
        header.append(f"_Source: <{doc.source_url}>_")
    header.append("")
    body = _normalize_markdown(doc.markdown)
    rendered = "\n".join(header) + "\n" + body.rstrip() + "\n"
    if not emit_frontmatter:
        return rendered
    return (
        _frontmatter(
            {
                "language": language,
                "language_slug": language_slug,
                "source": source,
                "source_slug": source_slug,
                "source_url": doc.source_url,
                "topic": topic,
                "slug": doc.slug,
                "title": doc.title,
                "order_hint": doc.order_hint,
                "mode": mode,
                "generated_at": datetime.now(UTC).isoformat(),
            }
        )
        + rendered
    )


def render_consolidated_document_fragment(doc: Document) -> str:
    lines = [
        f"#### {doc.title}",
        "",
    ]
    if doc.source_url:
        lines.append(f"_Source: <{doc.source_url}>_")
        lines.append("")
    lines.append(_normalize_markdown(doc.markdown).rstrip())
    lines.append("")
    return "\n".join(lines) + "\n"


def _artifact_fragment_text(document: CompilationDocument) -> str:
    if document.fragment_path is not None and document.fragment_path.exists():
        return document.fragment_path.read_text(encoding="utf-8")
    if document.path.exists():
        return _rebuild_fragment_from_document_file(document)
    return ""


def _rebuild_fragment_from_document_file(document: CompilationDocument) -> str:
    text = document.path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            text = parts[1].lstrip()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and lines[0].startswith("_") and lines[0].endswith("_"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    body = "\n".join(lines).strip()
    rebuilt = Document(
        topic="",
        slug=document.slug,
        title=document.title,
        markdown=body,
        source_url=document.source_url,
        order_hint=document.order_hint,
    )
    return render_consolidated_document_fragment(rebuilt)


def _render_index(
    *,
    language: str,
    slug: str,
    source: str,
    source_slug: str,
    source_url: str,
    mode: str,
    topic_stats: list[TopicStats],
    topic_order: list[str],
) -> str:
    lines = [
        f"# {language} Documentation — Index",
        "",
        "## Metadata",
        "",
        f"- Source: {source}",
        f"- Source slug: `{source_slug}`",
        f"- Source URL: {source_url or 'N/A'}",
        f"- Mode: {mode}",
        f"- Generated: {datetime.now(UTC).isoformat()}",
        f"- Total documents: {sum(s.document_count for s in topic_stats)}",
        "",
        "## Consolidated file",
        "",
        f"- [{slug}.md]({slug}.md)",
        "",
        "## Topics",
        "",
    ]
    for stats in topic_stats:
        topic_slug = slugify(stats.topic)
        lines.append(f"- [{stats.topic}]({topic_slug}/_section.md) — {stats.document_count} document(s)")
    lines.append("")
    return "\n".join(lines)


def _render_consolidated(
    *,
    language: str,
    slug: str,
    source: str,
    source_slug: str,
    source_url: str,
    mode: str,
    total_documents: int,
    topics: list[str],
    topic_docs: dict[str, list[Document]],
) -> str:
    fake_plan = CompilationPlan(
        language_display=language,
        language_slug=slug,
        source=source,
        source_slug=source_slug,
        source_url=source_url,
        mode=mode,
        language_dir=Path("."),
        consolidated_path=Path(f"{slug}.md"),
        topics=[
            CompilationTopic(
                name=topic,
                slug=slugify(topic),
                directory=Path(slugify(topic)),
                documents=[
                    CompilationDocument(
                        title=doc.title,
                        slug=doc.slug,
                        source_url=doc.source_url,
                        order_hint=doc.order_hint,
                        path=Path(f"{doc.slug}.md"),
                        document=doc,
                    )
                    for doc in topic_docs[topic]
                ],
            )
            for topic in topics
        ],
        topic_stats=[TopicStats(topic=topic, document_count=len(topic_docs[topic])) for topic in topics],
        total_documents=total_documents,
    )
    anchors = _consolidated_anchors(fake_plan)
    lines = [
        _render_consolidated_header(
            language=language,
            source=source,
            source_slug=source_slug,
            source_url=source_url,
            mode=mode,
            total_documents=total_documents,
            topics=topics,
            topic_docs=topic_docs,
            anchors=anchors,
        )
    ]

    for topic in topics:
        lines.append(f'<a id="{anchors.topic_anchors[topic]}"></a>')
        lines.append("")
        lines.append(f"### {topic}")
        lines.append("")
        for doc in topic_docs[topic]:
            lines.append(f'<a id="{anchors.document_anchors[(topic, doc.order_hint, doc.slug)]}"></a>')
            lines.append("")
            lines.append(render_consolidated_document_fragment(doc).rstrip())
            lines.append("")

    return "\n".join(lines) + "\n"


def _render_consolidated_header(
    *,
    language: str,
    source: str,
    source_slug: str,
    source_url: str,
    mode: str,
    total_documents: int,
    topics: list[str],
    topic_docs: dict[str, list[Document]],
    anchors: ConsolidatedAnchors | None = None,
) -> str:
    if anchors is None:
        registry = AnchorRegistry()
        topic_anchors = {topic: registry.register(topic) for topic in topics}
        document_anchors = {
            (topic, doc.order_hint, doc.slug): registry.register(doc.title)
            for topic in topics
            for doc in topic_docs[topic]
        }
        anchors = ConsolidatedAnchors(topic_anchors=topic_anchors, document_anchors=document_anchors)
    lines = [
        f"# {language} Documentation",
        "",
        "## Metadata",
        "",
        f"- Source: {source}",
        f"- Source slug: `{source_slug}`",
        f"- Source URL: {source_url or 'N/A'}",
        f"- Mode: {mode}",
        f"- Generated: {datetime.now(UTC).isoformat()}",
        f"- Total documents: {total_documents}",
        "",
        "## Table of Contents",
        "",
    ]
    for topic in topics:
        lines.append(f"- [{topic}](#{anchors.topic_anchors[topic]})")
        for doc in topic_docs[topic]:
            lines.append(f"  - [{doc.title}](#{anchors.document_anchors[(topic, doc.order_hint, doc.slug)]})")
    lines.append("")
    lines.append("## Documentation")
    lines.append("")

    return "\n".join(lines) + "\n"


_HEADING_RE = re.compile(r"^(#{1,6})\s")


def _normalize_markdown(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    # Push all headings down to ensure they fit under ####+ in consolidated file.
    lines = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            new_level = min(6, level + 2)
            lines.append("#" * new_level + line[level:])
        else:
            lines.append(line)
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return collapsed.strip()


@dataclass(slots=True)
class ConsolidatedAnchors:
    topic_anchors: dict[str, str]
    document_anchors: dict[tuple[str, int, str], str]


class AnchorRegistry:
    def __init__(self) -> None:
        self._used: dict[str, int] = {}

    def register(self, text: str) -> str:
        base = _anchor(text) or "section"
        count = self._used.get(base, 0) + 1
        self._used[base] = count
        if count == 1:
            return base
        return f"{base}-{count}"


def _consolidated_anchors(plan: CompilationPlan) -> ConsolidatedAnchors:
    registry = AnchorRegistry()
    topic_anchors: dict[str, str] = {}
    document_anchors: dict[tuple[str, int, str], str] = {}
    for topic in plan.topics:
        topic_anchors[topic.name] = registry.register(topic.name)
        for doc in topic.documents:
            document_anchors[(topic.name, doc.order_hint, doc.slug)] = registry.register(doc.title)
    return ConsolidatedAnchors(topic_anchors=topic_anchors, document_anchors=document_anchors)


def _frontmatter(data: dict[str, Any]) -> str:
    payload = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{payload}\n---\n\n"


def _build_link_target_map(plan: CompilationPlan) -> dict[str, Path]:
    targets: dict[str, Path] = {}
    for topic in plan.topics:
        for doc in topic.documents:
            keys = {doc.slug, f"{topic.slug}/{doc.slug}.md", f"{doc.slug}.md"}
            if doc.source_url:
                keys.add(doc.source_url)
                keys.add(urldefrag(doc.source_url).url)
                parsed = urlparse(doc.source_url)
                if parsed.path:
                    keys.add(parsed.path.lstrip("/"))
                    keys.add(urldefrag(parsed.path.lstrip("/")).url)
            for key in keys:
                if key:
                    targets[_normalize_link_key(key)] = doc.path
    return targets


_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _rewrite_document_markdown(
    markdown: str,
    *,
    current_path: Path,
    language_dir: Path,
    target_map: dict[str, Path],
    asset_rewrites: dict[str, Path],
) -> str:
    lines: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue
        lines.append(
            _MARKDOWN_LINK_RE.sub(
                lambda match: _rewrite_link_match(
                    match,
                    current_path=current_path,
                    language_dir=language_dir,
                    target_map=target_map,
                    asset_rewrites=asset_rewrites,
                ),
                line,
            )
        )
    return "\n".join(lines)


def _rewrite_link_match(
    match: re.Match[str],
    *,
    current_path: Path,
    language_dir: Path,
    target_map: dict[str, Path],
    asset_rewrites: dict[str, Path],
) -> str:
    prefix, label, target = match.group(1), match.group(2), match.group(3)
    fragment = ""
    base_target = target
    if "#" in target:
        base_target, fragment = target.split("#", 1)
        fragment = f"#{fragment}"
    normalized = _normalize_link_key(target)
    base_normalized = _normalize_link_key(base_target)
    if (
        _is_external_or_special(target)
        and normalized not in target_map
        and base_normalized not in target_map
        and normalized not in asset_rewrites
        and base_normalized not in asset_rewrites
    ):
        return match.group(0)
    replacement_path = asset_rewrites.get(normalized) or asset_rewrites.get(base_normalized)
    if replacement_path is None:
        replacement_path = target_map.get(normalized) or target_map.get(base_normalized)
    if replacement_path is None:
        return match.group(0)
    relative = _relative_link(current_path, replacement_path)
    return f"{prefix}[{label}]({relative}{fragment})"


def _normalize_link_key(target: str) -> str:
    target = target.strip().strip("<>")
    if target.startswith("#"):
        return target
    target = urldefrag(target).url
    parsed = urlparse(target)
    if parsed.scheme and parsed.netloc:
        normalized_path = parsed.path.rstrip("/")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{normalized_path}"
    return target.lstrip("./").rstrip("/")


def _is_external_or_special(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https", "mailto", "tel", "data"}


def _relative_link(current_path: Path, target_path: Path) -> str:
    return Path(os.path.relpath(target_path, start=current_path.parent)).as_posix()


def write_assets(
    plan: CompilationPlan,
    *,
    durability: DurabilityMode = "balanced",
) -> tuple[list[AssetRecord], dict[str, Path]]:
    records: list[AssetRecord] = []
    rewrites: dict[str, Path] = {}
    if not plan.assets:
        return records, rewrites
    assets_dir = plan.language_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    by_checksum: dict[str, Path] = {}
    for event in plan.assets:
        payload = _asset_payload(event)
        if payload is None:
            records.append(
                AssetRecord(
                    source_url=event.source_url,
                    media_type=event.media_type,
                    original_path=event.path or event.local_path,
                    status="referenced",
                    reason="no local payload",
                )
            )
            continue
        checksum = hashlib.sha256(payload).hexdigest()
        output_path = by_checksum.get(checksum)
        if output_path is None:
            output_path = (
                assets_dir / f"{checksum[:16]}-{slugify(Path(event.path or event.local_path).name) or 'asset'}"
            )
            write_bytes(output_path, payload, durability=durability)
            by_checksum[checksum] = output_path
        record = AssetRecord(
            source_url=event.source_url,
            media_type=event.media_type,
            original_path=event.path or event.local_path,
            output_path=output_path.relative_to(plan.language_dir).as_posix(),
            checksum=checksum,
            byte_count=len(payload),
            status="copied",
        )
        records.append(record)
        for key in {event.path, event.source_url, event.local_path}:
            if key:
                rewrites[_normalize_link_key(key)] = output_path
    write_json(
        assets_dir / "manifest.json",
        {"assets": [record.model_dump(mode="json") for record in records]},
        durability=durability,
    )
    return records, rewrites


def _asset_payload(event: AssetEvent) -> bytes | None:
    if event.content is not None:
        return event.content
    local = Path(event.local_path)
    if not event.local_path or not local.exists() or not local.is_file():
        return None
    try:
        resolved = local.resolve()
        if ".." in local.parts:
            return None
        return resolved.read_bytes()
    except OSError:
        return None


def _asset_summary(records: list[AssetRecord]) -> AssetInventorySummary | None:
    if not records:
        return None
    return AssetInventorySummary(
        total=len(records),
        copied=sum(1 for record in records if record.status == "copied"),
        referenced=sum(1 for record in records if record.status == "referenced"),
        skipped=sum(1 for record in records if record.status == "skipped"),
        manifest_path="assets/manifest.json",
    )


def write_chunks(plan: CompilationPlan, *, durability: DurabilityMode = "balanced") -> int:
    chunks_dir = plan.language_dir / "chunks"
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    records: list[str] = []
    chunk_count = 0
    token_kwargs = {
        "max_tokens": max(1, plan.chunk_max_tokens),
        "overlap_tokens": max(0, plan.chunk_overlap_tokens),
    }
    max_chars = max(500, plan.chunk_max_chars)
    char_kwargs = {"max_chars": max_chars, "overlap": min(max(0, plan.chunk_overlap_chars), max_chars // 2)}
    for topic in plan.topics:
        for doc in topic.documents:
            text = doc.path.read_text(encoding="utf-8")
            chunk_iterable = (
                _token_chunks(text, **token_kwargs)
                if plan.chunk_strategy == "tokens"
                else _char_chunks(text, **char_kwargs)
            )
            for chunk in chunk_iterable:
                index, start, end, chunk_text, token_start, token_end = chunk
                chunk_id = f"{plan.language_slug}:{topic.slug}:{doc.slug}:{index:04d}"
                filename = f"{topic.slug}-{doc.slug}-{index:04d}.md"
                chunk_path = chunks_dir / filename
                write_text(chunk_path, chunk_text.rstrip() + "\n", durability=durability)
                record = {
                    "chunk_id": chunk_id,
                    "language": plan.language_display,
                    "source": plan.source,
                    "source_slug": plan.source_slug,
                    "topic": topic.name,
                    "document_slug": doc.slug,
                    "document_title": doc.title,
                    "source_url": doc.source_url,
                    "order_hint": doc.order_hint,
                    "chunk_index": index,
                    "text_path": f"chunks/{filename}",
                    "char_start": start,
                    "char_end": end,
                    "chunk_strategy": plan.chunk_strategy,
                }
                if plan.chunk_strategy == "tokens":
                    record.update(
                        {
                            "token_start": token_start,
                            "token_end": token_end,
                            "token_count": token_end - token_start,
                        }
                    )
                records.append(json.dumps(record, ensure_ascii=False))
                chunk_count += 1
    write_text(chunks_dir / "manifest.jsonl", "\n".join(records) + ("\n" if records else ""), durability=durability)
    return chunk_count


def _char_chunks(text: str, *, max_chars: int, overlap: int) -> Iterable[tuple[int, int, int, str, int, int]]:
    if not text:
        return
    start = 0
    index = 0
    length = len(text)
    while start < length:
        hard_end = min(length, start + max_chars)
        end = hard_end
        if hard_end < length:
            boundary = max(text.rfind("\n\n", start, hard_end), text.rfind("\n", start, hard_end))
            if boundary > start + max_chars // 2:
                end = boundary
        yield index, start, end, text[start:end], 0, 0
        if end >= length:
            break
        start = max(end - overlap, start + 1)
        index += 1


def _token_chunks(text: str, *, max_tokens: int, overlap_tokens: int) -> Iterable[tuple[int, int, int, str, int, int]]:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Tokenizer chunking requires: python -m pip install -e .[tokenizer]") from exc
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if not tokens:
        return
    overlap = min(overlap_tokens, max_tokens // 2)
    index = 0
    token_start = 0
    char_start = 0
    while token_start < len(tokens):
        token_end = min(len(tokens), token_start + max_tokens)
        chunk_text = encoding.decode(tokens[token_start:token_end])
        char_end = char_start + len(chunk_text)
        yield index, char_start, char_end, chunk_text, token_start, token_end
        if token_end >= len(tokens):
            break
        token_start = max(token_end - overlap, token_start + 1)
        char_start = max(0, len(encoding.decode(tokens[:token_start])))
        index += 1


def _anchor(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)
