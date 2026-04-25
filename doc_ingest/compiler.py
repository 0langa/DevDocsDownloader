from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import TopicStats
from .sources.base import Document
from .utils.filesystem import write_json, write_text
from .utils.text import slugify


class CompiledOutput:
    def __init__(self, *, total_documents: int, topics: list[TopicStats], output_path: Path) -> None:
        self.total_documents = total_documents
        self.topics = topics
        self.output_path = output_path


@dataclass(slots=True)
class CompilationDocument:
    document: Document
    path: Path


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
    ) -> None:
        self.language_display = language_display
        self.language_slug = language_slug
        self.source = source
        self.source_slug = source_slug
        self.source_url = source_url
        self.mode = mode
        self.language_dir = output_root / language_slug
        self.language_dir.mkdir(parents=True, exist_ok=True)

        self._topic_docs: dict[str, list[Document]] = {}
        self._topic_order: list[str] = []
        self._used_slugs: dict[str, set[str]] = {}
        self.total_documents = 0

    def add(self, document: Document) -> None:
        topic = document.topic.strip() or "Reference"
        if topic not in self._topic_docs:
            self._topic_docs[topic] = []
            self._topic_order.append(topic)
            self._used_slugs[topic] = set()

        slug_base = slugify(document.slug or document.title)
        slug = _unique_slug(slug_base, self._used_slugs[topic])
        self._used_slugs[topic].add(slug)
        document.slug = slug

        self._topic_docs[topic].append(document)
        self.total_documents += 1

    def finalize(self) -> CompiledOutput:
        plan = self.build_plan()
        rendered = render_compilation(plan)
        write_rendered_compilation(rendered)
        return CompiledOutput(
            total_documents=rendered.total_documents,
            topics=rendered.topic_stats,
            output_path=rendered.output_path,
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
                planned_topic.documents.append(CompilationDocument(document=doc, path=topic_dir / f"{doc.slug}.md"))
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
        )


def render_compilation(plan: CompilationPlan) -> RenderedCompilation:
    files: dict[Path, str] = {}
    topic_docs = {topic.name: [item.document for item in topic.documents] for topic in plan.topics}
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
            files[planned_doc.path] = _render_document(doc, topic=topic.name, language=plan.language_display)
            section_lines.append(f"- [{doc.title}]({doc.slug}.md)")
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
    meta = _render_meta(plan)
    return RenderedCompilation(
        files=files,
        meta_path=plan.language_dir / "_meta.json",
        meta=meta,
        output_path=plan.consolidated_path,
        topic_stats=plan.topic_stats,
        total_documents=plan.total_documents,
    )


def write_rendered_compilation(rendered: RenderedCompilation) -> None:
    for path, content in rendered.files.items():
        write_text(path, content)
    write_json(rendered.meta_path, rendered.meta)


def _render_meta(plan: CompilationPlan) -> dict[str, Any]:
    return {
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
) -> CompiledOutput:
    builder = LanguageOutputBuilder(
        language_display=language_display,
        language_slug=language_slug,
        source=source,
        source_slug=source_slug,
        source_url=source_url,
        mode=mode,
        output_root=output_root,
    )
    async for document in documents:
        builder.add(document)
        if on_document is not None:
            await on_document(document)
    return builder.finalize()


def _unique_slug(base: str, used: set[str]) -> str:
    base = base or "doc"
    if base not in used:
        return base
    i = 2
    while f"{base}-{i}" in used:
        i += 1
    return f"{base}-{i}"


def _render_document(doc: Document, *, topic: str, language: str) -> str:
    header = [
        f"# {doc.title}",
        "",
        f"_Language: {language} · Topic: {topic}_",
    ]
    if doc.source_url:
        header.append(f"_Source: <{doc.source_url}>_")
    header.append("")
    body = _normalize_markdown(doc.markdown)
    return "\n".join(header) + "\n" + body.rstrip() + "\n"


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
        anchor = _anchor(topic)
        lines.append(f"- [{topic}](#{anchor})")
        for doc in topic_docs[topic]:
            lines.append(f"  - [{doc.title}](#{_anchor(topic + '-' + doc.title)})")
    lines.append("")
    lines.append("## Documentation")
    lines.append("")

    for topic in topics:
        lines.append(f"### {topic}")
        lines.append("")
        for doc in topic_docs[topic]:
            lines.append(f"#### {doc.title}")
            lines.append("")
            if doc.source_url:
                lines.append(f"_Source: <{doc.source_url}>_")
                lines.append("")
            lines.append(_normalize_markdown(doc.markdown).rstrip())
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


def _anchor(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)
