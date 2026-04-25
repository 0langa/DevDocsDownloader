from __future__ import annotations

import json
import re
import shutil
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .models import DocumentArtifactCheckpoint, TopicStats
from .sources.base import Document
from .utils.filesystem import DurabilityMode, write_json, write_text, write_text_parts
from .utils.text import slugify


class CompiledOutput:
    def __init__(self, *, total_documents: int, topics: list[TopicStats], output_path: Path) -> None:
        self.total_documents = total_documents
        self.topics = topics
        self.output_path = output_path


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


@dataclass(slots=True)
class RenderedCompilation:
    files: dict[Path, str]
    meta_path: Path
    meta: dict[str, Any]
    output_path: Path
    topic_stats: list[TopicStats]
    total_documents: int


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
        self._topic_docs[topic].append(
            CompilationDocument(
                title=artifact.title,
                slug=artifact.slug,
                source_url=artifact.source_url,
                order_hint=artifact.order_hint,
                path=Path(artifact.path),
                fragment_path=Path(artifact.fragment_path),
                document=None,
            )
        )
        self.total_documents += 1

    def finalize(self) -> CompiledOutput:
        plan = self.build_plan()
        write_streamed_compilation(plan, durability=self.durability)
        return CompiledOutput(
            total_documents=plan.total_documents,
            topics=plan.topic_stats,
            output_path=plan.consolidated_path,
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
                markdown=item.fragment_path.read_text(encoding="utf-8") if item.fragment_path is not None else "",
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


def write_streamed_compilation(plan: CompilationPlan, *, durability: DurabilityMode = "balanced") -> None:
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
    write_json(plan.language_dir / "_meta.json", _render_meta(plan, chunk_count=chunk_count))
    shutil.rmtree(plan.language_dir / "_fragments", ignore_errors=True)


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
            if planned_doc.fragment_path is not None:
                yield planned_doc.fragment_path.read_text(encoding="utf-8")


def _render_meta(plan: CompilationPlan, *, chunk_count: int = 0) -> dict[str, Any]:
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
        }
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
    )
    for checkpoint_artifact in resume_artifacts or []:
        builder.preload_artifact(checkpoint_artifact)
    async for document in documents:
        artifact = builder.add(document)
        if on_document is not None:
            await on_document(document, artifact)
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


def write_chunks(plan: CompilationPlan, *, durability: DurabilityMode = "balanced") -> int:
    chunks_dir = plan.language_dir / "chunks"
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    records: list[str] = []
    chunk_count = 0
    max_chars = max(500, plan.chunk_max_chars)
    overlap = min(max(0, plan.chunk_overlap_chars), max_chars // 2)
    for topic in plan.topics:
        for doc in topic.documents:
            text = doc.path.read_text(encoding="utf-8")
            for index, start, end, chunk_text in _chunk_text(text, max_chars=max_chars, overlap=overlap):
                chunk_id = f"{plan.language_slug}:{topic.slug}:{doc.slug}:{index:04d}"
                filename = f"{topic.slug}-{doc.slug}-{index:04d}.md"
                chunk_path = chunks_dir / filename
                write_text(chunk_path, chunk_text.rstrip() + "\n", durability=durability)
                records.append(
                    json.dumps(
                        {
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
                        },
                        ensure_ascii=False,
                    )
                )
                chunk_count += 1
    write_text(chunks_dir / "manifest.jsonl", "\n".join(records) + ("\n" if records else ""), durability=durability)
    return chunk_count


def _chunk_text(text: str, *, max_chars: int, overlap: int) -> Iterable[tuple[int, int, int, str]]:
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
        yield index, start, end, text[start:end]
        if end >= length:
            break
        start = max(end - overlap, start + 1)
        index += 1


def _anchor(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)
