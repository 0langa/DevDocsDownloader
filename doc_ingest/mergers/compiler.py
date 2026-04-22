from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from collections.abc import Iterable
from pathlib import Path

from ..adapters import SiteAdapter
from ..models import CrawlState, ExtractedDocument, LanguageEntry
from ..normalizers.markdown import normalize_compiled_markdown
from ..utils.text import slugify


@dataclass(slots=True)
class ReconstructedSubsection:
    title: str
    blocks: list[str] = field(default_factory=list)
    block_signatures: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ReconstructedSection:
    title: str
    subsections: dict[str, ReconstructedSubsection] = field(default_factory=dict)
    block_signatures: list[str] = field(default_factory=list)


def build_toc(sections: list[tuple[str, str]], *, heading: str = "## Table of Contents") -> str:
    lines = [heading, ""]
    for title, anchor in sections:
        indent = "  " if " / " in title else ""
        label = title.split(" / ", 1)[-1] if indent else title
        lines.append(f"{indent}- [{label}](#{anchor})")
    return "\n".join(lines)


def _anchorize(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)


def _order_documents(documents: list[ExtractedDocument], state: CrawlState | None, adapter: SiteAdapter | None) -> list[ExtractedDocument]:
    state_pages = state.pages if state is not None else {}

    def sort_key(document: ExtractedDocument) -> tuple:
        page = state_pages.get(document.url) or state_pages.get(document.final_url)
        depth = page.depth if page is not None else 99
        parent = page.parent_url if page is not None else ""
        breadcrumbs = document.breadcrumbs or (page.metadata.get("breadcrumbs", []) if page is not None else [])
        order_hint = adapter.order_hint(document.final_url, document.title, breadcrumbs) if adapter is not None else (document.source_order_hint or "")
        return (
            depth,
            adapter.page_priority(document.final_url, document.title, breadcrumbs) if adapter is not None else 999,
            "/".join(breadcrumbs).lower(),
            parent or "",
            order_hint,
            document.title.lower(),
            document.final_url,
        )

    return sorted(documents, key=sort_key)


def compile_language_markdown(
    language: LanguageEntry,
    documents: list[ExtractedDocument],
    output_path: Path,
    *,
    state: CrawlState | None = None,
    coverage_notes: list[str] | None = None,
    adapter: SiteAdapter | None = None,
) -> Path:
    ordered = _order_documents(documents, state, adapter)
    sections = _reconstruct_sections(ordered, adapter)
    final_markdown = _enforce_output_schema(language, sections, state=state, coverage_notes=coverage_notes or [], adapter=adapter)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_markdown, encoding="utf-8")
    return output_path


def compile_language_markdown_streaming(
    language: LanguageEntry,
    documents: Iterable[ExtractedDocument],
    output_path: Path,
    *,
    state: CrawlState | None = None,
    coverage_notes: list[str] | None = None,
    adapter: SiteAdapter | None = None,
) -> Path:
    sections = _reconstruct_sections(documents, adapter)
    final_markdown = _enforce_output_schema(language, sections, state=state, coverage_notes=coverage_notes or [], adapter=adapter)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_markdown, encoding="utf-8")
    return output_path


def _reconstruct_sections(documents: Iterable[ExtractedDocument], adapter: SiteAdapter | None) -> list[ReconstructedSection]:
    section_map: dict[str, ReconstructedSection] = {}
    order: list[str] = []
    for document in documents:
        for fragment_title, fragment_body in _split_document_fragments(document):
            section_title, subsection_title = _section_titles(document, fragment_title, adapter)
            if adapter is not None and (adapter.should_ignore_heading(section_title) or adapter.should_ignore_heading(subsection_title)):
                continue
            if section_title not in section_map:
                section_map[section_title] = ReconstructedSection(title=section_title)
                order.append(section_title)
            section = section_map[section_title]
            subsection = section.subsections.setdefault(subsection_title, ReconstructedSubsection(title=subsection_title))
            subsection.sources.add(document.final_url)
            for block in _split_content_blocks(fragment_body):
                signature = _normalized_section_signature(block)
                if not signature or _is_duplicate_block(signature, subsection.block_signatures, adapter) or _is_duplicate_block(signature, section.block_signatures, adapter):
                    continue
                subsection.block_signatures.append(signature)
                section.block_signatures.append(signature)
                subsection.blocks.append(block)
    return [section_map[title] for title in order]


def _section_titles(document: ExtractedDocument, fragment_title: str, adapter: SiteAdapter | None) -> tuple[str, str]:
    if adapter is not None:
        section_title, subsection_title = adapter.section_path(document.final_url, document.title, document.breadcrumbs, fragment_title)
        return adapter.canonical_section_title(section_title), adapter.canonical_section_title(subsection_title)
    if document.breadcrumbs:
        section_title = document.breadcrumbs[0].strip() or "Documentation"
        subsection_title = document.breadcrumbs[1].strip() if len(document.breadcrumbs) > 1 else fragment_title.strip()
        if not subsection_title:
            subsection_title = document.title.strip() or "Overview"
        return section_title, subsection_title
    fallback = document.title.strip() or "Documentation"
    return fallback, fragment_title.strip() or fallback


def _split_document_fragments(document: ExtractedDocument) -> list[tuple[str, str]]:
    body = _clean_page_body(document.markdown, title=document.title.strip() or document.final_url)
    lines = body.splitlines()
    fragments: list[tuple[str, str]] = []
    current_title = document.title.strip() or "Overview"
    buffer: list[str] = []
    for line in lines:
        match = re.match(r"^#{2,6}\s+(.*)$", line.strip())
        if match:
            fragment = "\n".join(buffer).strip()
            if fragment:
                fragments.append((current_title, fragment))
            current_title = match.group(1).strip() or current_title
            buffer = []
            continue
        buffer.append(line)
    fragment = "\n".join(buffer).strip()
    if fragment:
        fragments.append((current_title, fragment))
    if not fragments:
        fallback = body.strip() or document.markdown.strip()
        if fallback:
            fragments.append((document.title.strip() or "Overview", fallback))
    return fragments


def _split_content_blocks(markdown: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", markdown.strip()) if block.strip()]
    merged: list[str] = []
    current_code: list[str] = []
    in_code = False
    for block in blocks:
        if block.startswith("```") or in_code:
            current_code.append(block)
            combined = "\n\n".join(current_code)
            if combined.count("```") % 2 == 0:
                merged.append(combined)
                current_code = []
                in_code = False
            else:
                in_code = True
            continue
        merged.append(block)
    if current_code:
        merged.append("\n\n".join(current_code))
    return merged


def _is_duplicate_block(signature: str, seen_signatures: list[str], adapter: SiteAdapter | None) -> bool:
    if signature in seen_signatures:
        return True
    threshold = adapter.dedupe_similarity_threshold() if adapter is not None else 0.96
    for candidate in seen_signatures:
        if len(signature) < 80 or len(candidate) < 80:
            continue
        if SequenceMatcher(None, signature, candidate).ratio() >= threshold:
            return True
    return False


def _build_toc_entries(sections: list[ReconstructedSection], adapter: SiteAdapter | None) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for section in sections:
        entries.append((section.title, _anchorize(section.title)))
        for subsection in _ordered_subsections(section, adapter):
            entries.append((f"{section.title} / {subsection.title}", _anchorize(f"{section.title}-{subsection.title}")))
    return entries


def _ordered_subsections(section: ReconstructedSection, adapter: SiteAdapter | None) -> list[ReconstructedSubsection]:
    subsections = list(section.subsections.values())
    return sorted(
        subsections,
        key=lambda subsection: adapter.subsection_priority(section.title, subsection.title) if adapter is not None else (999, slugify(subsection.title)),
    )


def _enforce_output_schema(
    language: LanguageEntry,
    sections: list[ReconstructedSection],
    *,
    state: CrawlState | None,
    coverage_notes: list[str],
    adapter: SiteAdapter | None,
) -> str:
    processed_pages = sum(1 for page in (state.pages.values() if state else []) if page.status == "processed") if state else len(sections)
    skipped_pages = sum(1 for page in (state.pages.values() if state else []) if page.status == "skipped") if state else 0
    low_quality_pages = [page for page in (state.pages.values() if state else []) if page.status == "processed" and ((page.extraction_score or 0.0) < 0.35 or page.warning_codes)]
    toc_entries = _build_toc_entries(sections, adapter)
    lines = [
        f"# {language.name} Documentation",
        "",
        "## Metadata",
        "",
        f"- Source: {language.source_url}",
        f"- Crawl Date: {datetime.now(timezone.utc).isoformat()}",
        f"- Pages Processed: {processed_pages}",
        f"- Pages Skipped: {skipped_pages}",
        f"- Adapter Used: {adapter.name if adapter is not None else 'generic'}",
        "",
        build_toc(toc_entries),
        "",
        "## Documentation",
        "",
    ]

    for section in sections:
        non_empty_subsections = [subsection for subsection in _ordered_subsections(section, adapter) if subsection.blocks]
        if not non_empty_subsections:
            continue
        lines.append(f"### {section.title}")
        lines.append("")
        for subsection in non_empty_subsections:
            lines.append(f"#### {subsection.title}")
            lines.append("")
            lines.append("\n\n".join(subsection.blocks))
            lines.append("")
            lines.append(f"_Sources: {', '.join(sorted(subsection.sources))}_")
            lines.append("")

    lines.extend(["## Appendix", "", "### Skipped Pages", ""])
    skipped_pages_list = [page for page in (state.pages.values() if state else []) if page.status == "skipped"]
    if skipped_pages_list:
        lines.extend(f"- {page.normalized_url} ({', '.join(page.warning_codes) or 'no reason recorded'})" for page in skipped_pages_list[:100])
    else:
        lines.append("- None")

    lines.extend(["", "### Low-Quality Pages", ""])
    if low_quality_pages:
        lines.extend(
            f"- {page.normalized_url} (score={page.extraction_score or 0.0:.2f}; warnings={', '.join(page.warning_codes) or 'none'})"
            for page in low_quality_pages[:100]
        )
    else:
        lines.append("- None")

    lines.extend(["", "### Notes", ""])
    if coverage_notes:
        lines.extend(f"- {note}" for note in coverage_notes)
    else:
        lines.append("- None")

    return normalize_compiled_markdown("\n".join(lines) + "\n")


def _clean_page_body(markdown: str, *, title: str) -> str:
    body = markdown.strip()
    lines = body.splitlines()
    if lines and re.match(r"^#{1,3}\s+", lines[0]) and title.lower() in lines[0].lower():
        lines = lines[1:]
    body = "\n".join(lines).strip()
    body = re.sub(r"(?im)^_Source[s]?:\s+[^\n]+_$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _normalized_section_signature(markdown: str) -> str:
    text = re.sub(r"(?m)^_Source[s]?:\s+[^\n]+_$", "", markdown)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:5000]
