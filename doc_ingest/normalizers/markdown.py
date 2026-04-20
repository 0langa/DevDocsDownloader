from __future__ import annotations

import re

from ..models import ExtractedDocument
from ..utils.text import normalize_whitespace


BOILERPLATE_PATTERNS = [
    r"(?im)^\s*cookie(s)?\s*$",
    r"(?im)^\s*privacy\s+policy\s*$",
    r"(?im)^\s*all\s+rights\s+reserved\.?\s*$",
    r"(?im)^\s*feedback\s*$",
]


def normalize_document(document: ExtractedDocument) -> ExtractedDocument:
    markdown = document.markdown
    for pattern in BOILERPLATE_PATTERNS:
        markdown = re.sub(pattern, "", markdown)

    markdown = re.sub(r"\n```\n", "\n```text\n", markdown)
    markdown = re.sub(r"(?m)^(#{1,6})([^ #])", r"\1 \2", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = normalize_whitespace(markdown)
    document.markdown = markdown
    document.word_count = len(markdown.split())
    return document