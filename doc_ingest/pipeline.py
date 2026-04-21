from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from .adaptive import AdaptiveRuntimeController
from .adapters import select_adapter
from .config import AppConfig
from .discovery import DiscoveryHelper, RobotsCache
from .extractors.dispatcher import detect_asset_type, extract_document
from .extractors.html import extract_html
from .fetchers.browser import BrowserFetcher
from .fetchers.http import HttpFetcher
from .mergers.compiler import compile_language_markdown
from .models import CrawlMode, CrawlState, ExtractedDocument, LanguageEntry, LanguageRunReport, PageState, PlannedSource, RunSummary, UrlRecord
from .normalizers.markdown import normalize_document
from .parser import parse_language_file
from .planner.planner import CrawlPlanner
from .progress import CrawlProgressTracker
from .reporting.writer import write_reports
from .state import CrawlStateStore
from .utils.filesystem import read_json, write_json, write_text
from .utils.text import stable_hash
from .utils.urls import canonicalize_url_for_content, normalize_url
from .validators.markdown_validator import validate_markdown


LOGGER = logging.getLogger("doc_ingest")


class DiscoveryDocument:
    def __init__(self, *, title: str, final_url: str, links: list[str], breadcrumbs: list[str]) -> None:
        self.title = title
        self.final_url = final_url
        self.links = links
        self.breadcrumbs = breadcrumbs


class DocumentationPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.http_fetcher = HttpFetcher(config)
        self.browser_fetcher = BrowserFetcher(config)
        self.planner = CrawlPlanner(config)
        self.adaptive_controller = AdaptiveRuntimeController(config)
        self.robots = RobotsCache(config)
        self.http_fetcher.set_adaptive_controller(self.adaptive_controller)

    async def close(self) -> None:
        await self.http_fetcher.close()
        await self.browser_fetcher.close()

    async def run(
        self,
        language_name: str | None = None,
        force_refresh: bool = False,
        dry_run: bool = False,
        validate_only: bool = False,
        language_concurrency: int | None = None,
        crawl_mode: CrawlMode | None = None,
        progress_tracker: CrawlProgressTracker | None = None,
    ) -> RunSummary:
        entries = parse_language_file(self.config.paths.input_file)
        if language_name:
            needle = language_name.lower()
            entries = [entry for entry in entries if entry.name.lower() == needle or entry.slug == needle]

        if progress_tracker is not None:
            await progress_tracker.set_total_languages(len(entries))
            await progress_tracker.register_languages(entries)

        concurrency = max(1, language_concurrency or self.config.crawl.language_concurrency)
        summary = RunSummary()
        semaphore = asyncio.Semaphore(concurrency)

        async def _run_entry(entry: LanguageEntry) -> LanguageRunReport:
            async with semaphore:
                return await self._run_language(
                    entry,
                    force_refresh=force_refresh,
                    dry_run=dry_run,
                    validate_only=validate_only,
                    crawl_mode=crawl_mode,
                    progress_tracker=progress_tracker,
                )

        reports = await asyncio.gather(*[_run_entry(entry) for entry in entries])
        summary.reports.extend(reports)
        write_reports(summary, self.config.paths.reports_dir)
        return summary

    async def _run_language(
        self,
        language: LanguageEntry,
        force_refresh: bool,
        dry_run: bool,
        validate_only: bool,
        crawl_mode: CrawlMode | None,
        progress_tracker: CrawlProgressTracker | None,
    ) -> LanguageRunReport:
        plan = self.planner.plan(language)
        if crawl_mode is not None:
            plan.crawl_mode = crawl_mode
        adapter, _override = select_adapter(language, self.config)
        report = LanguageRunReport(
            language=language.name,
            slug=language.slug,
            source_url=str(language.source_url),
            strategy=plan.strategy,
            adapter=adapter.name,
        )
        output_path = self.config.paths.markdown_dir / f"{language.slug}.md"
        state_path = self.config.paths.state_dir / f"{language.slug}.json"
        diagnostics_path = self.config.paths.diagnostics_dir / f"{language.slug}.tree.txt"
        state_store = CrawlStateStore(state_path, language=language.name, slug=language.slug, source_url=str(language.source_url))

        if validate_only:
            if output_path.exists():
                report.output_path = output_path
                report.validation = validate_markdown(language.name, output_path, self.config, state=state_store.load())
            else:
                report.failures.append("Output markdown file does not exist.")
            return report

        if dry_run:
            report.coverage_notes.extend(plan.notes)
            report.warnings.extend(plan.notes)
            return report

        if force_refresh and state_path.exists():
            state_path.unlink()

        state = state_store.load()
        state.plan = plan.model_dump(mode="json")
        documents: dict[str, ExtractedDocument] = self._load_cached_documents(language.slug, state)
        processed_hashes = {document.content_hash for document in documents.values()}
        helper = DiscoveryHelper(self.config, adapter, plan)
        queue: asyncio.Queue[UrlRecord | None] = asyncio.Queue(maxsize=max(0, self.config.crawl.max_queue_size_per_language))
        queued_urls: set[str] = set()
        dirty = False
        pending_changes = 0
        last_persist_at = time.monotonic()

        async def update_queue_progress() -> None:
            if progress_tracker is not None:
                await progress_tracker.on_queue_size_changed(language.slug, queue.qsize())

        async def persist_state(force: bool = False) -> None:
            nonlocal dirty, pending_changes, last_persist_at
            if not dirty and not force:
                return
            if (
                not force
                and pending_changes < self.config.crawl.persist_every_changes
                and (time.monotonic() - last_persist_at) < self.config.crawl.persist_every_seconds
            ):
                return
            tree = self._build_discovered_tree_text(state)
            await asyncio.to_thread(state_store.save, state)
            await asyncio.to_thread(write_text, diagnostics_path, tree)
            dirty = False
            pending_changes = 0
            last_persist_at = time.monotonic()

        async def enqueue(record: UrlRecord) -> None:
            normalized = canonicalize_url_for_content(record.normalized_url)
            if normalized in queued_urls:
                return
            if normalized not in state.pages and len(state.pages) >= self.config.crawl.max_pages_per_language:
                return
            page = state.pages.get(normalized)
            if page is not None and page.status in {"processed", "failed", "skipped"}:
                return
            if len(state.pages) >= self.config.crawl.max_discovered_urls_per_language:
                return
            if not helper.should_visit(normalized):
                return
            if not await self.robots.allowed(normalized):
                return
            queued_urls.add(normalized)
            state.pages.setdefault(
                normalized,
                PageState(
                    normalized_url=normalized,
                    discovered_url=record.url,
                    parent_url=record.parent_url,
                    depth=record.depth,
                    discovered_from=record.discovered_from,
                    status="pending",
                ),
            )
            await queue.put(record.model_copy(update={"normalized_url": normalized}))
            await update_queue_progress()

        pending_extractions: list[asyncio.Task] = []

        async def _fast_discover(fetch_result: FetchResult) -> DiscoveryDocument:
            """BS4-only link extraction — fast, no Docling, keeps workers unblocked."""
            if detect_asset_type(fetch_result) != "html":
                return DiscoveryDocument(title=fetch_result.final_url, final_url=fetch_result.final_url, links=[], breadcrumbs=[])
            doc = await asyncio.to_thread(extract_html, fetch_result, adapter=adapter)
            return DiscoveryDocument(title=doc.title, final_url=doc.final_url, links=doc.links, breadcrumbs=doc.breadcrumbs)

        async def _full_extract_and_store(
            record: UrlRecord,
            fetch_result: FetchResult,
            normalized: str,
            page: PageState,
        ) -> None:
            nonlocal dirty, pending_changes
            try:
                document = await asyncio.to_thread(
                    extract_document,
                    fetch_result,
                    preferred_extractors=plan.preferred_extractors,
                    adapter=adapter,
                    docling_timeout_seconds=self.config.crawl.docling_timeout_seconds,
                )
                if adapter.should_retry_with_browser(
                    asset_type=detect_asset_type(fetch_result),
                    fetch_method=fetch_result.method,
                    word_count=document.word_count,
                    extraction_score=document.extraction.score if document.extraction else None,
                ) and self.config.crawl.browser_enabled:
                    try:
                        cache_dir = self.config.paths.cache_dir / plan.language.slug
                        browser_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
                        browser_doc = await asyncio.to_thread(
                            extract_document, browser_result,
                            preferred_extractors=plan.preferred_extractors,
                            adapter=adapter,
                            docling_timeout_seconds=self.config.crawl.docling_timeout_seconds,
                        )
                        if browser_doc.extraction and document.extraction and browser_doc.extraction.score > document.extraction.score:
                            document = browser_doc
                    except Exception:
                        LOGGER.debug("Browser fallback failed for %s", record.normalized_url, exc_info=True)

                if document.word_count < 10:
                    page.status = "skipped"
                    page.warning_codes.append("low-content")
                    report.pages_skipped += 1
                    dirty = True
                    pending_changes += 1
                    return

                document = normalize_document(document, adapter=adapter)
                page.asset_type = document.asset_type
                page.extractor = document.metadata.get("extractor")
                page.extraction_score = document.extraction.score if document.extraction else None
                page.extraction_notes = document.extraction.won_because if document.extraction else []
                page.source_order_hint = document.source_order_hint
                page.metadata = {"breadcrumbs": document.breadcrumbs, "final_url": document.final_url}
                for code in self._quality_warning_codes(document):
                    page.warning_codes.append(code)
                    report.warnings_by_code[code] = report.warnings_by_code.get(code, 0) + 1

                if document.content_hash in processed_hashes:
                    page.status = "skipped"
                    page.duplicate_of = next((url for url, d in documents.items() if d.content_hash == document.content_hash), None)
                    page.warning_codes.append("duplicate-content")
                    report.pages_deduplicated += 1
                    report.pages_skipped += 1
                else:
                    page.status = "processed"
                    page.content_hash = document.content_hash
                    documents[normalized] = document
                    processed_hashes.add(document.content_hash)
                    report.pages_processed = len(documents)
                    report.assets_processed += 1 if document.asset_type != "html" else 0
                    report.extractor_choices[page.extractor or "unknown"] = report.extractor_choices.get(page.extractor or "unknown", 0) + 1
                    await asyncio.to_thread(self._persist_document_cache, language.slug, normalized, document)

                dirty = True
                pending_changes += 1
                await persist_state()
            except Exception:
                LOGGER.exception("Extraction failed for %s", record.url)
                if page.status not in {"processed", "skipped"}:
                    page.status = "failed"
                    report.pages_failed += 1
                    dirty = True
                    pending_changes += 1

        async def discovery_worker() -> None:
            while True:
                record = await queue.get()
                await update_queue_progress()
                if record is None:
                    queue.task_done()
                    return
                try:
                    normalized = canonicalize_url_for_content(record.normalized_url)
                    page = state.pages.setdefault(
                        normalized,
                        PageState(
                            normalized_url=normalized,
                            discovered_url=record.url,
                            parent_url=record.parent_url,
                            depth=record.depth,
                            discovered_from=record.discovered_from,
                            status="pending",
                        ),
                    )
                    if page.status in {"processed", "failed", "skipped"}:
                        return
                    page.attempts += 1
                    report.pages_queued = max(report.pages_queued, len(state.pages))

                    cache_dir = self.config.paths.cache_dir / plan.language.slug
                    try:
                        fetch_result = await self.http_fetcher.fetch(record.normalized_url, cache_dir)
                        if progress_tracker is not None:
                            await progress_tracker.on_fetch_complete(plan.language.slug, fetch_result.status_code, fetch_result.history_status_codes, fetch_result.method)
                        if fetch_result.status_code >= 400:
                            raise RuntimeError(f"HTTP {fetch_result.status_code}")
                        if detect_asset_type(fetch_result) == "unknown" and self.config.crawl.browser_enabled:
                            fetch_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
                    except Exception as exc:
                        if progress_tracker is not None:
                            await progress_tracker.on_request_failure(plan.language.slug)
                        LOGGER.exception("Failed fetching %s", record.url)
                        page.status = "failed"
                        page.last_error = str(exc)
                        report.pages_failed += 1
                        report.failures.append(f"{record.url}: {exc}")
                        dirty = True
                        pending_changes += 1
                        return

                    report.pages_fetched += 1

                    # Fast BS4 discovery — no Docling, worker returns to queue immediately after
                    discovery_doc = await _fast_discover(fetch_result)
                    page.title = discovery_doc.title

                    for link in self._discover_links(discovery_doc, helper, plan, record.depth):
                        await enqueue(link)

                    # Docling extraction runs in background — doesn't block this worker
                    task = asyncio.create_task(_full_extract_and_store(record, fetch_result, normalized, page))
                    pending_extractions.append(task)
                    await persist_state()
                finally:
                    queue.task_done()
                    await update_queue_progress()

        initial_urls = [helper.make_record(url, depth=0, discovered_from="seed") for url in plan.start_urls]
        sitemap_urls = await helper.load_sitemap_urls()
        initial_urls.extend(helper.make_record(url, depth=1, discovered_from="sitemap") for url in sitemap_urls)
        for page in state.pages.values():
            if page.status in {"pending", "discovered"}:
                initial_urls.append(
                    helper.make_record(
                        page.normalized_url,
                        depth=page.depth,
                        parent_url=page.parent_url,
                        discovered_from=page.discovered_from or "resume",
                    )
                )
        for record in initial_urls:
            await enqueue(record)

        report.pages_discovered = len(state.pages)
        workers = [asyncio.create_task(discovery_worker()) for _ in range(max(1, self.config.crawl.max_concurrency))]

        async def _tune_loop() -> None:
            while True:
                await asyncio.sleep(5.0)
                queue_fill_ratio = queue.qsize() / max(1, self.config.crawl.max_queue_size_per_language or max(1, queue.qsize()))
                await self.adaptive_controller.tune(queue_fill_ratio=queue_fill_ratio, limit_hit=len(state.pages) >= self.config.crawl.max_discovered_urls_per_language)

        tune_task = asyncio.create_task(_tune_loop())
        try:
            await queue.join()
            # Wait for all background Docling extractions that were fired during the crawl
            if pending_extractions:
                await asyncio.gather(*pending_extractions, return_exceptions=True)
        finally:
            tune_task.cancel()
            try:
                await tune_task
            except asyncio.CancelledError:
                pass

        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers, return_exceptions=True)

        state.compiled = False
        await persist_state(force=True)

        if not documents:
            report.failures.append("No documents were processed.")
            report.suspected_incompleteness = True
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language.slug, report)
            return report

        report.pages_discovered = len(state.pages)
        report.coverage_notes.extend(self._coverage_notes(state, report, plan))
        report.output_path = compile_language_markdown(
            language,
            list(documents.values()),
            output_path,
            state=state,
            coverage_notes=report.coverage_notes,
            adapter=adapter,
        )
        state.compiled = True
        state.compiled_at = datetime.now(timezone.utc)
        state.output_path = str(report.output_path)
        await persist_state(force=True)
        report.validation = validate_markdown(language.name, output_path, self.config, state=state)
        report.suspected_incompleteness = bool(report.validation and report.validation.score < 0.7)
        if progress_tracker is not None:
            await progress_tracker.on_language_complete(language.slug, report)
        return report

    def _discover_links(self, document: DiscoveryDocument, helper: DiscoveryHelper, plan: PlannedSource, depth: int) -> list[UrlRecord]:
        if depth >= plan.max_depth:
            return []
        discovered: dict[str, UrlRecord] = {}
        for link in document.links:
            normalized = normalize_url(link, drop_query_params=self.config.crawl.drop_query_params, keep_query_params=self.config.crawl.keep_query_params)
            if not helper.should_visit(normalized):
                continue
            if not self._is_preferred_locale_url(normalized):
                continue
            if plan.crawl_mode == "important" and not self._is_important_link(normalized):
                continue
            discovered[normalized] = helper.make_record(
                normalized,
                depth=depth + 1,
                parent_url=document.final_url,
                discovered_from="internal-link",
            )
        return list(discovered.values())

    def _is_preferred_locale_url(self, url: str) -> bool:
        parsed = urlparse(url)
        preferred = self.config.planner.preferred_locale.lower()
        aliases = {value.lower() for value in self.config.planner.locale_aliases}
        blocked = {value.lower() for value in self.config.planner.common_nonpreferred_locales if value.lower() not in aliases}

        path_parts = [part.lower() for part in parsed.path.split("/") if part]
        for part in path_parts:
            if part in blocked:
                return False
            if part in aliases:
                return True

        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"lang", "locale", "hl"}:
                locale_value = value.lower()
                if locale_value in blocked:
                    return False
                if locale_value in aliases:
                    return True

        host = parsed.netloc.lower()
        for locale in blocked:
            if host.startswith(f"{locale}.") or f"/{locale}/" in parsed.path.lower():
                return False

        return preferred in aliases

    def _is_important_link(self, url: str) -> bool:
        lowered = url.lower()
        keywords = [keyword.lower() for keyword in self.config.planner.important_path_keywords]
        return any(keyword in lowered for keyword in keywords)

    def _persist_document_cache(self, slug: str, normalized_url: str, document: ExtractedDocument) -> None:
        cache_dir = self.config.paths.cache_dir / slug / "normalized"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{stable_hash(normalized_url)}.json"
        write_json(cache_path, document.model_dump(mode="json"))

    def _load_cached_documents(self, slug: str, state: CrawlState) -> dict[str, ExtractedDocument]:
        cache_dir = self.config.paths.cache_dir / slug / "normalized"
        documents: dict[str, ExtractedDocument] = {}
        if not cache_dir.exists():
            return documents
        for normalized_url, page in state.pages.items():
            if page.status != "processed":
                continue
            cache_path = cache_dir / f"{stable_hash(normalized_url)}.json"
            if not cache_path.exists():
                continue
            try:
                documents[normalized_url] = ExtractedDocument.model_validate(read_json(cache_path, {}))
            except Exception:
                LOGGER.debug("Failed to load cached document %s", cache_path, exc_info=True)
        return documents

    def _coverage_notes(self, state: CrawlState, report: LanguageRunReport, plan: PlannedSource) -> list[str]:
        notes = list(plan.notes)
        failed = [page for page in state.pages.values() if page.status == "failed"]
        low_score = [page for page in state.pages.values() if (page.extraction_score or 0.0) < 0.35 and page.status == "processed"]
        noisy = [page for page in state.pages.values() if "layout-noise" in page.warning_codes]
        if failed:
            notes.append(f"{len(failed)} pages failed and may require adapter tuning or another run.")
        if low_score:
            notes.append(f"{len(low_score)} processed pages scored poorly during extraction.")
        if noisy:
            notes.append(f"{len(noisy)} pages were kept but flagged for layout noise or weak structure.")
        if report.pages_processed < max(1, len(state.pages) // 4):
            notes.append("Coverage looks low relative to discovered URLs; inspect diagnostics tree and state file.")
        return notes

    def _quality_warning_codes(self, document: ExtractedDocument) -> list[str]:
        warnings: list[str] = []
        extraction = document.extraction
        if extraction is None:
            return warnings
        metrics = extraction.metrics
        if extraction.score < 0.35:
            warnings.append("low-extraction-score")
        if metrics.link_line_ratio > 0.22 or metrics.boilerplate_ratio > 0.08:
            warnings.append("layout-noise")
        if metrics.repeated_line_ratio > 0.18:
            warnings.append("repeated-blocks")
        if metrics.malformed_ratio > 0.01:
            warnings.append("encoding-artifacts")
        if metrics.heading_count == 0 and metrics.word_count > 180:
            warnings.append("low-structure")
        return warnings

    def _build_discovered_tree_text(self, state: CrawlState) -> str:
        children: dict[str, list[str]] = {}
        roots: list[str] = []
        for url, page in state.pages.items():
            if page.parent_url:
                children.setdefault(page.parent_url, []).append(url)
            else:
                roots.append(url)
        for urls in children.values():
            urls.sort()
        roots.sort()
        lines = [
            "# Discovered Documentation Link Tree",
            "",
            f"- Language: {state.language}",
            f"- Source: {state.source_url}",
            "",
        ]

        def walk(root_url: str) -> None:
            stack = [(root_url, "")]
            while stack:
                url, prefix = stack.pop()
                page = state.pages.get(url)
                status = page.status if page is not None else "unknown"
                lines.append(f"{prefix}- {url} [{status}]")
                for child in reversed(children.get(url, [])):
                    stack.append((child, prefix + "  "))

        for root in roots:
            walk(root)
        lines.append("")
        return "\n".join(lines)
