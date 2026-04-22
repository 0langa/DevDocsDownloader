from __future__ import annotations

import asyncio
import os
import logging
import random
import time
from bisect import bisect_left
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import psutil
try:
    import msgpack
except ImportError:  # pragma: no cover
    msgpack = None

from .adaptive import AdaptiveRuntimeController
from .adapters import select_adapter
from .config import AppConfig
from .discovery import DiscoveryHelper, RobotsCache
from .extractors.dispatcher import detect_asset_type, extract_document
from .extractors.html import extract_html_links
from .fetchers.browser import BrowserFetcher
from .fetchers.http import HttpFetcher
from .mergers.compiler import compile_language_markdown, compile_language_markdown_streaming
from .models import CrawlMode, CrawlState, ExtractedDocument, FetchResult, LanguageEntry, LanguageRunReport, PageState, PlannedSource, RunSummary, UrlRecord
from .normalizers.markdown import normalize_document
from .parser import parse_language_file
from .planner.planner import CrawlPlanner
from .progress import CrawlProgressTracker
from .reporting.writer import write_reports
from .state import CrawlStateStore
from .utils.filesystem import write_text
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
        self._process_pool: ProcessPoolExecutor | None = None
        if self.config.crawl.extract_executor == "process":
            workers = self.config.crawl.extract_process_workers or max(1, (os.cpu_count() or 2) // 2)
            self._process_pool = ProcessPoolExecutor(max_workers=workers)
        self.http_fetcher.set_adaptive_controller(self.adaptive_controller)

    async def close(self) -> None:
        await self.http_fetcher.close()
        await self.browser_fetcher.close()
        await self.robots.close()
        if self._process_pool is not None:
            self._process_pool.shutdown(wait=True, cancel_futures=True)
            self._process_pool = None

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

        helper = DiscoveryHelper(self.config, adapter, plan)
        queue: asyncio.Queue[UrlRecord | None] = asyncio.Queue(maxsize=max(0, self.config.crawl.max_queue_size_per_language))
        extraction_workers_max = max(1, min(self.config.crawl.max_concurrency, self.config.crawl.max_extraction_workers))
        extraction_queue: asyncio.Queue[tuple[UrlRecord, FetchResult, str, PageState] | None] = asyncio.Queue(
            maxsize=max(1, self.config.crawl.max_pending_extractions_per_language)
        )
        queued_urls: set[str] = set()
        pending_document_cache: dict[str, ExtractedDocument] = {}
        in_memory_documents: OrderedDict[str, ExtractedDocument] = OrderedDict()

        processed_hashes = {
            page.content_hash
            for page in state.pages.values()
            if page.status == "processed" and page.content_hash
        }
        hash_to_url = {
            page.content_hash: url
            for url, page in state.pages.items()
            if page.status == "processed" and page.content_hash
        }
        processed_count = sum(1 for page in state.pages.values() if page.status == "processed")
        report.pages_processed = processed_count

        stage_totals: dict[str, dict[str, float | int]] = {
            "fetch": {"duration_ms_total": 0.0, "items_total": 0, "failures_total": 0},
            "discover": {"duration_ms_total": 0.0, "items_total": 0, "failures_total": 0},
            "extract": {"duration_ms_total": 0.0, "items_total": 0, "failures_total": 0},
            "persist": {"duration_ms_total": 0.0, "items_total": 0, "failures_total": 0},
        }
        queue_stats_runtime = {
            "discover": {"current": 0, "sum": 0.0, "samples": 0, "hwm": 0},
            "extract": {"current": 0, "sum": 0.0, "samples": 0, "hwm": 0},
        }
        latency_bins = sorted(set(value for value in self.config.crawl.extract_latency_bins_ms if value > 0))
        latency_histogram = {f"<= {bound}ms": 0 for bound in latency_bins}
        latency_histogram[f"> {latency_bins[-1]}ms" if latency_bins else "> 0ms"] = 0
        latency_samples: list[float] = []
        latency_count = 0
        cpu_sum = 0.0
        cpu_samples = 0
        process = psutil.Process()
        rss_peak_mb = process.memory_info().rss / (1024 * 1024)
        extract_busy_seconds = 0.0
        extract_idle_seconds = 0.0
        desired_extraction_workers = max(
            1,
            min(
                extraction_workers_max,
                max(self.config.crawl.extract_scale_min_workers, extraction_workers_max),
            ),
        )
        scale_events = 0
        last_scale_at = 0.0

        dirty = False
        pending_changes = 0
        last_persist_at = time.monotonic()
        last_diagnostics_at = 0.0
        last_queue_progress_at = 0.0
        last_queue_sample_at = 0.0
        persist_lock = asyncio.Lock()

        def _record_stage(stage_name: str, started_at: float, *, success: bool) -> None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            stats = stage_totals[stage_name]
            stats["duration_ms_total"] = float(stats["duration_ms_total"]) + elapsed_ms
            if success:
                stats["items_total"] = int(stats["items_total"]) + 1
            else:
                stats["failures_total"] = int(stats["failures_total"]) + 1

        def _sample_queue_metrics() -> None:
            discover_size = queue.qsize()
            extract_size = extraction_queue.qsize()
            for name, size in (("discover", discover_size), ("extract", extract_size)):
                runtime = queue_stats_runtime[name]
                runtime["current"] = size
                runtime["sum"] = float(runtime["sum"]) + size
                runtime["samples"] = int(runtime["samples"]) + 1
                runtime["hwm"] = max(int(runtime["hwm"]), size)

        def _record_latency_ms(latency_ms: float) -> None:
            nonlocal latency_count
            latency_count += 1
            if latency_bins:
                idx = bisect_left(latency_bins, latency_ms)
                if idx >= len(latency_bins):
                    latency_histogram[f"> {latency_bins[-1]}ms"] += 1
                else:
                    latency_histogram[f"<= {latency_bins[idx]}ms"] += 1
            else:
                latency_histogram["> 0ms"] += 1

            max_sample = max(1, self.config.crawl.extract_latency_sample_size)
            if len(latency_samples) < max_sample:
                latency_samples.append(latency_ms)
                return
            replace_at = random.randint(0, latency_count - 1)
            if replace_at < max_sample:
                latency_samples[replace_at] = latency_ms

        def _remember_document(normalized_url: str, document: ExtractedDocument) -> None:
            in_memory_documents[normalized_url] = document
            in_memory_documents.move_to_end(normalized_url)
            max_items = max(1, self.config.crawl.max_in_memory_documents)
            while len(in_memory_documents) > max_items:
                in_memory_documents.popitem(last=False)

        def _finalize_performance_metrics() -> None:
            perf = report.performance
            for stage_name, model in (
                ("fetch", perf.fetch),
                ("discover", perf.discover),
                ("extract", perf.extract),
                ("persist", perf.persist),
            ):
                runtime = stage_totals[stage_name]
                model.duration_ms_total = float(runtime["duration_ms_total"])
                model.items_total = int(runtime["items_total"])
                model.failures_total = int(runtime["failures_total"])
                duration_seconds = model.duration_ms_total / 1000.0
                model.throughput_items_per_sec = (model.items_total / duration_seconds) if duration_seconds > 0 else 0.0

            for queue_name, model in (("discover", perf.queue_discover), ("extract", perf.queue_extract)):
                runtime = queue_stats_runtime[queue_name]
                model.depth_current = int(runtime["current"])
                samples = int(runtime["samples"])
                model.depth_avg = (float(runtime["sum"]) / samples) if samples > 0 else 0.0
                model.depth_hwm = int(runtime["hwm"])

            latency = perf.extraction_latency
            latency.count = latency_count
            latency.histogram = dict(latency_histogram)
            if latency_samples:
                ordered = sorted(latency_samples)

                def _pct(p: float) -> float:
                    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * p))))
                    return float(ordered[rank])

                latency.p50_ms = _pct(0.50)
                latency.p90_ms = _pct(0.90)
                latency.p95_ms = _pct(0.95)
                latency.p99_ms = _pct(0.99)

            cache = perf.cache
            fetch_total = cache.fetch_hits + cache.fetch_misses
            normalized_total = cache.normalized_hits + cache.normalized_misses
            cache.fetch_hit_rate = (cache.fetch_hits / fetch_total) if fetch_total > 0 else 0.0
            cache.normalized_hit_rate = (cache.normalized_hits / normalized_total) if normalized_total > 0 else 0.0

            workers = perf.workers
            workers.discover_workers = max(1, self.config.crawl.max_concurrency)
            workers.extraction_workers_max = extraction_workers_max
            workers.extraction_workers_current = desired_extraction_workers
            workers.extraction_scale_events_total = scale_events
            workers.extraction_busy_seconds = extract_busy_seconds
            workers.extraction_idle_seconds = extract_idle_seconds
            total_worker_time = extract_busy_seconds + extract_idle_seconds
            workers.extraction_busy_ratio = (extract_busy_seconds / total_worker_time) if total_worker_time > 0 else 0.0

            system = perf.system
            system.cpu_utilization_avg_pct = (cpu_sum / cpu_samples) if cpu_samples > 0 else 0.0
            system.resident_memory_peak_mb = rss_peak_mb

        async def update_queue_progress(*, force: bool = False) -> None:
            nonlocal last_queue_progress_at, last_queue_sample_at
            now = time.monotonic()
            sampling_interval = max(0.05, self.config.crawl.queue_metrics_sampling_ms / 1000.0)
            if force or (now - last_queue_sample_at) >= sampling_interval:
                _sample_queue_metrics()
                last_queue_sample_at = now

            if progress_tracker is not None:
                if not force and (now - last_queue_progress_at) < 0.15:
                    return
                last_queue_progress_at = now
                await progress_tracker.on_queue_size_changed(language.slug, queue.qsize() + extraction_queue.qsize())

        async def persist_state(force: bool = False) -> None:
            nonlocal dirty, pending_changes, last_persist_at, last_diagnostics_at
            stage_started = time.perf_counter()
            try:
                async with persist_lock:
                    if not dirty and not force and not pending_document_cache:
                        _record_stage("persist", stage_started, success=True)
                        return
                    now = time.monotonic()
                    if (
                        not force
                        and pending_changes < self.config.crawl.persist_every_changes
                        and (now - last_persist_at) < self.config.crawl.persist_every_seconds
                    ):
                        _record_stage("persist", stage_started, success=True)
                        return
                    if pending_document_cache:
                        cached_batch = pending_document_cache.copy()
                        pending_document_cache.clear()
                        bytes_written, serialize_ms = await asyncio.to_thread(
                            self._persist_document_cache_batch,
                            language.slug,
                            cached_batch,
                        )
                        report.performance.cache.normalized_bytes_written += bytes_written
                        report.performance.cache.normalized_serialize_ms_total += serialize_ms
                    await asyncio.to_thread(state_store.save, state)
                    should_write_tree = force or ((now - last_diagnostics_at) >= self.config.crawl.persist_diagnostics_every_seconds)
                    if should_write_tree:
                        tree = self._build_discovered_tree_text(state)
                        await asyncio.to_thread(write_text, diagnostics_path, tree)
                        last_diagnostics_at = now
                    dirty = False
                    pending_changes = 0
                    last_persist_at = now
            except Exception:
                _record_stage("persist", stage_started, success=False)
                raise
            _record_stage("persist", stage_started, success=True)

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

        async def _fast_discover(fetch_result: FetchResult) -> DiscoveryDocument:
            if detect_asset_type(fetch_result) != "html":
                return DiscoveryDocument(title=fetch_result.final_url, final_url=fetch_result.final_url, links=[], breadcrumbs=[])
            doc = await asyncio.to_thread(extract_html_links, fetch_result, adapter=adapter)
            return DiscoveryDocument(title=doc.title, final_url=doc.final_url, links=doc.links, breadcrumbs=[])

        async def _extract_via_executor(fetch_result: FetchResult) -> ExtractedDocument:
            kwargs = {
                "preferred_extractors": plan.preferred_extractors,
                "adapter": adapter,
                "docling_timeout_seconds": self.config.crawl.docling_timeout_seconds,
            }
            asset_type = detect_asset_type(fetch_result)
            executor_mode = (self.config.crawl.extract_executor or "thread").lower()
            use_process = (
                executor_mode == "process"
                or (executor_mode == "auto" and asset_type in {"pdf", "docx", "text", "markdown"})
            )
            if use_process and self._process_pool is not None and asset_type != "html":
                loop = asyncio.get_running_loop()
                fn = partial(extract_document, fetch_result, **kwargs)
                try:
                    return await loop.run_in_executor(self._process_pool, fn)
                except Exception:
                    LOGGER.debug("Process extraction failed for %s, falling back to thread executor.", fetch_result.final_url, exc_info=True)
            return await asyncio.to_thread(extract_document, fetch_result, **kwargs)

        async def _full_extract_and_store(
            record: UrlRecord,
            fetch_result: FetchResult,
            normalized: str,
            page: PageState,
        ) -> None:
            nonlocal dirty, pending_changes, processed_count
            stage_started = time.perf_counter()
            extraction_started = time.perf_counter()
            try:
                document = await _extract_via_executor(fetch_result)
                if adapter.should_retry_with_browser(
                    asset_type=detect_asset_type(fetch_result),
                    fetch_method=fetch_result.method,
                    word_count=document.word_count,
                    extraction_score=document.extraction.score if document.extraction else None,
                ) and self.config.crawl.browser_enabled:
                    try:
                        cache_dir = self.config.paths.cache_dir / plan.language.slug
                        browser_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
                        browser_doc = await _extract_via_executor(browser_result)
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
                    _record_latency_ms((time.perf_counter() - extraction_started) * 1000.0)
                    _record_stage("extract", stage_started, success=True)
                    await persist_state()
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
                    page.duplicate_of = hash_to_url.get(document.content_hash)
                    page.warning_codes.append("duplicate-content")
                    report.pages_deduplicated += 1
                    report.pages_skipped += 1
                else:
                    page.status = "processed"
                    page.content_hash = document.content_hash
                    processed_hashes.add(document.content_hash)
                    hash_to_url[document.content_hash] = normalized
                    processed_count += 1
                    report.pages_processed = processed_count
                    report.assets_processed += 1 if document.asset_type != "html" else 0
                    report.extractor_choices[page.extractor or "unknown"] = report.extractor_choices.get(page.extractor or "unknown", 0) + 1
                    pending_document_cache[normalized] = document
                    _remember_document(normalized, document)

                dirty = True
                pending_changes += 1
                _record_latency_ms((time.perf_counter() - extraction_started) * 1000.0)
                _record_stage("extract", stage_started, success=True)
                await persist_state()
            except Exception:
                _record_latency_ms((time.perf_counter() - extraction_started) * 1000.0)
                _record_stage("extract", stage_started, success=False)
                LOGGER.exception("Extraction failed for %s", record.url)
                if page.status not in {"processed", "skipped"}:
                    page.status = "failed"
                    report.pages_failed += 1
                    dirty = True
                    pending_changes += 1
                    await persist_state()

        async def discovery_worker() -> None:
            nonlocal dirty, pending_changes
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
                        continue
                    page.attempts += 1
                    report.pages_queued = max(report.pages_queued, len(state.pages))

                    cache_dir = self.config.paths.cache_dir / plan.language.slug
                    fetch_started = time.perf_counter()
                    try:
                        fetch_result = await self.http_fetcher.fetch(record.normalized_url, cache_dir)
                        if fetch_result.method == "cache":
                            report.performance.cache.fetch_hits += 1
                        else:
                            report.performance.cache.fetch_misses += 1
                        if progress_tracker is not None:
                            await progress_tracker.on_fetch_complete(plan.language.slug, fetch_result.status_code, fetch_result.history_status_codes, fetch_result.method)
                        if fetch_result.status_code >= 400:
                            raise RuntimeError(f"HTTP {fetch_result.status_code}")
                        if detect_asset_type(fetch_result) == "unknown" and self.config.crawl.browser_enabled:
                            fetch_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
                            report.performance.cache.fetch_misses += 1
                        _record_stage("fetch", fetch_started, success=True)
                    except Exception as exc:
                        _record_stage("fetch", fetch_started, success=False)
                        if progress_tracker is not None:
                            await progress_tracker.on_request_failure(plan.language.slug)
                        LOGGER.exception("Failed fetching %s", record.url)
                        page.status = "failed"
                        page.last_error = str(exc)
                        report.pages_failed += 1
                        report.failures.append(f"{record.url}: {exc}")
                        dirty = True
                        pending_changes += 1
                        await persist_state()
                        continue

                    report.pages_fetched += 1

                    discover_started = time.perf_counter()
                    discovery_doc = await _fast_discover(fetch_result)
                    page.title = discovery_doc.title

                    discovered_links = self._discover_links(discovery_doc, helper, plan, record.depth)
                    if progress_tracker is not None:
                        await progress_tracker.on_links_found(language.slug, len(discovery_doc.links))
                        await progress_tracker.on_links_added(language.slug, len(discovered_links))
                    for link in discovered_links:
                        await enqueue(link)
                    _record_stage("discover", discover_started, success=True)

                    await extraction_queue.put((record, fetch_result, normalized, page))
                    await persist_state()
                finally:
                    queue.task_done()
                    await update_queue_progress()

        async def extraction_worker(worker_id: int) -> None:
            nonlocal extract_busy_seconds, extract_idle_seconds
            while True:
                while worker_id >= desired_extraction_workers:
                    idle_started = time.perf_counter()
                    await asyncio.sleep(0.2)
                    extract_idle_seconds += time.perf_counter() - idle_started

                idle_started = time.perf_counter()
                item = await extraction_queue.get()
                extract_idle_seconds += time.perf_counter() - idle_started
                await update_queue_progress()
                if item is None:
                    extraction_queue.task_done()
                    return
                record, fetch_result, normalized, page = item
                busy_started = time.perf_counter()
                try:
                    await _full_extract_and_store(record, fetch_result, normalized, page)
                finally:
                    extract_busy_seconds += time.perf_counter() - busy_started
                    extraction_queue.task_done()
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
        extraction_workers = [asyncio.create_task(extraction_worker(index)) for index in range(extraction_workers_max)]

        async def _tune_loop() -> None:
            nonlocal cpu_sum, cpu_samples, rss_peak_mb, desired_extraction_workers, scale_events, last_scale_at
            psutil.cpu_percent(interval=None)
            while True:
                await asyncio.sleep(5.0)
                await update_queue_progress(force=True)
                discovery_fill_ratio = queue.qsize() / max(1, self.config.crawl.max_queue_size_per_language or max(1, queue.qsize()))
                extraction_fill_ratio = extraction_queue.qsize() / max(1, self.config.crawl.max_pending_extractions_per_language)
                queue_fill_ratio = max(discovery_fill_ratio, extraction_fill_ratio)
                await self.adaptive_controller.tune(
                    queue_fill_ratio=queue_fill_ratio,
                    limit_hit=len(state.pages) >= self.config.crawl.max_discovered_urls_per_language,
                )

                cpu_pct = psutil.cpu_percent(interval=None)
                cpu_sum += cpu_pct
                cpu_samples += 1
                rss_peak_mb = max(rss_peak_mb, process.memory_info().rss / (1024 * 1024))

                if not self.config.crawl.adaptive_extraction_workers:
                    continue
                now = time.monotonic()
                if (now - last_scale_at) < self.config.crawl.extract_scale_cooldown_seconds:
                    continue

                min_workers = max(1, min(extraction_workers_max, self.config.crawl.extract_scale_min_workers))
                target_cpu = self.config.crawl.extract_target_cpu_percent
                if (
                    extraction_fill_ratio >= self.config.crawl.extract_scale_up_queue_fill_ratio
                    and cpu_pct < (target_cpu - 8.0)
                    and desired_extraction_workers < extraction_workers_max
                ):
                    desired_extraction_workers += 1
                    scale_events += 1
                    last_scale_at = now
                elif (
                    (
                        extraction_fill_ratio <= self.config.crawl.extract_scale_down_queue_fill_ratio
                        and cpu_pct > (target_cpu + 5.0)
                    )
                    or cpu_pct > 92.0
                ) and desired_extraction_workers > min_workers:
                    desired_extraction_workers -= 1
                    scale_events += 1
                    last_scale_at = now

        tune_task = asyncio.create_task(_tune_loop())
        try:
            await queue.join()
        finally:
            tune_task.cancel()
            try:
                await tune_task
            except asyncio.CancelledError:
                pass

        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers, return_exceptions=True)
        await extraction_queue.join()
        for _ in extraction_workers:
            await extraction_queue.put(None)
        await asyncio.gather(*extraction_workers, return_exceptions=True)
        await update_queue_progress(force=True)

        state.compiled = False
        await persist_state(force=True)

        if processed_count <= 0:
            report.failures.append("No documents were processed.")
            report.suspected_incompleteness = True
            _finalize_performance_metrics()
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language.slug, report)
            return report

        report.pages_discovered = len(state.pages)
        report.coverage_notes.extend(self._coverage_notes(state, report, plan))
        if self.config.crawl.compile_streaming:
            documents_iter = self._iter_compilation_documents(
                slug=language.slug,
                state=state,
                adapter=adapter,
                in_memory_documents=in_memory_documents,
                report=report,
            )
            report.output_path = compile_language_markdown_streaming(
                language,
                documents_iter,
                output_path,
                state=state,
                coverage_notes=report.coverage_notes,
                adapter=adapter,
            )
        else:
            documents = list(
                self._iter_compilation_documents(
                    slug=language.slug,
                    state=state,
                    adapter=adapter,
                    in_memory_documents=in_memory_documents,
                    report=report,
                )
            )
            report.output_path = compile_language_markdown(
                language,
                documents,
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
        _finalize_performance_metrics()
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

    def _persist_document_cache_batch(self, slug: str, documents: dict[str, ExtractedDocument]) -> tuple[int, float]:
        cache_dir = self.config.paths.cache_dir / slug / "normalized"
        cache_dir.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        serialize_ms_total = 0.0
        for normalized_url, document in documents.items():
            started = time.perf_counter()
            payload, suffix = self._serialize_document_cache_payload(document)
            serialize_ms_total += (time.perf_counter() - started) * 1000.0
            cache_path = cache_dir / f"{stable_hash(normalized_url)}{suffix}"
            temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
            temp_path.write_bytes(payload)
            temp_path.replace(cache_path)
            bytes_written += len(payload)
        return bytes_written, serialize_ms_total

    def _serialize_document_cache_payload(self, document: ExtractedDocument) -> tuple[bytes, str]:
        cache_format = (self.config.crawl.normalized_cache_format or "json").lower()
        payload = document.model_dump(mode="json")
        if cache_format == "msgpack" and msgpack is not None:
            return msgpack.packb(payload, use_bin_type=True), ".msgpack"
        if cache_format == "json_compact":
            try:
                import orjson

                return orjson.dumps(payload), ".jsonc"
            except Exception:
                pass
        try:
            import orjson

            return orjson.dumps(payload, option=orjson.OPT_INDENT_2), ".json"
        except Exception:
            import json

            return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), ".json"

    def _load_cached_document(self, slug: str, normalized_url: str) -> tuple[ExtractedDocument | None, float]:
        cache_dir = self.config.paths.cache_dir / slug / "normalized"
        hashed = stable_hash(normalized_url)
        lookup_order = []
        cache_format = (self.config.crawl.normalized_cache_format or "json").lower()
        if cache_format == "msgpack":
            lookup_order = [".msgpack", ".jsonc", ".json"]
        elif cache_format == "json_compact":
            lookup_order = [".jsonc", ".json", ".msgpack"]
        else:
            lookup_order = [".json", ".jsonc", ".msgpack"]

        for suffix in lookup_order:
            cache_path = cache_dir / f"{hashed}{suffix}"
            if not cache_path.exists():
                continue
            started = time.perf_counter()
            try:
                payload = cache_path.read_bytes()
                if suffix == ".msgpack":
                    if msgpack is None:
                        continue
                    data = msgpack.unpackb(payload, raw=False)
                elif suffix == ".jsonc":
                    try:
                        import orjson

                        data = orjson.loads(payload)
                    except Exception:
                        import json

                        data = json.loads(payload.decode("utf-8"))
                else:
                    try:
                        import orjson

                        data = orjson.loads(payload)
                    except Exception:
                        import json

                        data = json.loads(payload.decode("utf-8"))
                document = ExtractedDocument.model_validate(data)
                return document, (time.perf_counter() - started) * 1000.0
            except Exception:
                LOGGER.debug("Failed to load cached document %s", cache_path, exc_info=True)
                return None, (time.perf_counter() - started) * 1000.0
        return None, 0.0

    def _ordered_processed_urls(self, state: CrawlState, adapter) -> list[str]:
        processed = [(url, page) for url, page in state.pages.items() if page.status == "processed"]

        def sort_key(item: tuple[str, PageState]) -> tuple:
            url, page = item
            breadcrumbs = page.metadata.get("breadcrumbs", []) if isinstance(page.metadata, dict) else []
            title = page.title or url
            order_hint = adapter.order_hint(url, title, breadcrumbs) if adapter is not None else (page.source_order_hint or "")
            return (
                page.depth,
                adapter.page_priority(url, title, breadcrumbs) if adapter is not None else 999,
                "/".join(str(value).lower() for value in breadcrumbs),
                page.parent_url or "",
                order_hint,
                title.lower(),
                url,
            )

        processed.sort(key=sort_key)
        return [url for url, _page in processed]

    def _iter_compilation_documents(
        self,
        *,
        slug: str,
        state: CrawlState,
        adapter,
        in_memory_documents: OrderedDict[str, ExtractedDocument],
        report: LanguageRunReport,
    ):
        max_items = max(1, self.config.crawl.max_in_memory_documents)
        for normalized_url in self._ordered_processed_urls(state, adapter):
            document = in_memory_documents.get(normalized_url)
            if document is not None:
                in_memory_documents.move_to_end(normalized_url)
                report.performance.cache.normalized_hits += 1
                yield document
                continue

            cached_document, deserialize_ms = self._load_cached_document(slug, normalized_url)
            report.performance.cache.normalized_deserialize_ms_total += deserialize_ms
            if cached_document is None:
                report.performance.cache.normalized_misses += 1
                continue
            report.performance.cache.normalized_hits += 1
            in_memory_documents[normalized_url] = cached_document
            in_memory_documents.move_to_end(normalized_url)
            while len(in_memory_documents) > max_items:
                in_memory_documents.popitem(last=False)
            yield cached_document

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
