from __future__ import annotations

import io

import mammoth

from ..models import ExtractedDocument, FetchResult
from ..utils.text import normalize_whitespace, stable_hash


def extract_markdown(fetch_result: FetchResult) -> ExtractedDocument:
    markdown = normalize_whitespace(fetch_result.content.decode("utf-8", errors="ignore"))
    title = markdown.splitlines()[0].lstrip("# ").strip() if markdown.strip() else fetch_result.final_url
    return ExtractedDocument(
        url=fetch_result.url,
        final_url=fetch_result.final_url,
        title=title,
        markdown=markdown,
        asset_type="markdown",
        headings=[title],
        links=[],
        word_count=len(markdown.split()),
        content_hash=stable_hash(markdown),
        source_order_hint=title.lower(),
    )


def extract_text(fetch_result: FetchResult) -> ExtractedDocument:
    text = normalize_whitespace(fetch_result.content.decode("utf-8", errors="ignore"))
    title = text.splitlines()[0][:120] if text.strip() else fetch_result.final_url
    markdown = f"## Extracted Text\n\n{text}"
    return ExtractedDocument(
        url=fetch_result.url,
        final_url=fetch_result.final_url,
        title=title,
        markdown=markdown,
        asset_type="text",
        headings=[title],
        links=[],
        word_count=len(markdown.split()),
        content_hash=stable_hash(markdown),
        source_order_hint=title.lower(),
    )


def extract_docx(fetch_result: FetchResult) -> ExtractedDocument:
    result = mammoth.convert_to_markdown(io.BytesIO(fetch_result.content))
    markdown = normalize_whitespace(result.value)
    title = markdown.splitlines()[0].lstrip("# ").strip() if markdown.strip() else fetch_result.final_url
    return ExtractedDocument(
        url=fetch_result.url,
        final_url=fetch_result.final_url,
        title=title,
        markdown=markdown,
        asset_type="docx",
        headings=[title],
        links=[],
        word_count=len(markdown.split()),
        content_hash=stable_hash(markdown),
        source_order_hint=title.lower(),
    )