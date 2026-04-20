from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown

from ..models import ExtractedDocument, FetchResult
from ..utils.text import normalize_whitespace, stable_hash
from ..utils.urls import resolve_url


JUNK_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    ".sidebar",
    ".toc",
    ".breadcrumbs",
    ".breadcrumb",
    ".cookie",
    ".consent",
    ".advertisement",
    ".feedback",
]


@dataclass
class HtmlDiscoveryResult:
    title: str
    final_url: str
    links: list[str]
    headings: list[str]


def extract_html_links(fetch_result: FetchResult) -> HtmlDiscoveryResult:
    html = fetch_result.content.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    for selector in JUNK_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    main = None
    for selector in ["main", "article", "[role='main']", ".main-content", ".content", "body"]:
        main = soup.select_one(selector)
        if main:
            break
    if main is None:
        main = soup

    title = soup.title.get_text(strip=True) if soup.title else fetch_result.final_url
    links: list[str] = []
    for anchor in main.select("a[href]"):
        href = anchor.get("href")
        if href:
            links.append(resolve_url(fetch_result.final_url, href))

    headings = [node.get_text(" ", strip=True) for node in main.select("h1, h2, h3, h4")]
    return HtmlDiscoveryResult(title=title, final_url=fetch_result.final_url, links=links, headings=headings)


def extract_html(fetch_result: FetchResult) -> ExtractedDocument:
    html = fetch_result.content.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    for selector in JUNK_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    main = None
    for selector in ["main", "article", "[role='main']", ".main-content", ".content", "body"]:
        main = soup.select_one(selector)
        if main:
            break
    if main is None:
        main = soup

    for code in main.select("pre code"):
        classes = " ".join(code.get("class", []))
        match = re.search(r"language-([\w#+-]+)", classes)
        language = match.group(1) if match else "text"
        code.string = f"```{language}\n{code.get_text()}\n```"

    markdown = html_to_markdown(
        str(main),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = normalize_whitespace(markdown)

    title = soup.title.get_text(strip=True) if soup.title else fetch_result.final_url
    links = []
    for anchor in main.select("a[href]"):
        href = anchor.get("href")
        if href:
            links.append(resolve_url(fetch_result.final_url, href))

    headings = [node.get_text(" ", strip=True) for node in main.select("h1, h2, h3, h4")]
    breadcrumbs = [node.get_text(" ", strip=True) for node in soup.select(".breadcrumb a, .breadcrumbs a, nav[aria-label='breadcrumb'] a") if node.get_text(" ", strip=True)]
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
