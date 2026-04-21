from __future__ import annotations

from collections.abc import Iterable

from ..adapters import SiteAdapter
from ..models import ExtractedDocument, FetchResult
from .html import extract_html
from .html_docling import extract_html_docling
from .pdf import extract_pdf
from .scoring import score_extraction
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


def extract_document(fetch_result: FetchResult, *, preferred_extractors: Iterable[str] | None = None, adapter: SiteAdapter | None = None, docling_timeout_seconds: float = 25.0) -> ExtractedDocument:
    asset_type = detect_asset_type(fetch_result)
    if asset_type == "html":
        return _extract_html_with_scoring(fetch_result, preferred_extractors=preferred_extractors or [], adapter=adapter, docling_timeout_seconds=docling_timeout_seconds)
    if asset_type == "markdown":
        document = extract_markdown(fetch_result)
        document.extraction = score_extraction(document, "markdown_passthrough")
        document.metadata["extractor"] = document.extraction.extractor
        return document
    if asset_type == "pdf":
        document = extract_pdf(fetch_result)
        document.extraction = score_extraction(document, "pdf_text")
        document.metadata["extractor"] = document.extraction.extractor
        return document
    if asset_type == "docx":
        document = extract_docx(fetch_result)
        document.extraction = score_extraction(document, "docx_mammoth")
        document.metadata["extractor"] = document.extraction.extractor
        return document
    document = extract_text(fetch_result)
    document.extraction = score_extraction(document, "text_plain")
    document.metadata["extractor"] = document.extraction.extractor
    return document


def _extract_html_with_scoring(fetch_result: FetchResult, *, preferred_extractors: Iterable[str], adapter: SiteAdapter | None, docling_timeout_seconds: float = 25.0) -> ExtractedDocument:
    candidates: list[tuple[str, ExtractedDocument]] = []
    extractor_map = {
        "html_docling": lambda result: extract_html_docling(result, adapter=adapter, timeout_seconds=docling_timeout_seconds),
        "html_readability": lambda result: extract_html(result, adapter=adapter),
        "html_bs4": lambda result: extract_html(result, adapter=adapter),
    }
    preferred = [name for name in preferred_extractors if name in extractor_map]
    order = preferred + [name for name in ["html_docling", "html_readability"] if name not in preferred]

    for extractor_name in order:
        extractor = extractor_map[extractor_name]
        try:
            document = extractor(fetch_result)
        except Exception:
            continue
        decision = score_extraction(document, extractor_name)
        candidates.append((extractor_name, document.model_copy(update={"extraction": decision})))

    if not candidates:
        document = extract_html(fetch_result, adapter=adapter)
        decision = score_extraction(document, "html_readability")
        document.extraction = decision
        document.metadata["extractor"] = decision.extractor
        return document

    winner_name, winner = max(
        candidates,
        key=lambda item: (
            item[1].extraction.score if item[1].extraction else 0.0,
            item[1].word_count,
            len(item[1].headings),
        ),
    )
    winner.extraction.candidates = [
        {
            "extractor": name,
            "score": doc.extraction.score if doc.extraction else 0.0,
            "word_count": doc.word_count,
            "heading_count": len(doc.headings),
        }
        for name, doc in candidates
    ]
    winner.metadata["extractor"] = winner_name
    return winner

