from __future__ import annotations

import re
from pathlib import Path

from ..models import CrawlState, ExtractedDocument, LanguageEntry


def build_toc(sections: list[tuple[str, str]]) -> str:
    lines = ["## Table of Contents", ""]
    for heading, anchor in sections:
        lines.append(f"- [{heading}](#{anchor})")
    return "\n".join(lines)


def _anchorize(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)


def _order_documents(documents: list[ExtractedDocument], state: CrawlState | None) -> list[ExtractedDocument]:
    state_pages = state.pages if state is not None else {}

    def sort_key(document: ExtractedDocument) -> tuple:
        page = state_pages.get(document.url) or state_pages.get(document.final_url)
        depth = page.depth if page is not None else 99
        parent = page.parent_url if page is not None else ""
        return (
            depth,
            parent or "",
            document.source_order_hint or "",
            "/".join(document.breadcrumbs).lower(),
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
) -> Path:
    ordered = _order_documents(documents, state)
    sections: list[str] = []
    toc_entries: list[tuple[str, str]] = []

    for index, document in enumerate(ordered, start=1):
        heading = document.title.strip() or document.final_url
        anchor = _anchorize(f"{index}-{heading}")
        toc_entries.append((heading, anchor))
        body = document.markdown.strip()
        if body.startswith("# "):
            body = "\n".join(body.splitlines()[1:]).strip()
        sections.append(
            "\n".join(
                [
                    f"## {index}. {heading}",
                    "",
                    f"_Source: {document.final_url}_",
                    f"_Extractor: {document.metadata.get('extractor', 'unknown')}_",
                    "",
                    body,
                ]
            )
        )

    coverage = coverage_notes or []
    summary_lines = [
        "## Source Metadata",
        "",
        f"- Language: {language.name}",
        f"- Official source: {language.source_url}",
        f"- Compiled pages: {len(ordered)}",
        f"- Resumable state: {'yes' if state is not None else 'no'}",
        "",
        "## Crawl Summary",
        "",
        f"- Processed pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'processed') if state else len(ordered)}",
        f"- Failed pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'failed') if state else 0}",
        f"- Skipped pages: {sum(1 for page in (state.pages.values() if state else []) if page.status == 'skipped') if state else 0}",
    ]
    if coverage:
        summary_lines.extend(["", "## Notes", ""])
        summary_lines.extend(f"- {note}" for note in coverage)

    content = [
        f"# {language.name} Documentation",
        "",
        *summary_lines,
        "",
        build_toc(toc_entries),
        "",
        "\n\n---\n\n".join(sections),
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(content), encoding="utf-8")
    return output_path

