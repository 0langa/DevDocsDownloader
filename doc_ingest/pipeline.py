from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import parse_qsl, urlparse

from .adaptive import AdaptiveRuntimeController
from .config import AppConfig
from .extractors.html import extract_html_links
from .extractors.dispatcher import detect_asset_type, extract_document
from .fetchers.browser import BrowserFetcher
from .fetchers.http import HttpFetcher
from .mergers.compiler import compile_language_markdown
from .models import CrawlMode, ExtractedDocument, LanguageEntry, LanguageRunReport, PageProcessResult, PlannedSource, RunSummary, UrlRecord
from .normalizers.markdown import normalize_document
from .parser import parse_language_file
from .planner.planner import CrawlPlanner
from .progress import CrawlProgressTracker
from .reporting.writer import write_reports
from .utils.filesystem import read_json, write_json, write_text
from .utils.urls import normalize_url
from .validators.markdown_validator import validate_markdown


LOGGER = logging.getLogger("doc_ingest")


class DiscoveryDocument:
    def __init__(self, *, title: str, final_url: str, links: list[str]) -> None:
        self.title = title
        self.final_url = final_url
        self.links = links


class DocumentationPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.http_fetcher = HttpFetcher(config)
        self.browser_fetcher = BrowserFetcher(config)
        self.planner = CrawlPlanner(config)
        self.adaptive_controller = AdaptiveRuntimeController(config)
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
        split_mode: bool = False,
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
        if self.config.crawl.smart_mode:
            concurrency = await self.adaptive_controller.get_language_concurrency()
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
                    split_mode=split_mode,
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
        split_mode: bool,
        progress_tracker: CrawlProgressTracker | None,
    ) -> LanguageRunReport:
        plan = self.planner.plan(language)
        if crawl_mode is not None:
            plan.crawl_mode = crawl_mode
        report = LanguageRunReport(language=language.name, slug=language.slug, source_url=str(language.source_url), strategy=plan.strategy)
        state_path = self.config.paths.state_dir / f"{language.slug}.json"
        output_path = self.config.paths.markdown_dir / f"{language.slug}.md"

        if validate_only:
            if output_path.exists():
                report.output_path = output_path
                report.validation = validate_markdown(language.name, output_path, self.config)
            else:
                report.failures.append("Output markdown file does not exist.")
            return report

        if dry_run:
            report.warnings.extend(plan.notes)
            return report

        if force_refresh and state_path.exists():
            state_path.unlink()

        state = read_json(state_path, {"processed": {}, "failed": {}})
        discovered_cache_path = self.config.paths.crawl_cache_dir / f"{language.slug}.json"
        discovered_tree_path = self.config.paths.crawl_cache_dir / f"{language.slug}.tree.txt"
        discovered_cache = read_json(discovered_cache_path, {"urls": {}, "roots": []})
        processed_docs: dict[str, ExtractedDocument] = {}
        processed_hashes: set[str] = set()
        processed_state_urls = set(state.get("processed", {}).keys())
        failed_state_urls = set(state.get("failed", {}).keys())
        queued_urls: set[str] = set()
        discovered_urls: dict[str, dict[str, str | int | None]] = discovered_cache.get("urls", {})
        queue: asyncio.Queue[UrlRecord | None] = asyncio.Queue(maxsize=self.config.crawl.max_queue_size_per_language)
        state_lock = asyncio.Lock()
        dirty_state = False
        dirty_discovery = False
        last_persist_at = time.monotonic()
        persist_every_seconds = 10.0
        persist_every_changes = 50
        pending_changes = 0

        async def update_queue_progress() -> None:
            if progress_tracker is not None:
                await progress_tracker.on_queue_size_changed(language.slug, queue.qsize())

        async def enqueue(record: UrlRecord) -> None:
            if record.normalized_url in queued_urls or record.normalized_url in processed_state_urls:
                return
            max_discovered_urls = self.config.crawl.max_discovered_urls_per_language
            if self.config.crawl.smart_mode:
                max_discovered_urls = await self.adaptive_controller.get_max_discovered()
            if len(discovered_urls) >= max_discovered_urls:
                await self.adaptive_controller.tune(queue_fill_ratio=queue.qsize() / max(1, self.config.crawl.max_queue_size_per_language), limit_hit=True)
                return
            queued_urls.add(record.normalized_url)
            discovered_urls.setdefault(
                record.normalized_url,
                {
                    "parent": record.parent_url,
                    "depth": record.depth,
                    "source": record.discovered_from,
                },
            )
            await queue.put(record)
            await update_queue_progress()

        for url in plan.start_urls:
            await enqueue(UrlRecord(url=url, normalized_url=normalize_url(url), depth=0))

        for url, meta in discovered_cache.get("urls", {}).items():
            normalized = normalize_url(url)
            if normalized not in processed_state_urls and normalized not in failed_state_urls:
                await enqueue(
                    UrlRecord(
                        url=normalized,
                        normalized_url=normalized,
                        depth=int(meta.get("depth", 1) or 1),
                        parent_url=meta.get("parent"),
                        discovered_from="cache",
                    )
                )

        report.pages_discovered = len(discovered_urls)

        async def persist_caches(force: bool = False) -> None:
            nonlocal dirty_state, dirty_discovery, last_persist_at, pending_changes
            if not force and not (dirty_state or dirty_discovery):
                return
            if not force and pending_changes < persist_every_changes and (time.monotonic() - last_persist_at) < persist_every_seconds:
                return
            write_json(state_path, state)
            roots = sorted(url for url, meta in discovered_urls.items() if not meta.get("parent"))
            write_json(discovered_cache_path, {"roots": roots, "urls": discovered_urls})
            write_text(discovered_tree_path, self._build_discovered_tree_text(discovered_urls, roots))
            dirty_state = False
            dirty_discovery = False
            pending_changes = 0
            last_persist_at = time.monotonic()

        async def discovery_worker() -> None:
            nonlocal report
            while True:
                max_pages = self.config.crawl.max_pages_per_language
                if self.config.crawl.smart_mode:
                    max_pages = await self.adaptive_controller.get_max_pages()
                if len(processed_docs) >= max_pages and not split_mode:
                    return
                record = await queue.get()
                await update_queue_progress()
                if record is None:
                    queue.task_done()
                    return

                try:
                    if record.normalized_url in state.get("processed", {}) or record.normalized_url in state.get("failed", {}):
                        continue

                    try:
                        document = await self._fetch_document_for_discovery(record, plan, progress_tracker)
                    except Exception as exc:
                        LOGGER.exception("Failed discovering %s", record.url)
                        async with state_lock:
                            state.setdefault("failed", {})[record.normalized_url] = str(exc)
                            discovered_urls.pop(record.normalized_url, None)
                            report.failures.append(f"{record.url}: {exc}")
                            dirty_state = True
                            dirty_discovery = True
                            pending_changes += 1
                            await persist_caches()
                        continue

                    new_links = self._discover_links(document, plan, record.depth)
                    if progress_tracker is not None:
                        await progress_tracker.on_links_found(language.slug, len(document.links))

                    async with state_lock:
                        added_links = 0
                        for link in new_links:
                            max_discovered_urls = self.config.crawl.max_discovered_urls_per_language
                            if self.config.crawl.smart_mode:
                                max_discovered_urls = await self.adaptive_controller.get_max_discovered()
                            if len(discovered_urls) >= max_discovered_urls:
                                await self.adaptive_controller.tune(queue_fill_ratio=queue.qsize() / max(1, self.config.crawl.max_queue_size_per_language), limit_hit=True)
                                break
                            if link.normalized_url not in discovered_urls:
                                discovered_urls[link.normalized_url] = {
                                    "parent": link.parent_url,
                                    "depth": link.depth,
                                    "source": link.discovered_from,
                                }
                                report.pages_discovered = max(report.pages_discovered, len(discovered_urls))
                                queued_urls.add(link.normalized_url)
                                added_links += 1
                                if not queue.full():
                                    await queue.put(link)

                        if progress_tracker is not None and added_links:
                            await progress_tracker.on_links_added(language.slug, added_links)
                            await update_queue_progress()

                        state.setdefault("processed", {})[record.normalized_url] = {
                            "title": document.title,
                            "hash": "discovered-only",
                            "asset_type": "html",
                            "phase": "discovered",
                        }
                        dirty_state = True
                        dirty_discovery = True
                        pending_changes += 1 + added_links
                        await persist_caches()
                        if self.config.crawl.smart_mode:
                            await self.adaptive_controller.tune(queue_fill_ratio=queue.qsize() / max(1, self.config.crawl.max_queue_size_per_language))
                finally:
                    queue.task_done()
                    await update_queue_progress()

        async def processing_phase() -> None:
            discovered_records = [
                UrlRecord(
                    url=url,
                    normalized_url=url,
                    depth=int(meta.get("depth", 0) or 0),
                    parent_url=meta.get("parent"),
                    discovered_from=str(meta.get("source") or "splitmode"),
                )
                for url, meta in discovered_urls.items()
            ]

            semaphore = asyncio.Semaphore(max(1, self.config.crawl.max_concurrency))

            async def process_record(record: UrlRecord) -> None:
                nonlocal report
                async with semaphore:
                    max_pages = self.config.crawl.max_pages_per_language
                    if self.config.crawl.smart_mode:
                        max_pages = await self.adaptive_controller.get_max_pages()
                    if len(processed_docs) >= max_pages:
                        await self.adaptive_controller.tune(limit_hit=True)
                        return
                    try:
                        page_result = await self._process_url(record, plan, progress_tracker)
                    except Exception as exc:
                        LOGGER.exception("Failed processing %s", record.url)
                        async with state_lock:
                            state.setdefault("failed", {})[record.normalized_url] = str(exc)
                            report.failures.append(f"{record.url}: {exc}")
                            dirty_state = True
                            pending_changes += 1
                            await persist_caches()
                        return

                    if page_result.status != "processed" or not page_result.document:
                        async with state_lock:
                            state.setdefault("failed", {})[record.normalized_url] = page_result.message
                            report.failures.append(f"{record.url}: {page_result.message}")
                            dirty_state = True
                            pending_changes += 1
                            await persist_caches()
                        return

                    document = normalize_document(page_result.document)
                    async with state_lock:
                        if document.content_hash in processed_hashes:
                            return
                        processed_docs[record.normalized_url] = document
                        processed_hashes.add(document.content_hash)
                        state.setdefault("processed", {})[record.normalized_url] = {
                            "title": document.title,
                            "hash": document.content_hash,
                            "asset_type": document.asset_type,
                            "phase": "processed",
                        }
                        report.pages_processed += 1
                        if document.asset_type != "html":
                            report.assets_processed += 1
                        dirty_state = True
                        pending_changes += 1
                        await persist_caches()
                        if self.config.crawl.smart_mode:
                            await self.adaptive_controller.tune()

            await asyncio.gather(*[process_record(record) for record in discovered_records])

        worker_count = max(1, self.config.crawl.max_concurrency)
        if self.config.crawl.smart_mode:
            worker_count = await self.adaptive_controller.get_page_concurrency()
        workers = [asyncio.create_task(discovery_worker()) for _ in range(worker_count)]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

        if split_mode:
            state["processed"] = {
                url: meta
                for url, meta in state.get("processed", {}).items()
                if meta.get("phase") != "discovered"
            }
            dirty_state = True
            pending_changes += 1
            await persist_caches(force=True)
            await processing_phase()

        await persist_caches(force=True)

        if not processed_docs:
            report.failures.append("No documents were processed.")
            report.suspected_incompleteness = True
            if progress_tracker is not None:
                await progress_tracker.on_language_complete(language.slug, report)
            return report

        report.output_path = compile_language_markdown(language, list(processed_docs.values()), output_path)
        report.validation = validate_markdown(language.name, output_path, self.config)
        report.suspected_incompleteness = bool(report.validation and report.validation.score < 0.7)
        if progress_tracker is not None:
            await progress_tracker.on_language_complete(language.slug, report)
        return report

    async def _fetch_document_for_discovery(
        self,
        record: UrlRecord,
        plan: PlannedSource,
        progress_tracker: CrawlProgressTracker | None,
    ) -> DiscoveryDocument:
        cache_dir = self.config.paths.cache_dir / plan.language.slug
        try:
            fetch_result = await self.http_fetcher.fetch(record.normalized_url, cache_dir)
        except Exception:
            if progress_tracker is not None:
                await progress_tracker.on_request_failure(plan.language.slug)
            raise

        if progress_tracker is not None:
            await progress_tracker.on_fetch_complete(
                plan.language.slug,
                fetch_result.status_code,
                fetch_result.history_status_codes,
                fetch_result.method,
            )

        if fetch_result.status_code >= 400:
            raise RuntimeError(f"HTTP {fetch_result.status_code}")

        asset_type = detect_asset_type(fetch_result)
        if asset_type == "unknown" and self.config.crawl.browser_enabled:
            fetch_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
            asset_type = detect_asset_type(fetch_result)

        if asset_type != "html":
            return DiscoveryDocument(title=fetch_result.final_url, final_url=fetch_result.final_url, links=[])

        lightweight = extract_html_links(fetch_result)
        return DiscoveryDocument(title=lightweight.title, final_url=lightweight.final_url, links=lightweight.links)

    async def _process_url(
        self,
        record: UrlRecord,
        plan: PlannedSource,
        progress_tracker: CrawlProgressTracker | None,
    ) -> PageProcessResult:
        cache_dir = self.config.paths.cache_dir / plan.language.slug
        try:
            fetch_result = await self.http_fetcher.fetch(record.normalized_url, cache_dir)
        except Exception:
            if progress_tracker is not None:
                await progress_tracker.on_request_failure(plan.language.slug)
            raise

        if progress_tracker is not None:
            await progress_tracker.on_fetch_complete(
                plan.language.slug,
                fetch_result.status_code,
                fetch_result.history_status_codes,
                fetch_result.method,
            )

        if fetch_result.status_code >= 400:
            return PageProcessResult(
                url=record.normalized_url,
                status="failed",
                message=f"HTTP {fetch_result.status_code}",
            )

        asset_type = detect_asset_type(fetch_result)
        if asset_type == "unknown" and self.config.crawl.browser_enabled:
            fetch_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)

        document = extract_document(fetch_result)
        if document.word_count < 40 and self.config.crawl.browser_enabled and fetch_result.method != "browser":
            try:
                browser_result = await self.browser_fetcher.fetch(record.normalized_url, cache_dir)
                browser_document = extract_document(browser_result)
                if browser_document.word_count > document.word_count:
                    document = browser_document
            except Exception:
                LOGGER.debug("Browser fallback failed for %s", record.normalized_url, exc_info=True)

        return PageProcessResult(url=record.normalized_url, status="processed", document=document)

    def _discover_links(self, document: ExtractedDocument, plan: PlannedSource, depth: int) -> list[UrlRecord]:
        if depth >= plan.max_depth:
            return []
        discovered: list[UrlRecord] = []

        for link in document.links:
            normalized = normalize_url(link)
            parsed = urlparse(normalized)
            if parsed.netloc not in plan.allowed_domains:
                continue
            if plan.allowed_path_prefixes and not any(
                parsed.path.startswith(p) for p in plan.allowed_path_prefixes
            ):
                continue
            if not self._is_preferred_locale_url(normalized):
                continue
            if not self._is_relevant_doc_link(normalized):
                continue
            if plan.crawl_mode == "important" and not self._is_important_link(normalized):
                continue
            discovered.append(UrlRecord(url=link, normalized_url=normalized, depth=depth + 1, parent_url=document.final_url))

        return list({item.normalized_url: item for item in discovered}.values())

    def _is_relevant_doc_link(self, url: str) -> bool:
        lowered = url.lower()
        negative_tokens = ["blog", "news", "press", "careers", "pricing", "contact", "privacy", "terms", "login", "signup"]
        if any(token in lowered for token in negative_tokens):
            return False
        positive_tokens = ["doc", "reference", "manual", "guide", "tutorial", "library", "spec", "language", "stdlib", "book", "learn", "chapter"]
        return any(token in lowered for token in positive_tokens) or lowered.endswith((".html", "/", ".md", ".pdf", ".txt", ".docx"))

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

    def _build_discovered_tree_text(self, discovered_urls: dict[str, dict[str, str | int | None]], roots: list[str]) -> str:
        children: dict[str, list[str]] = {}
        for url, meta in discovered_urls.items():
            parent = meta.get("parent")
            if parent:
                children.setdefault(str(parent), []).append(url)

        for node_children in children.values():
            node_children.sort()

        lines = ["# Discovered Documentation Link Tree", ""]

        def walk(url: str, prefix: str = "") -> None:
            meta = discovered_urls.get(url, {})
            lines.append(f"{prefix}- {url} (depth={meta.get('depth', '?')})")
            for child in children.get(url, []):
                walk(child, prefix + "  ")

        for root in roots:
            walk(root)
        orphaned = sorted(url for url in discovered_urls if url not in roots and all(url not in child_list for child_list in children.values()))
        if orphaned:
            lines.extend(["", "# Orphaned / Cached-only URLs", ""])
            for url in orphaned:
                lines.append(f"- {url}")
        lines.append("")
        return "\n".join(lines)