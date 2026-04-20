from __future__ import annotations

from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse, urlencode


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_PARAMS]
    normalized = parsed._replace(fragment="", query=urlencode(query))
    path = normalized.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    normalized = normalized._replace(path=path)
    return urlunparse(normalized)


def resolve_url(base: str, href: str) -> str:
    return normalize_url(urljoin(base, href))