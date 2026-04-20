from __future__ import annotations

import html
import re
from collections import Counter

from ..adapters import SiteAdapter
from ..models import ExtractedDocument
from ..utils.text import normalize_whitespace, stable_hash


BOILERPLATE_PATTERNS = [
    r"(?im)^\s*cookie(s)?\s*$",
    r"(?im)^\s*privacy\s+policy\s*$",
    r"(?im)^\s*all\s+rights\s+reserved\.?\s*$",
    r"(?im)^\s*feedback\s*$",
    r"(?im)^\s*skip\s+to\s+main\s+content\s*$",
    r"(?im)^\s*table\s+of\s+contents\s*$",
]
INLINE_HTML_PATTERNS = [
    (re.compile(r"<br\s*/?>", re.IGNORECASE), "\n"),
    (re.compile(r"</?(div|span|section|article|main|body)[^>]*>", re.IGNORECASE), ""),
    (re.compile(r"</?strong>", re.IGNORECASE), "**"),
    (re.compile(r"</?em>", re.IGNORECASE), "*"),
]


def normalize_document(document: ExtractedDocument, *, adapter: SiteAdapter | None = None) -> ExtractedDocument:
    markdown = _normalize_markdown_fragment(document.markdown, adapter=adapter)
    headings = _extract_headings(markdown)
    if not headings and document.title:
        markdown = f"## {document.title.strip()}\n\n{markdown}".strip() + "\n"
        headings = [document.title.strip()]
    document.markdown = markdown
    document.headings = headings
    document.word_count = len(markdown.split())
    document.content_hash = stable_hash(markdown)
    return document


def normalize_compiled_markdown(markdown: str) -> str:
    markdown = _normalize_markdown_fragment(markdown)
    markdown = re.sub(r"(?m)^_Source:\s+([^\n]+)_\n_Source:\s+[^\n]+_$", r"_Source: \1_", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return normalize_whitespace(markdown)


def _normalize_markdown_fragment(markdown: str, *, adapter: SiteAdapter | None = None) -> str:
    normalized = html.unescape(markdown.replace("\ufeff", ""))
    for pattern, replacement in INLINE_HTML_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    normalized = re.sub(r"(?m)^(#{1,6})([^ #])", r"\1 \2", normalized)
    normalized = re.sub(r"(?m)^([*-])([^\s])", r"\1 \2", normalized)
    normalized = re.sub(r"(?m)^(\d+\.)([^\s])", r"\1 \2", normalized)
    normalized = re.sub(r"(?m)^\s*>\s*", "> ", normalized)
    normalized = re.sub(r"\n```\n", "\n```text\n", normalized)
    normalized = _normalize_code_fences(normalized)
    normalized = _normalize_tables(normalized)
    normalized = _normalize_heading_levels(normalized)
    normalized = _remove_layout_noise(normalized, adapter=adapter)
    normalized = _dedupe_repeated_blocks(normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalize_whitespace(normalized)


def _normalize_heading_levels(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized_lines: list[str] = []
    seen_h1 = False
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not match:
            normalized_lines.append(line.rstrip())
            continue
        level = len(match.group(1))
        text = match.group(2).strip()
        if level == 1:
            if seen_h1:
                level = 2
            seen_h1 = True
        elif level > 4:
            level = 4
        normalized_lines.append(f"{'#' * level} {text}")
    return "\n".join(normalized_lines)


def _normalize_code_fences(markdown: str) -> str:
    lines = markdown.splitlines()
    fixed: list[str] = []
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            fence = line.strip()
            if not in_code and fence == "```":
                fence = "```text"
            in_code = not in_code
            fixed.append(fence)
        else:
            fixed.append(line.rstrip())
    if in_code:
        fixed.append("```")
    return "\n".join(fixed)


def _normalize_tables(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized: list[str] = []
    for line in lines:
        if "|" in line and line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            normalized.append("| " + " | ".join(cells) + " |")
        else:
            normalized.append(line)
    return "\n".join(normalized)


def _remove_layout_noise(markdown: str, *, adapter: SiteAdapter | None) -> str:
    cleaned = markdown
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    if adapter is not None:
        cleaned = adapter.clean_markdown(cleaned)
    cleaned = re.sub(r"(?im)^\s*\[(previous|next|home|up)\]\([^)]+\)\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*on\s+this\s+page\s*$", "", cleaned)
    return cleaned


def _dedupe_repeated_blocks(markdown: str) -> str:
    lines = markdown.splitlines()
    if len(lines) < 6:
        return markdown
    line_counts = Counter(line.strip() for line in lines if line.strip())
    common_lines = {line for line, count in line_counts.items() if count >= 3 and len(line) > 20}
    filtered = [line for line in lines if line.strip() not in common_lines or re.match(r"^#{1,4}\s", line)]
    kept: list[str] = []
    seen_blocks: set[str] = set()
    for start in range(0, len(filtered), 4):
        block = "\n".join(line.strip() for line in filtered[start : start + 4]).strip()
        if block and block in seen_blocks and len(block) > 60:
            continue
        if block:
            seen_blocks.add(block)
        kept.extend(filtered[start : start + 4])
    return "\n".join(kept)


def _extract_headings(markdown: str) -> list[str]:
    return [match.group(2).strip() for line in markdown.splitlines() if (match := re.match(r"^(#{1,6})\s+(.*)$", line))]

