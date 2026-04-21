"""HTML extractor backed by Docling for higher-quality markdown conversion.

Docling converts the raw HTML into a ``DoclingDocument`` (a structured IR with
sections, headings, tables, code blocks, etc.) and then exports to Markdown.
This produces cleaner output than a raw markdownify pass because Docling
understands document structure rather than just serialising DOM nodes.

Link extraction still uses BeautifulSoup because Docling's output is the
*converted document*, not a navigation graph — href links in <a> tags are
irrelevant to the content representation but are essential for crawling.

The ``DocumentConverter`` is expensive to construct (registers pipelines,
allocates backend instances) so it is created once as a module-level
singleton and reused across all calls.  For the HTML ``SimplePipeline`` no
ML models are downloaded or loaded — it is a pure rule-based parser.
"""
from __future__ import annotations

import io
import logging
import re
import threading
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from ..adapters import SiteAdapter
from ..models import ExtractedDocument, FetchResult
from ..utils.text import normalize_whitespace, stable_hash
from ..utils.urls import resolve_url

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter as _DoclingConverter


LOGGER = logging.getLogger("doc_ingest.extractors.html_docling")

# ---------------------------------------------------------------------------
# Lazy singleton — created once on first call, protected by a lock so that
# concurrent workers don't each try to initialise at the same time.
# ---------------------------------------------------------------------------
_converter_lock = threading.Lock()
_converter: _DoclingConverter | None = None


def _get_converter() -> _DoclingConverter:
    global _converter
    if _converter is not None:
        return _converter
    with _converter_lock:
        if _converter is not None:  # double-checked locking
            return _converter
        from docling.backend.html_backend import HTMLDocumentBackend
        from docling.document_converter import DocumentConverter, FormatOption, InputFormat
        from docling.pipeline.simple_pipeline import SimplePipeline

        _converter = DocumentConverter(
            format_options={
                InputFormat.HTML: FormatOption(
                    pipeline_cls=SimplePipeline,
                    backend=HTMLDocumentBackend,
                )
            }
        )
        LOGGER.debug("Docling DocumentConverter initialised (HTML/SimplePipeline)")
        return _converter


# ---------------------------------------------------------------------------
# Selectors for navigation chrome we want to ignore during *link* extraction.
# (Docling handles content stripping on its own side.)
# ---------------------------------------------------------------------------
DEFAULT_LINK_STRIP_SELECTORS = [
    "nav", "header", "footer", "aside",
    ".sidebar", ".toc", ".breadcrumbs", ".breadcrumb",
    ".cookie", ".consent", ".advertisement", ".feedback",
]


def extract_html_docling(fetch_result: FetchResult, *, adapter: SiteAdapter | None = None) -> ExtractedDocument:
    """Convert an HTML page to Markdown via Docling and return an ExtractedDocument.

    Falls back transparently to the plain BS4+markdownify extractor if Docling
    raises an unexpected error, so a single broken page never kills a crawl.
    """
    try:
        return _docling_convert(fetch_result, adapter=adapter)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Docling conversion failed for %s (%s); falling back to BS4 extractor",
            fetch_result.final_url, exc,
        )
        from .html import extract_html  # local import to avoid circular deps at module load
        return extract_html(fetch_result, adapter=adapter)


def _docling_convert(fetch_result: FetchResult, *, adapter: SiteAdapter | None = None) -> ExtractedDocument:
    html_bytes = fetch_result.content
    html_str = html_bytes.decode("utf-8", errors="ignore")

    # ---- Docling conversion ------------------------------------------------
    from docling.datamodel.document import DocumentStream  # noqa: PLC0415

    converter = _get_converter()
    stream = DocumentStream(
        name=f"{fetch_result.final_url}.html",
        stream=io.BytesIO(html_bytes),
    )
    result = converter.convert(stream)
    markdown: str = result.document.export_to_markdown()
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = normalize_whitespace(markdown)

    # ---- Metadata via BS4 (title + links — Docling doesn't expose hrefs) ---
    soup = BeautifulSoup(html_str, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else fetch_result.final_url

    # Strip navigation chrome before collecting links so we only follow
    # content-area anchors, not sidebar / header / footer noise.
    for sel in (adapter.discovery_strip_candidates() if adapter is not None else DEFAULT_LINK_STRIP_SELECTORS):
        for el in soup.select(sel):
            el.decompose()

    main = None
    for sel in (adapter.content_root_candidates() if adapter is not None else ["main", "article", "[role='main']", ".main-content", ".content", "body"]):
        main = soup.select_one(sel)
        if main:
            break
    if main is None:
        main = soup

    links: list[str] = []
    for anchor in main.select("a[href]"):
        href = anchor.get("href")
        if href:
            links.append(resolve_url(fetch_result.final_url, href))

    headings = [node.get_text(" ", strip=True) for node in main.select("h1, h2, h3, h4")]
    breadcrumbs = []
    for selector in (adapter.breadcrumb_candidates() if adapter is not None else [".breadcrumb a", ".breadcrumbs a", "nav[aria-label='breadcrumb'] a"]):
        for node in soup.select(selector):
            label = node.get_text(" ", strip=True)
            if label and label not in breadcrumbs:
                breadcrumbs.append(label)

    return ExtractedDocument(
        url=fetch_result.url,
        final_url=fetch_result.final_url,
        title=title,
        markdown=markdown,
        asset_type="html",
        headings=headings,
        links=links,
        word_count=len(markdown.split()),
        content_hash=stable_hash(markdown),
        source_order_hint=title.lower(),
        breadcrumbs=breadcrumbs,
    )
