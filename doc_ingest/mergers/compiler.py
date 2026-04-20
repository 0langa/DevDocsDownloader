from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..adapters import SiteAdapter
from ..models import CrawlState, ExtractedDocument, LanguageEntry
from ..normalizers.markdown import normalize_compiled_markdown
from ..utils.text import stable_hash


def build_toc(sections: list[tuple[str, str]], *, heading: str = "## Table of Contents") -> str:
    lines = [heading, ""]
    for title, anchor in sections:
        lines.append(f"- [{title}](#{anchor})")
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
    grouped = _group_documents(ordered, adapter)
    toc_entries: list[tuple[str, str]] = []
    section_chunks: list[str] = []
    seen_section_hashes: set[str] = set()

    for group_title, group_documents in grouped:
        group_anchor = _anchorize(group_title)
        toc_entries.append((group_title, group_anchor))
        page_blocks: list[str] = []
        for index, document in enumerate(group_documents, start=1):
            heading = document.title.strip() or document.final_url
            body = _clean_page_body(document.markdown, title=heading)
            section_hash = stable_hash(_normalized_section_signature(body))
            if section_hash in seen_section_hashes:
                continue
            seen_section_hashes.add(section_hash)
            page_blocks.append(
                "\n".join(
                    [
                        f"### {heading}",
                        "",
                        body,
                        "",
                        f"_Source: {document.final_url}_",
                    ]
                ).strip()
            )
        if not page_blocks:
            continue
        section_chunks.append("\n\n".join([f"## {group_title}", "", *page_blocks]))

    coverage = coverage_notes or []
    appendices = _build_appendices(state)
    content = [
        f"# {language.name} Documentation",
        "",
        "## Source Metadata",
        "",
        f"- Language: {language.name}",
        f"- Official source: {language.source_url}",
        f"- Adapter: {adapter.name if adapter is not None else 'generic'}",
        f"- Compiled pages: {len(ordered)}",
        f"- Resumable state: {'yes' if state is not None else 'no'}",
        "",
        "## Crawl Summary",
        "",
        f"- Processed pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'processed') if state else len(ordered)}",
        f"- Failed pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'failed') if state else 0}",
        f"- Skipped pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'skipped') if state else 0}",
        "",
        build_toc(toc_entries),
    ]
    if coverage:
        content.extend(["", "## Notes", ""])
        content.extend(f"- {note}" for note in coverage)
    if section_chunks:
        content.extend(["", *section_chunks])
    if appendices:
        content.extend(["", *appendices])

    final_markdown = normalize_compiled_markdown("\n".join(content) + "\n")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_markdown, encoding="utf-8")
    return output_path


def _group_documents(documents: list[ExtractedDocument], adapter: SiteAdapter | None) -> list[tuple[str, list[ExtractedDocument]]]:
    grouped: dict[str, list[ExtractedDocument]] = defaultdict(list)
    order: list[str] = []
    for document in documents:
        group = adapter.group_name(document.final_url, document.title, document.breadcrumbs) if adapter is not None else _default_group_name(document)
        if group not in grouped:
            order.append(group)
        grouped[group].append(document)
    return [(group, grouped[group]) for group in order]


def _default_group_name(document: ExtractedDocument) -> str:
    if document.breadcrumbs:
        return document.breadcrumbs[0]
    return document.title.strip() or "Content"


def _clean_page_body(markdown: str, *, title: str) -> str:
    body = markdown.strip()
    lines = body.splitlines()
    if lines and re.match(r"^#{1,3}\s+", lines[0]) and title.lower() in lines[0].lower():
        lines = lines[1:]
    body = "\n".join(lines).strip()
    body = re.sub(r"(?im)^_source:\s+[^\n]+_$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _normalized_section_signature(markdown: str) -> str:
    text = re.sub(r"(?m)^_Source:\s+[^\n]+_$", "", markdown)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:5000]


def _build_appendices(state: CrawlState | None) -> list[str]:
    if state is None:
        return []
    skipped = [page for page in state.pages.values() if page.status == "skipped"]
    failed = [page for page in state.pages.values() if page.status == "failed"]
    appendices: list[str] = []
    if skipped:
        appendices.extend(["## Appendix: Skipped Pages", ""])
        appendices.extend(f"- {page.normalized_url} ({', '.join(page.warning_codes) or 'no reason recorded'})" for page in skipped[:100])
        appendices.append("")
    if failed:
        appendices.extend(["## Appendix: Failed Pages", ""])
        appendices.extend(f"- {page.normalized_url}: {page.last_error or 'unknown error'}" for page in failed[:100])
        appendices.append("")
    return appendices

