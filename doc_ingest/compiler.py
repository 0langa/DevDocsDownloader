from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from .models import TopicStats
from .sources.base import Document
from .utils.filesystem import write_json, write_text
from .utils.text import slugify


class CompiledOutput:
    def __init__(self, *, total_documents: int, topics: list[TopicStats], output_path: Path) -> None:
        self.total_documents = total_documents
        self.topics = topics
        self.output_path = output_path


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
        topic_stats: list[TopicStats] = []

        for topic in self._topic_order:
            topic_slug = slugify(topic)
            topic_dir = self.language_dir / topic_slug
            topic_dir.mkdir(parents=True, exist_ok=True)

            documents = self._topic_docs[topic]
            section_lines = [
                f"# {topic}",
                "",
                f"_{len(documents)} document(s) from {self.source}_",
                "",
                "## Contents",
                "",
            ]

            for doc in documents:
                per_doc_path = topic_dir / f"{doc.slug}.md"
                write_text(per_doc_path, _render_document(doc, topic=topic, language=self.language_display))
                section_lines.append(f"- [{doc.title}]({doc.slug}.md)")

            section_lines.append("")
            write_text(topic_dir / "_section.md", "\n".join(section_lines) + "\n")
            topic_stats.append(TopicStats(topic=topic, document_count=len(documents)))

        index_md = _render_index(
            language=self.language_display,
            slug=self.language_slug,
            source=self.source,
            source_slug=self.source_slug,
            source_url=self.source_url,
            mode=self.mode,
            topic_stats=topic_stats,
            topic_order=self._topic_order,
        )
        write_text(self.language_dir / "index.md", index_md)

        consolidated_md = _render_consolidated(
            language=self.language_display,
            slug=self.language_slug,
            source=self.source,
            source_slug=self.source_slug,
            source_url=self.source_url,
            mode=self.mode,
            total_documents=self.total_documents,
            topics=self._topic_order,
            topic_docs=self._topic_docs,
        )
        consolidated_path = self.language_dir / f"{self.language_slug}.md"
        write_text(consolidated_path, consolidated_md)

        meta = {
            "language": self.language_display,
            "slug": self.language_slug,
            "source": self.source,
            "source_slug": self.source_slug,
            "source_url": self.source_url,
            "mode": self.mode,
            "total_documents": self.total_documents,
            "topics": [{"topic": s.topic, "document_count": s.document_count} for s in topic_stats],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(self.language_dir / "_meta.json", meta)

        return CompiledOutput(
            total_documents=self.total_documents,
            topics=topic_stats,
            output_path=consolidated_path,
        )


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
    *, language: str, slug: str, source: str, source_slug: str, source_url: str,
    mode: str, topic_stats: list[TopicStats], topic_order: list[str],
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
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Total documents: {sum(s.document_count for s in topic_stats)}",
        "",
        f"## Consolidated file",
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
    *, language: str, slug: str, source: str, source_slug: str, source_url: str,
    mode: str, total_documents: int, topics: list[str],
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
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
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
