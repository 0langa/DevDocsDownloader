# Documentation Crawler — Session Log

**Date:** 2026-04-20  
**Project:** `c:\Users\juliu\Documents\AI text stuff\Documentations Coding`

---

## Session Goals

1. Improve startup/configuration UX — replace 10-flag CLI with guided Q&A wizard
2. Remove `--splitmode` and `--smart` flags
3. Fix CPU usage issues
4. General performance pass

---

## Bugs Fixed (Prior Session — 15 total)

| # | File | Issue |
|---|---|---|
| 1 | `pipeline.py` | Queue deadlock when cache exists — workers started after enqueue loop |
| 2 | `pipeline.py` | Non-split mode never extracted content — `processed_docs` always empty |
| 3 | `pipeline.py` | Blocking disk I/O inside async state lock |
| 4 | `progress.py` | Rich markup injection in log messages |
| 5 | `planner/planner.py` | Silent failure loading `doc_path_overrides.json` |
| 6 | `pipeline.py` | `asyncio.gather()` without `return_exceptions=True` |
| 7 | `pipeline.py` | `_build_discovered_tree_text` unbounded recursion |
| 8 | `progress.py` | `emit_log()` not async-safe relative to Live refresh |
| 9 | `fetchers/http.py` | `_host_state_locks` and `_host_next_allowed_at` grow unbounded |
| 10 | `pipeline.py` | `asyncio.gather` for `process_record` without `return_exceptions=True` |
| 11 | `pipeline.py` | Worker max_pages check against always-empty `processed_docs` |
| 12 | `cli.py` | `logging.basicConfig()` called after pipeline creation |
| 13 | `cli.py` | `validate()` command calls `run()` directly |
| 14 | `config.py` | `max_queue_size_per_language` (1500) mismatched with `max_discovered` (5000) |
| 15 | `pipeline.py` | Type annotation mismatch in `_discover_links` |

---

## This Session — Changes Made

### 1. CLI Wizard (`doc_ingest/cli.py`) — Complete rewrite

- Added `invoke_without_command=True, no_args_is_help=False` to Typer app
- Added `@app.callback(invoke_without_command=True)` — calls `_wizard()` when no subcommand given
- `_wizard()` prompts for: language, mode (important/full), page concurrency, language concurrency, max pages, per-host delay, force refresh
- Conservative defaults: mode=important, page_concurrency=4, lang_concurrency=2, max_pages=1000, per_host_delay=0.15s
- Shows summary `Panel` with `Table.grid` before confirming
- `_execute_run()` extracted as shared helper used by both wizard and `run` command
- Removed `--splitmode`, `--smart`, `--single-terminal` flags

```python
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _wizard()

def _wizard() -> None:
    console.print(Panel("[bold cyan]Documentation Ingestion Wizard[/bold cyan]", border_style="cyan", expand=False))
    lang_input = typer.prompt("Language to crawl (press Enter for all languages)", default="")
    language = lang_input.strip() or None
    # ... mode, concurrency, max_pages, per_host_delay, force_refresh prompts ...
    if not typer.confirm("Start crawl?", default=True):
        raise typer.Exit()
    _execute_run(language=language, mode=mode, ...)
```

---

### 2. Split mode removed (`doc_ingest/pipeline.py`) — Major rewrite

- Removed `split_mode` parameter from `run()` and `_run_language()`
- Removed `processing_phase()` function entirely
- Removed `if split_mode:` block at end of `_run_language()`
- Removed `phase` field from state entries
- Added adaptive tune loop as background task:

```python
async def _tune_loop() -> None:
    while True:
        await asyncio.sleep(5.0)
        await self.adaptive_controller.tune()

_tune_task = asyncio.create_task(_tune_loop())
try:
    await queue.join()
finally:
    _tune_task.cancel()
    try:
        await _tune_task
    except asyncio.CancelledError:
        pass
```

- Replaced `_fetch_document_for_discovery()` + `_process_url()` with single `_fetch_and_process()`:

```python
async def _fetch_and_process(
    self,
    record: UrlRecord,
    plan: PlannedSource,
    progress_tracker: CrawlProgressTracker | None,
) -> tuple[DiscoveryDocument, ExtractedDocument | None]:
    """Fetch once, extract once — returns both the discovery view (links) and the full document."""
    cache_dir = self.config.paths.cache_dir / plan.language.slug
    fetch_result = await self.http_fetcher.fetch(record.normalized_url, cache_dir)
    document = await asyncio.to_thread(extract_document, fetch_result)
    disc = DiscoveryDocument(
        title=document.title,
        final_url=document.final_url,
        links=document.links if asset_type == "html" else [],
    )
    return disc, document
```

- Removed unused imports: `extract_html_links`, `PageProcessResult`

---

### 3. Adaptive controller always-on (`doc_ingest/adaptive.py`)

- Removed `self.enabled = bool(config.crawl.smart_mode)` from `__init__`
- Removed `if not self.enabled: return` from `tune()`
- Controller now always active — monitors CPU/memory/disk every 5s, adjusts `per_host_delay_seconds`

---

### 4. Removed `smart_mode` config field (`doc_ingest/config.py`)

- Removed `smart_mode: bool = False` from `CrawlConfig`
- Retained all `smart_min_*` / `smart_max_*` tuning parameters

---

### 5. Removed `os.fsync()` (`doc_ingest/utils/filesystem.py`)

Every write function previously flushed and fsynced to disk — costing 1–10ms per write, thousands of times per crawl.

```python
# Before
with open(temp_path, "wb") as handle:
    handle.write(payload_bytes)
    handle.flush()
    os.fsync(handle.fileno())
temp_path.replace(path)

# After
temp_path.write_bytes(payload_bytes)
temp_path.replace(path)
```

Atomic rename already provides crash safety. Removed `import os`.

---

### 6. Fixed async I/O in browser fetcher (`doc_ingest/fetchers/browser.py`)

```python
# Before
content_bytes = cache_path.read_bytes()  # blocking

# After
content_bytes = await asyncio.to_thread(cache_path.read_bytes)

# Before
write_bytes(cache_path, content.encode("utf-8"))  # blocking

# After
await asyncio.to_thread(write_bytes, cache_path, content.encode("utf-8"))
```

---

## Performance Analysis

### Root cause of CPU usage
Synchronous CPU-bound work (BeautifulSoup, Docling, regex) running in the asyncio event loop thread. Async workers are not truly concurrent for CPU work — one blocks all others.

### Fixes applied
| Fix | Impact |
|---|---|
| `asyncio.to_thread()` for extraction | Workers' CPU work overlaps with each other and with I/O |
| Eliminated double HTML parse | One fewer full BS4 parse per HTML page |
| Removed `os.fsync()` | Saves 1–10ms × thousands of writes per crawl |
| Removed blocking browser cache reads | No longer blocks event loop during cache hits |

### Remaining known cost
`html_docling.py` still does 2 internal parses per HTML page (Docling conversion + BeautifulSoup for title/links/headings). Cannot easily be reduced without modifying Docling's interface.

---

## Top 5 Next Steps

1. **Run end-to-end smoke test**  
   `python documentation_downloader.py run --language python --mode important`  
   Verify combined-mode extraction, adaptive tune loop, and wizard flow all work. Do this before building anything else.

2. **Playwright page pool**  
   Reuse pages across requests instead of create/destroy per URL. Significant speedup for JS-heavy doc sites.  
   In `browser.py`: maintain a pool of open pages, acquire/release via semaphore.

3. **Persist wizard settings**  
   Save wizard answers to `crawl_config.json` in project root. Pre-fill wizard on next run. Add `--reset-config` to re-run wizard.

4. **Make failed extractions retryable**  
   URLs with `hash: "discovered-only"` in `state["processed"]` are permanently skipped. Move them to `state["failed"]` to be retried on next run.

5. **Stream documents to disk**  
   `processed_docs` holds all markdown in RAM until compile. Write per-document temp files and compile by reading them back — keeps memory flat for full 50-language runs.

---

## Files Modified This Session

| File | Change |
|---|---|
| `doc_ingest/cli.py` | Complete rewrite — wizard, removed splitmode/smart, `_execute_run()` helper |
| `doc_ingest/pipeline.py` | Removed split mode, fused fetch+process, added tune loop |
| `doc_ingest/adaptive.py` | Removed `enabled` gate — always on |
| `doc_ingest/config.py` | Removed `smart_mode` field |
| `doc_ingest/utils/filesystem.py` | Removed `os.fsync()`, simplified write functions |
| `doc_ingest/fetchers/browser.py` | Wrapped sync I/O in `asyncio.to_thread()` |
