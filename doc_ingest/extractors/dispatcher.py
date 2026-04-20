from __future__ import annotations

from ..models import ExtractedDocument, FetchResult
from .html import extract_html
from .html_docling import extract_html_docling
from .pdf import extract_pdf
from .textual import extract_docx, extract_markdown, extract_text


def detect_asset_type(fetch_result: FetchResult) -> str:
    ct = fetch_result.content_type.lower()
    url = fetch_result.final_url.lower()
    if "html" in ct:
        return "html"
    if "markdown" in ct or url.endswith(".md"):
        return "markdown"
    if "pdf" in ct or url.endswith(".pdf"):
        return "pdf"
    if "wordprocessingml" in ct or url.endswith(".docx"):
        return "docx"
    if ct.startswith("text/"):
        return "text"
    return "unknown"


def extract_document(fetch_result: FetchResult) -> ExtractedDocument:
    asset_type = detect_asset_type(fetch_result)
    if asset_type == "html":
        return extract_html_docling(fetch_result)
    if asset_type == "markdown":
        return extract_markdown(fetch_result)
    if asset_type == "pdf":
        return extract_pdf(fetch_result)
    if asset_type == "docx":
        return extract_docx(fetch_result)
    return extract_text(fetch_result)