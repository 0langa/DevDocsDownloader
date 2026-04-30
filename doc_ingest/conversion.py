from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

SAFE_LINK_SCHEMES = {"http", "https", "mailto", "tel", "data", "dash"}
NOISE_SELECTORS = [
    "nav",
    "aside",
    "header",
    "footer",
    "script",
    "style",
    "template",
    "[hidden]",
    "[aria-hidden='true']",
    "[role='navigation']",
    "[role='search']",
    ".breadcrumb",
    ".breadcrumbs",
    ".sidebar",
    ".side-bar",
    ".toc",
    ".table-of-contents",
    ".search",
    ".searchbox",
    ".toolbar",
    ".pagination",
    ".page-header",
    ".page-footer",
]


@dataclass(frozen=True)
class HtmlCleanupProfile:
    content_selectors: tuple[str, ...]
    noise_selectors: tuple[str, ...] = tuple(NOISE_SELECTORS)


@dataclass(frozen=True)
class ConversionDiagnostics:
    matched_selector: str


DEVDOCS_PROFILE = HtmlCleanupProfile(
    content_selectors=(
        "main",
        "article",
        ".content",
        ".doc",
        ".docs",
        ".entry",
        ".documentation",
        "#content",
    )
)

DASH_PROFILE = HtmlCleanupProfile(
    content_selectors=(
        "main",
        "article",
        ".content",
        ".contents",
        ".documentation",
        ".doc-content",
        "#content",
        "body",
    )
)


def convert_html_to_markdown(html: str, *, base_url: str, profile: HtmlCleanupProfile) -> str:
    soup = _parse_html(html)
    root, _ = _select_content_root(soup, profile)
    _remove_noise(root, profile)
    _normalize_links(root, base_url=base_url)
    markdown = html_to_md(str(root), heading_style="ATX", strip=["script", "style"])
    return normalize_markdown_quality(markdown)


def convert_html_to_markdown_with_diagnostics(
    html: str, *, base_url: str, profile: HtmlCleanupProfile
) -> tuple[str, ConversionDiagnostics]:
    soup = _parse_html(html)
    root, matched_selector = _select_content_root(soup, profile)
    _remove_noise(root, profile)
    _normalize_links(root, base_url=base_url)
    markdown = html_to_md(str(root), heading_style="ATX", strip=["script", "style"])
    return normalize_markdown_quality(markdown), ConversionDiagnostics(matched_selector=matched_selector)


def rewrite_markdown_links(markdown: str, *, base_url: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue
        lines.append(_rewrite_links_outside_code_spans(line, base_url=base_url))
    return "\n".join(lines)


def normalize_markdown_quality(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def resolve_source_link(target: str, *, base_url: str) -> str:
    cleaned = target.strip()
    if not cleaned or cleaned.startswith("#"):
        return cleaned
    parsed = urlparse(cleaned)
    if parsed.scheme in SAFE_LINK_SCHEMES:
        return cleaned
    if parsed.scheme:
        return cleaned
    if base_url.startswith("dash://"):
        return _dash_join(base_url, cleaned)
    return urljoin(base_url, cleaned)


def _parse_html(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml should be available at runtime
        return BeautifulSoup(html, "html.parser")


def _select_content_root(soup: BeautifulSoup, profile: HtmlCleanupProfile):
    for selector in profile.content_selectors:
        found = soup.select_one(selector)
        if found is not None:
            return found, selector
    return soup, "document"


def _remove_noise(root, profile: HtmlCleanupProfile) -> None:
    for selector in profile.noise_selectors:
        for node in root.select(selector):
            node.decompose()


def _normalize_links(root, *, base_url: str) -> None:
    for node in root.select("[href]"):
        href = node.get("href")
        if isinstance(href, str):
            node["href"] = resolve_source_link(href, base_url=base_url)
    for node in root.select("[src]"):
        src = node.get("src")
        if isinstance(src, str):
            node["src"] = resolve_source_link(src, base_url=base_url)


_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)]*)\)")


def _rewrite_links_outside_code_spans(line: str, *, base_url: str) -> str:
    segments = line.split("`")
    for index in range(0, len(segments), 2):
        segments[index] = _MARKDOWN_LINK_RE.sub(
            lambda match: _replace_markdown_link(match, base_url=base_url),
            segments[index],
        )
    return "`".join(segments)


def _replace_markdown_link(match: re.Match[str], *, base_url: str) -> str:
    marker, label, target = match.groups()
    stripped = target.strip()
    if not stripped:
        return match.group(0)
    return f"{marker}[{label}]({resolve_source_link(stripped, base_url=base_url)})"


def _dash_join(base_url: str, target: str) -> str:
    if target.startswith("/"):
        parsed = urlparse(base_url)
        return f"dash://{parsed.netloc}{target}"
    prefix, _, _name = base_url.rpartition("/")
    return f"{prefix}/{target}" if prefix else f"{base_url}/{target}"
