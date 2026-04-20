from __future__ import annotations

import html
import re

from ..models import ExtractedDocument
from ..utils.text import normalize_whitespace, stable_hash


BOILERPLATE_PATTERNS = [
    r"(?im)^\s*cookie(s)?\s*$",
    r"(?im)^\s*privacy\s+policy\s*$",
    r"(?im)^\s*all\s+rights\s+reserved\.?\s*$",
    r"(?im)^\s*feedback\s*$",
    r"(?im)^\s*skip\s+to\s+main\s+content\s*$",
]


def normalize_document(document: ExtractedDocument) -> ExtractedDocument:
    markdown = html.unescape(document.markdown.replace("\ufeff", ""))
    markdown = re.sub(r"<br\s*/?>", "\n", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"</?(div|span|section|article|main|body)[^>]*>", "", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"(?m)^(#{1,6})([^ #])", r"\1 \2", markdown)
    markdown = re.sub(r"(?m)^([*-])([^\s])", r"\1 \2", markdown)
    markdown = re.sub(r"(?m)^(\d+\.)([^\s])", r"\1 \2", markdown)
    markdown = re.sub(r"\n```\n", "\n```text\n", markdown)
    markdown = re.sub(r"(?m)^\s*>\s*", "> ", markdown)
    markdown = re.sub(r"(?m)[ \t]+$", "", markdown)
    markdown = _dedupe_repeated_blocks(markdown)
    for pattern in BOILERPLATE_PATTERNS:
        markdown = re.sub(pattern, "", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = normalize_whitespace(markdown)
    document.markdown = markdown
    document.word_count = len(markdown.split())
    document.content_hash = stable_hash(markdown)
    return document


def _dedupe_repeated_blocks(markdown: str) -> str:
    lines = markdown.splitlines()
    if len(lines) < 6:
        return markdown
    kept: list[str] = []
    seen_blocks: set[str] = set()
    for start in range(0, len(lines), 4):
        block = "\n".join(line.strip() for line in lines[start : start + 4]).strip()
        if block and block in seen_blocks and len(block) > 60:
            continue
        if block:
            seen_blocks.add(block)
        kept.extend(lines[start : start + 4])
    return "\n".join(kept)

