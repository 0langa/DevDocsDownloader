from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

INDEX_PAGE_SUFFIXES = {"/index.html", "/index.htm", "/index.md", "/README.md", "/readme.md"}
DEFAULT_DROP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref",
    "source",
    "trk",
    "spm",
    "from",
    "mkt_tok",
}
DOCUMENT_EXTENSIONS = {".html", ".htm", ".md", ".txt", ".pdf", ".docx"}
NON_DOCUMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".map",
    ".json",
    ".xml",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
}


def normalize_url(
    url: str,
    *,
    drop_query_params: Iterable[str] | None = None,
    keep_query_params: Iterable[str] | None = None,
    prefer_https: bool = True,
) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    if prefer_https and scheme == "http":
        scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    keep = {value.lower() for value in keep_query_params or []}
    drop = {value.lower() for value in drop_query_params or DEFAULT_DROP_QUERY_PARAMS}
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in keep or lowered not in drop:
            query_items.append((lowered, value))
    query_items.sort()

    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = f"/{path}"
    for suffix in INDEX_PAGE_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)] or "/"
            break
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    normalized = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=path,
        params="",
        query=urlencode(query_items),
        fragment="",
    )
    return urlunparse(normalized)


def resolve_url(base: str, href: str, **kwargs: object) -> str:
    drop_query_params = kwargs.get("drop_query_params")
    keep_query_params = kwargs.get("keep_query_params")
    prefer_https = kwargs.get("prefer_https", True)
    return normalize_url(
        urljoin(base, href),
        drop_query_params=drop_query_params if isinstance(drop_query_params, Iterable) else None,
        keep_query_params=keep_query_params if isinstance(keep_query_params, Iterable) else None,
        prefer_https=prefer_https if isinstance(prefer_https, bool) else True,
    )


def canonicalize_url_for_content(url: str) -> str:
    return normalize_url(url, keep_query_params=["lang", "locale", "hl", "view", "version"])


def is_probably_document_url(url: str) -> bool:
    parsed = urlparse(url)
    lowered = parsed.path.lower()
    if any(lowered.endswith(ext) for ext in NON_DOCUMENT_EXTENSIONS):
        return False
    if any(lowered.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
        return True
    return not lowered.endswith("/")


def strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def same_domain(url: str, allowed_domains: Iterable[str]) -> bool:
    host = urlparse(url).netloc.lower()
    normalized_domains = {domain.lower() for domain in allowed_domains}
    return host in normalized_domains
