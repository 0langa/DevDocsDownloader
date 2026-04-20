from __future__ import annotations

import io
import re

from pypdf import PdfReader

from ..models import ExtractedDocument, FetchResult
from ..utils.text import normalize_whitespace, stable_hash


def extract_pdf(fetch_result: FetchResult) -> ExtractedDocument:
    reader = PdfReader(io.BytesIO(fetch_result.content))
    parts: list[str] = []
    headings: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        cleaned = normalize_whitespace(text)
        if not cleaned.strip():
            continue
        first_line = cleaned.splitlines()[0].strip() if cleaned.splitlines() else f"Page {index}"
        headings.append(first_line[:120])
        parts.append(f"## Page {index}: {first_line}\n\n{cleaned}")

    markdown = "\n\n".join(parts)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    title = headings[0] if headings else fetch_result.final_url
    return ExtractedDocument(
        url=fetch_result.url,
        final_url=fetch_result.final_url,
        title=title,
        markdown=markdown,
        asset_type="pdf",
        headings=headings,
        links=[],
        word_count=len(markdown.split()),
        content_hash=stable_hash(markdown),
        source_order_hint="000-pdf-manual",
    )