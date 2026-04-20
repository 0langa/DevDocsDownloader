from __future__ import annotations

import re
from pathlib import Path

from ..models import ExtractedDocument, LanguageEntry


def build_toc(sections: list[tuple[str, str]]) -> str:
    lines = ["## Table of Contents", ""]
    for heading, anchor in sections:
        lines.append(f"- [{heading}](#{anchor})")
    return "\n".join(lines)


def _anchorize(text: str) -> str:
    anchor = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", anchor)


def compile_language_markdown(language: LanguageEntry, documents: list[ExtractedDocument], output_path: Path) -> Path:
    ordered = sorted(documents, key=lambda item: (item.source_order_hint, item.title.lower(), item.final_url))
    sections: list[str] = []
    toc_entries: list[tuple[str, str]] = []
    for document in ordered:
        heading = document.title.strip() or document.final_url
        anchor = _anchorize(heading)
        toc_entries.append((heading, anchor))
        body = document.markdown.strip()
        if body.startswith("# "):
            body = "\n".join(body.splitlines()[1:]).strip()
        sections.append(f"## {heading}\n\n_Source: {document.final_url}_\n\n{body}")

    content = [
        f"# {language.name} Documentation",
        "",
        f"- Official source: {language.source_url}",
        f"- Compiled pages: {len(ordered)}",
        "",
        build_toc(toc_entries),
        "",
        "\n\n---\n\n".join(sections),
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(content), encoding="utf-8")
    return output_path