# Development Progress

## Current state summary (v1.1.1)

The repository ships as a working Windows desktop application backed by a frozen Python FastAPI process. The active Python package is a source-adapter ingestion pipeline for DevDocs, MDN, and Dash/Kapeli. The WinUI3 shell covers all operator workflows: Languages, Run, Bulk, Presets, Reports, Output Browser, Checkpoints, Cache, and Settings.

Highlights shipped in `v1.1.1`:
- Cooperative cancellation via `asyncio.sleep(0)` in the event sink between documents
- Job history persisted to `logs/job_history.jsonl` and restored on backend startup
- 30s backend health monitor with dispatcher-safe UI updates on failure/recovery
- SSE reconnection with `from_index` cursor on unexpected stream disconnect (5 retries, exponential backoff)
- Cancel button gives immediate UI feedback before SSE event arrives
- Startup error dialog (`ContentDialog`) when backend fails to start
- `ruff format` compliance on touched Python files
- language resolution hardening for shorthand aliases, version-shaped inputs, and punctuation/Unicode variants
- weighted validation score with additive component scores
- bounded live Dash acceptance probe that extracts a real docset, validates SQLite traversal, and converts one indexed document
- output storage management in the desktop shell: bundle sizes, safe bundle deletion, and report-history pruning

## What works today

### CLI and orchestration

- Top-level bootstrap works through `DevDocsDownloader.py`
- Typer app defined in `doc_ingest/cli.py` with full operator help text
- Interactive wizard path exists
- Single-language, bulk, validation-only, catalog listing/refresh, preset audit, and init commands all implemented
- Desktop backend host uses desktop-safe runtime paths and settings

### Source registry and resolution

- Source registry composes DevDocs, MDN, and Dash adapters with plugin entry-point loading
- Language resolution supports source override and source priority ordering
- `_normalise_lang()` maps special-char names and shorthand aliases (C++→cpp, C#→csharp, Node.js→nodejs, .NET→net, js→javascript, ts→typescript, py→python)
- Exact, family, prefix, and contains matching with alias support
- Version-shaped requests such as `python3.12` and `vue 3` resolve to the right family and prefer an exact version when present
- Fuzzy suggestions for unresolved names
- All-language catalog enumeration with deduplication

### DevDocs adapter

- Catalog fetch and cache implemented with cached-manifest fallback
- Dataset fetch and cache with corrupt-JSON detection
- HTML-to-Markdown conversion with source-specific cleanup
- Important/full mode filtering via `devdocs_core.json`
- Fragment references preserved (not silently dropped)

### MDN adapter

- Dynamic catalog discovery with cached-manifest fallback
- GitHub tarball download with checksum and area-readiness metadata
- Selective tar extraction (only relevant `files/en-us` trees)
- Safe YAML frontmatter parsing with recoverable malformed input
- Important/full mode filtering via `page-type`

### Dash adapter

- Dynamic catalog discovery from Kapeli's cheat-sheet index with cached-manifest fallback
- Docset download, extraction, and SQLite search index traversal
- HTML-to-Markdown with navigation noise removal and relative link rewriting
- Important/full mode filtering via entry type
- Opt-in bounded live acceptance probe verifies one small real docset archive end to end

### Output generation

- Per-topic directories, per-document Markdown, topic `_section.md`, language `index.md`, consolidated language Markdown, and `_meta.json`
- Windows-reserved filename normalization through `slugify()`
- Collision-safe consolidated anchors via shared unique-anchor registry
- Optional YAML frontmatter per document (`--document-frontmatter`)
- Optional retrieval chunk export with JSONL manifest (`--chunks`)
- Optional tokenizer-aware chunking via tiktoken (`--chunk-strategy tokens`)
- Asset inventory and deduplication from adapter `AssetEvent` records
- Exact cross-document link rewriting for known same-language targets

### Validation and reporting

- Structural validation after every compilation run
- Internal anchor, duplicate section/document heading, source-inventory reconciliation checks
- Per-document validation records in `validation_documents.jsonl`
- Weighted validation score with additive component scores for completeness, structure, conversion, consistency, and document quality
- Quality trend reports in `trends.json` / `trends.md`
- Report history under `output/reports/history/`
- Active checkpoints under `state/checkpoints/` during runs; removed on success
- Automatic checkpoint resume when artifacts still exist

### Desktop backend and WinUI shell

- FastAPI loopback backend on `127.0.0.1:{random-port}` with bearer-token auth
- Single active job queue (409 on conflict); SSE event streaming with 15s heartbeat
- Job history persisted to `logs/job_history.jsonl`; reloaded on backend startup
- Cooperative cancellation: `asyncio.sleep(0)` in event sink allows `CancelledError` propagation at document boundaries
- Health/version/shutdown, run/bulk/validate, output/reports/checkpoints/cache/settings endpoints
- WinUI3 shell: persistent tab state, shared live progress and activity log, cancel button with immediate feedback
- SSE client reconnects on stream drop using `from_index` cursor (5 retries, exponential backoff)
- 30s health monitor detects backend crash and updates shell status
- Startup failure shows `ContentDialog` with error message and log path
- Language tree: searchable source-first and category-first views
- Output Browser, Reports, Checkpoints, Cache, Settings pages all present and functional
- Output Browser shows managed storage totals, bundle sizes, safe delete, and report-history pruning
- Desktop default output root: `%UserProfile%\Documents\DevDocsDownloader`
- Desktop per-user storage: `%LocalAppData%\DevDocsDownloader\{cache,state,logs,tmp,settings}`

### Tests

- Contract, integration, CLI, resilience, architecture, desktop-backend, pipeline, service-artifact, setup-script, version, source-discovery, live-endpoint (opt-in), and live-extraction-sanity (opt-in) test files
- `test_desktop_backend.py` covers job queue transitions, SSE, history, cancel, auth

## Partially implemented or shallow areas

### Validation quality

Layered and pragmatic — not semantic.

- detects missing/tiny output, unbalanced code fences, required sections, unresolved links, HTML leftovers, malformed tables, definition-list artifacts
- checks internal anchors, duplicate sections/document headings, source inventory reconciliation
- weights validation scores by bundle size and emits component scores instead of flat per-issue deductions
- emits per-document validation records

Does **not** verify:
- semantic source correctness
- Markdown rendering quality beyond static heuristics
- full source completeness beyond counter reconciliation

### Cancellation

Cooperative cancel improved: `asyncio.sleep(0)` between events allows `CancelledError` to propagate at document boundaries. Cancel is now meaningfully faster for document-heavy runs. Full sub-document granularity (interrupting in-flight httpx requests mid-download) is not yet implemented.

## Known bugs, mismatches, and fragile areas

See `documentation/roadmap.md` for the full prioritized list. Summary of remaining open issues:

- Single-job queue with no queuing UI (High)
- Dash source still lacks broad full-language acceptance coverage (High)
- Some language normalization edge cases may still exist outside the common alias set (Medium)
- Settings changes don't affect already-running jobs (Medium)
- Unsigned binary — Windows SmartScreen warning (Medium)
- PRI file copy in CI is fragile grep (Medium)
- No auto-update (Low)

## Implementation completeness by subsystem

| Subsystem | Status | Notes |
|---|---|---|
| CLI | Working | All commands implemented |
| Config/paths | Working | Repo and desktop modes |
| Registry | Working | Normalization, exact/family/prefix/contains matching, plugins |
| DevDocs adapter | Working | Best-aligned source |
| MDN adapter | Working with caveats | Heavy archive; simple frontmatter |
| Dash adapter | Working with caveats | Bounded live acceptance exists; full language coverage still not in routine CI |
| Compiler | Working | Chunking, asset inventory, link rewriting |
| Validator | Working | Structural, anchor, inventory, per-document records |
| Reporting | Working | Summaries, history, trends |
| State store | Working | Active checkpoints + stable state |
| Progress UI | Working | CLI presentation only |
| Desktop backend | Working | Jobs, SSE reconnect, history persistence, health endpoint |
| WinUI shell | Working | All pages, persistent state, health monitor, error dialogs |
| Tests | Working | Broad coverage; live probes opt-in |
| Benchmarks | Working | Targets active CLI |
| Support scripts | Aligned | build_desktop_backend, check_version, generate_icon, minimal_smoke all current |

## Priority improvements

### Highest priority (v1.0.x patches — in progress or done)

- ~~Cooperative cancellation~~ — done (asyncio.sleep(0) in event sink)
- ~~Job history lost on restart~~ — done (job_history.jsonl)
- ~~SSE stream drops silently~~ — done (reconnect with from_index)
- ~~Startup failure shows blank window~~ — done (ContentDialog)

### Medium priority (v1.1.x - v1.2.0)

1. Job queue UI (show pending state instead of 409 error)
2. Better desktop cleanup breadth (cache + richer retention controls)
3. Broader Dash acceptance depth in CI
4. Packaging/distribution cleanup around desktop release reliability

### Lower priority (v1.2.0+)

- PRI packaging fix (MSBuild target instead of grep-and-copy)
- Code signing
- Auto-update notification
- Persistent job history across restarts (done for current session; deep history via SQLite is a future option)
