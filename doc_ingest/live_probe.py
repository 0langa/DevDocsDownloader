from __future__ import annotations

import asyncio
import sqlite3
import tarfile
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path

import httpx

from .conversion import DASH_PROFILE, DEVDOCS_PROFILE, convert_html_to_markdown, rewrite_markdown_links
from .sources.dash import CHEATSHEETS_URL, FEED_BASE, DashFeedSource
from .sources.devdocs import DOCS_INDEX_URL, DOCUMENTS_BASE
from .sources.mdn import CONTENT_ROOT_URL, _parse_frontmatter
from .utils.archive import safe_extract_tar

DEFAULT_PROBE_BYTES = 4096
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_DASH_ACCEPTANCE_MAX_BYTES = 12_000_000
DEFAULT_DASH_ACCEPTANCE_CANDIDATES = 12

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

    probes.append(partial(_probe_mdn, language="HTML", slug="html", area="web/html"))

    try:
        response = await client.get(CHEATSHEETS_URL)
        response.raise_for_status()
        entries = DashFeedSource(cache_dir=Path(tempfile.mkdtemp()))._discover_catalog_entries(response.text)
        for entry in entries[:64]:
            probes.append(partial(_probe_dash, language=entry.display_name, slug=entry.slug))
    except Exception as exc:
        probes.append(partial(_catalog_failure, source="dash", url=CHEATSHEETS_URL, exc=exc))

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
    url = f"{CONTENT_ROOT_URL}/{area}/index.md"
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
    display, area = "HTML", "web/html"
    url = f"{CONTENT_ROOT_URL}/{area}/index.md"
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
    try:
        response = await client.get(CHEATSHEETS_URL)
        response.raise_for_status()
        entries = DashFeedSource(cache_dir=Path(tempfile.mkdtemp()))._discover_catalog_entries(response.text)
        entry = await _select_dash_acceptance_entry(
            client,
            entries=entries,
            max_archive_bytes=DEFAULT_DASH_ACCEPTANCE_MAX_BYTES,
            candidate_limit=DEFAULT_DASH_ACCEPTANCE_CANDIDATES,
        )
    except Exception as exc:
        return LiveProbeResult(source, "Dash", "", CHEATSHEETS_URL, None, 0, False, f"{type(exc).__name__}: {exc}")
    if entry is None:
        return LiveProbeResult(source, "Dash", "", CHEATSHEETS_URL, None, 0, False, "no Dash catalog entries")
    slug = entry.slug
    language = entry.display_name
    url = f"{FEED_BASE}/{slug}.tgz"
    try:
        status_code, archive_bytes = await _download_dash_archive_with_limit(
            client,
            url=url,
            max_archive_bytes=DEFAULT_DASH_ACCEPTANCE_MAX_BYTES,
        )
        message = await asyncio.to_thread(_validate_dash_archive_acceptance, slug, archive_bytes)
        return LiveProbeResult(source, language, slug, url, status_code, len(archive_bytes), True, message)
    except Exception as exc:
        return LiveProbeResult(source, language, slug, url, None, 0, False, f"{type(exc).__name__}: {exc}")


async def _select_dash_acceptance_entry(
    client: httpx.AsyncClient,
    *,
    entries: list,
    max_archive_bytes: int,
    candidate_limit: int,
):
    limited = entries[: max(1, candidate_limit)]
    if not limited:
        return None
    sized: list[tuple[int, object]] = []
    for entry in limited:
        size = await _dash_archive_size_hint(client, f"{FEED_BASE}/{entry.slug}.tgz")
        if size is not None and size <= max_archive_bytes:
            sized.append((size, entry))
    if sized:
        sized.sort(key=lambda item: item[0])
        return sized[0][1]
    return limited[0]


async def _dash_archive_size_hint(client: httpx.AsyncClient, url: str) -> int | None:
    try:
        response = await client.head(url)
        if response.status_code >= 400:
            return None
        raw = response.headers.get("Content-Length")
        return int(raw) if raw and raw.isdigit() else None
    except Exception:
        return None


async def _download_dash_archive_with_limit(
    client: httpx.AsyncClient,
    *,
    url: str,
    max_archive_bytes: int,
) -> tuple[int | None, bytes]:
    downloaded = bytearray()
    status_code: int | None = None
    async with client.stream("GET", url) as response:
        status_code = response.status_code
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            downloaded.extend(chunk)
            if len(downloaded) > max_archive_bytes:
                raise ValueError(f"Dash acceptance archive exceeded {max_archive_bytes} byte budget")
    if not downloaded:
        raise ValueError("Dash acceptance archive was empty")
    if bytes(downloaded[:2]) != b"\x1f\x8b":
        raise ValueError("Dash acceptance archive did not start with gzip magic bytes")
    return status_code, bytes(downloaded)


def _validate_dash_archive_acceptance(slug: str, archive_bytes: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as archive:
            safe_extract_tar(archive, root)
        docsets = list(root.glob("*.docset"))
        if not docsets:
            raise ValueError("extracted archive did not contain a .docset")
        docset = docsets[0]
        dsidx = docset / "Contents" / "Resources" / "docSet.dsidx"
        docs_root = docset / "Contents" / "Resources" / "Documents"
        if not dsidx.exists():
            raise ValueError("extracted docset was missing docSet.dsidx")
        if not docs_root.exists():
            raise ValueError("extracted docset was missing Documents root")

        connection = sqlite3.connect(dsidx)
        try:
            rows = connection.execute(
                "SELECT name, type, path FROM searchIndex ORDER BY type, name LIMIT 200"
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            raise ValueError("Dash searchIndex query returned no rows")

        selected: tuple[str, str, str] | None = None
        for row_name, row_type, row_path in rows:
            doc_key = str(row_path).split("#", 1)[0] if row_path else ""
            if not doc_key:
                continue
            candidate = docs_root / doc_key
            if candidate.exists() and candidate.is_file():
                selected = (str(row_name), str(row_type), doc_key)
                break
        if selected is None:
            raise ValueError("Dash searchIndex rows did not map to a readable document file")

        name, entry_type, doc_key = selected
        html = (docs_root / doc_key).read_text(encoding="utf-8", errors="ignore")
        markdown = convert_html_to_markdown(html, base_url=f"dash://{slug}/{doc_key}", profile=DASH_PROFILE)
        if len(markdown.strip()) < 20:
            raise ValueError("Dash real-doc conversion produced tiny Markdown")
        return f"docset extracted, sqlite ok, converted {entry_type}:{name} from {doc_key}"


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
