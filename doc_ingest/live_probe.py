from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import httpx

from .conversion import DASH_PROFILE, DEVDOCS_PROFILE, convert_html_to_markdown, rewrite_markdown_links
from .sources.dash import FEED_BASE
from .sources.devdocs import DOCS_INDEX_URL, DOCUMENTS_BASE
from .sources.mdn import AREAS, _parse_frontmatter

DEFAULT_PROBE_BYTES = 4096
DEFAULT_TIMEOUT_SECONDS = 20.0

MDN_RAW_BASE = "https://raw.githubusercontent.com/mdn/content/main/files/en-us"
ProbeCallable = Callable[[httpx.AsyncClient], Awaitable["LiveProbeResult"]]


@dataclass(slots=True)
class LiveProbeResult:
    source: str
    language: str
    source_slug: str
    probe_url: str
    status_code: int | None
    downloaded_bytes: int
    ok: bool
    message: str


async def probe_live_endpoints(
    *,
    concurrency: int = 5,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    limit: int | None = None,
    dash_seed_path: Path | None = None,
) -> list[LiveProbeResult]:
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DocIngestBot/1.0)"},
    ) as client:
        probes = await _build_probes(client=client, dash_seed_path=dash_seed_path)
        if limit is not None:
            probes = probes[: max(0, limit)]
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run_probe(probe: ProbeCallable) -> LiveProbeResult:
            async with semaphore:
                return await probe(client)

        return await asyncio.gather(*(run_probe(probe) for probe in probes))


async def probe_live_extraction_sanity(
    *,
    concurrency: int = 3,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    limit: int | None = None,
    dash_seed_path: Path | None = None,
) -> list[LiveProbeResult]:
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DocIngestBot/1.0)"},
    ) as client:
        probes: list[ProbeCallable] = [
            _probe_devdocs_extraction,
            _probe_mdn_extraction,
            partial(_probe_dash_extraction, dash_seed_path=dash_seed_path),
        ]
        if limit is not None:
            probes = probes[: max(0, limit)]
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run_probe(probe: ProbeCallable) -> LiveProbeResult:
            async with semaphore:
                return await probe(client)

        return await asyncio.gather(*(run_probe(probe) for probe in probes))


async def _build_probes(*, client: httpx.AsyncClient, dash_seed_path: Path | None) -> list[ProbeCallable]:
    probes: list[ProbeCallable] = []

    try:
        response = await client.get(DOCS_INDEX_URL)
        response.raise_for_status()
        entries = response.json()
        if not isinstance(entries, list):
            raise ValueError("DevDocs catalog did not return a list")
        for entry in entries:
            slug = str(entry.get("slug") or entry.get("name") or "").strip()
            if not slug:
                continue
            language = str(entry.get("name") or slug)
            probes.append(partial(_probe_devdocs, language=language, slug=slug))
    except Exception as exc:
        probes.append(partial(_catalog_failure, source="devdocs", url=DOCS_INDEX_URL, exc=exc))

    for slug, (display, area) in AREAS.items():
        probes.append(partial(_probe_mdn, language=display, slug=slug, area=area))

    for entry in _load_dash_seed(dash_seed_path):
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        language = str(entry.get("display_name") or slug)
        probes.append(partial(_probe_dash, language=language, slug=slug))

    return probes


async def _probe_devdocs(client: httpx.AsyncClient, language: str, slug: str) -> LiveProbeResult:
    url = f"{DOCUMENTS_BASE}/{slug}/index.json"
    return await _probe_capped_get(
        client,
        source="devdocs",
        language=language,
        source_slug=slug,
        url=url,
        require_gzip=False,
    )


async def _probe_mdn(client: httpx.AsyncClient, language: str, slug: str, area: str) -> LiveProbeResult:
    url = f"{MDN_RAW_BASE}/{area}/index.md"
    return await _probe_capped_get(
        client,
        source="mdn",
        language=language,
        source_slug=slug,
        url=url,
        require_gzip=False,
    )


async def _probe_dash(client: httpx.AsyncClient, language: str, slug: str) -> LiveProbeResult:
    url = f"{FEED_BASE}/{slug}.tgz"
    head_status: int | None = None
    try:
        head = await client.head(url)
        head_status = head.status_code
    except httpx.HTTPError:
        head_status = None

    result = await _probe_capped_get(
        client,
        source="dash",
        language=language,
        source_slug=slug,
        url=url,
        require_gzip=True,
    )
    if result.ok and head_status is not None and head_status >= 400:
        return LiveProbeResult(
            source=result.source,
            language=result.language,
            source_slug=result.source_slug,
            probe_url=result.probe_url,
            status_code=result.status_code,
            downloaded_bytes=result.downloaded_bytes,
            ok=True,
            message=f"GET succeeded; HEAD returned {head_status}",
        )
    return result


async def _probe_devdocs_extraction(client: httpx.AsyncClient) -> LiveProbeResult:
    source = "devdocs"
    url = DOCS_INDEX_URL
    downloaded = 0
    try:
        catalog_response = await client.get(DOCS_INDEX_URL)
        downloaded += len(catalog_response.content)
        catalog_response.raise_for_status()
        entries = catalog_response.json()
        if not isinstance(entries, list) or not entries:
            raise ValueError("DevDocs catalog did not return entries")
        selected = next((entry for entry in entries if str(entry.get("slug") or "").startswith("python")), entries[0])
        slug = str(selected.get("slug") or selected.get("name") or "").strip()
        language = str(selected.get("name") or slug)
        if not slug:
            raise ValueError("DevDocs catalog entry had no slug")
        url = f"{DOCUMENTS_BASE}/{slug}/db.json"
        response = await client.get(url)
        downloaded += len(response.content)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("DevDocs db.json was not an object")
        html = next((value for value in payload.values() if isinstance(value, str) and value.strip()), "")
        if not html:
            raise ValueError("DevDocs db.json contained no HTML document bodies")
        markdown = convert_html_to_markdown(html, base_url=f"https://devdocs.io/{slug}/", profile=DEVDOCS_PROFILE)
        if len(markdown.strip()) < 20:
            raise ValueError("DevDocs conversion produced tiny Markdown")
        return LiveProbeResult(source, language, slug, url, response.status_code, downloaded, True, "conversion ok")
    except Exception as exc:
        return LiveProbeResult(source, "DevDocs", "", url, None, downloaded, False, f"{type(exc).__name__}: {exc}")


async def _probe_mdn_extraction(client: httpx.AsyncClient) -> LiveProbeResult:
    source = "mdn"
    slug = "html"
    display, area = AREAS[slug]
    url = f"{MDN_RAW_BASE}/{area}/index.md"
    downloaded = 0
    try:
        response = await client.get(url)
        downloaded = len(response.content)
        response.raise_for_status()
        text = response.text
        metadata, body, warning = _parse_frontmatter(text)
        if warning:
            raise ValueError(warning)
        title = str(metadata.get("title") or "").strip()
        if not title:
            raise ValueError("MDN frontmatter title missing")
        markdown = rewrite_markdown_links(body.strip(), base_url=f"https://developer.mozilla.org/en-US/docs/{area}")
        if len(markdown.strip()) < 20:
            raise ValueError("MDN body produced tiny Markdown")
        return LiveProbeResult(source, display, slug, url, response.status_code, downloaded, True, "frontmatter ok")
    except Exception as exc:
        return LiveProbeResult(source, display, slug, url, None, downloaded, False, f"{type(exc).__name__}: {exc}")


async def _probe_dash_extraction(client: httpx.AsyncClient, *, dash_seed_path: Path | None = None) -> LiveProbeResult:
    source = "dash"
    entry = next(iter(_load_dash_seed(dash_seed_path)), {"slug": "Swift", "display_name": "Swift"})
    slug = str(entry.get("slug") or "Swift")
    language = str(entry.get("display_name") or slug)
    url = f"{FEED_BASE}/{slug}.tgz"
    archive_probe = await _probe_capped_get(
        client,
        source=source,
        language=language,
        source_slug=slug,
        url=url,
        require_gzip=True,
    )
    if not archive_probe.ok:
        return archive_probe
    html = """
    <html><body><nav>Noise</nav><main><h1>Dash Probe</h1><p>Content</p><pre><code>print(1)</code></pre></main></body></html>
    """
    markdown = convert_html_to_markdown(html, base_url=f"dash://{slug}/index.html", profile=DASH_PROFILE)
    if "Dash Probe" not in markdown or "print(1)" not in markdown:
        return LiveProbeResult(
            source,
            language,
            slug,
            url,
            archive_probe.status_code,
            archive_probe.downloaded_bytes,
            False,
            "Dash fixture conversion failed",
        )
    return LiveProbeResult(
        source,
        language,
        slug,
        url,
        archive_probe.status_code,
        archive_probe.downloaded_bytes,
        True,
        "archive shape and fixture conversion ok",
    )


async def _probe_capped_get(
    client: httpx.AsyncClient,
    *,
    source: str,
    language: str,
    source_slug: str,
    url: str,
    require_gzip: bool,
    max_bytes: int = DEFAULT_PROBE_BYTES,
) -> LiveProbeResult:
    downloaded = bytearray()
    status_code: int | None = None
    try:
        async with client.stream("GET", url, headers={"Range": f"bytes=0-{max_bytes - 1}"}) as response:
            status_code = response.status_code
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                downloaded.extend(chunk)
                if len(downloaded) >= max_bytes:
                    break
    except Exception as exc:
        return LiveProbeResult(
            source=source,
            language=language,
            source_slug=source_slug,
            probe_url=url,
            status_code=status_code,
            downloaded_bytes=len(downloaded),
            ok=False,
            message=f"{type(exc).__name__}: {exc}",
        )

    if not downloaded:
        return LiveProbeResult(source, language, source_slug, url, status_code, 0, False, "empty response")
    if require_gzip and not bytes(downloaded[:2]) == b"\x1f\x8b":
        return LiveProbeResult(
            source,
            language,
            source_slug,
            url,
            status_code,
            len(downloaded),
            False,
            "response did not start with gzip magic bytes",
        )
    return LiveProbeResult(source, language, source_slug, url, status_code, len(downloaded), True, "ok")


async def _catalog_failure(client: httpx.AsyncClient, *, source: str, url: str, exc: Exception) -> LiveProbeResult:
    return LiveProbeResult(
        source=source,
        language="<catalog>",
        source_slug="<catalog>",
        probe_url=url,
        status_code=None,
        downloaded_bytes=0,
        ok=False,
        message=f"{type(exc).__name__}: {exc}",
    )


def _load_dash_seed(seed_path: Path | None) -> list[dict]:
    path = seed_path or Path(__file__).parent / "sources" / "dash_seed.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
    except Exception:
        return []
    return []
