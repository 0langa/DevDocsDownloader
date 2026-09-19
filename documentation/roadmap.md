# DevDocsDownloader — Roadmap to 2.0.0

> **Current release:** 1.5.0  
> **Document scope:** All planned work from 1.2.0 through 2.0.0 premium release.
> **Last updated:** 2026-05-01

---

## Vision: What 2.0.0 Looks Like

DevDocsDownloader 2.0.0 is a **premium documentation intelligence platform** for power users, developers, and AI engineers needing high-quality, structured, richly formatted documentation offline and on-demand.

By 2.0.0 product:

- Ingests from every major documentation source with measurable quality confidence.
- Outputs multiple formats (Markdown, HTML site, PDF, EPUB, chunked vector-ready JSON), full customization over structure, style, detail level, content depth.
- Indexes every compiled document for instant full-text and semantic search inside app.
- Automates recurring documentation pulls on user-defined schedules with smart refresh policies.
- Ships first-class, keyboard-navigable, accessible desktop app: dark mode, onboarding, in-app help, automatic updates.
- Extensible via stable plugin API — users and third parties add sources, custom conversion pipelines, post-processing hooks.
- Handles corpora of any scale — one language to hundreds — without memory pressure, via streaming compilation and tiered caching.
- Traceable, versioned output: every run recorded, run differences browsable, rollback to prior compiled version in one click.
- Code-signed, installer-distributed, professionally documented.

---

## Milestone Philosophy

Each **minor version** (1.2.0, 1.3.0, …) is a named major milestone with clear theme and concrete "done" definition. **Patch versions** between milestones (1.1.5, 1.1.6, …) are focused, releasable increments, each adding one meaningful capability or fixing one meaningful class of problem. No patch version is a grab-bag.

Every patch version:
- Passes all existing tests plus new tests for its changes.
- Does not break output contract.
- Ships updated release notes.
- Keeps backward compatibility with existing settings, checkpoints, compiled output.

---

## Architecture Baseline (v1.1.1)

Honest accounting of current state.

**What works well:**
- Source adapter pattern (DevDocs, MDN, Dash) with clean protocol boundaries.
- Async pipeline with cooperative cancellation and SSE streaming.
- Checkpoint/resume with per-document boundary tracking.
- FastAPI desktop backend: job history, health monitoring, SSE reconnection.
- WinUI 3 desktop shell: 9 pages, real-time job tracking, observable ViewModel.
- 113+ passing tests across integration, contract, phase-level suites.
- Weighted validation scoring across 5 quality dimensions.

**Critical gaps going into 1.2.0:**
- Streaming writes cap compilation memory near one document, but HTML site / future secondary outputs need same treatment.
- MDN uses commit-SHA delta checks and archive indexing, but archive scans remain serial and slow on very large refreshes.
- No job queue; desktop returns 409 if user runs while another job is active.
- Empty `doc_key` in DevDocs single-page manuals (bash, etc.) emitted 0 documents until 1.0.9.2 fix — similar edge cases may exist elsewhere.
- Conversion quality uneven; no per-source conversion profile tuning exposed to users.
- Validation catches structural issues but not link existence or document integrity hashes.
- Resume logic checks artifact paths exist, not that content is uncorrupted.
- No cache management UI; users cannot inspect or clear cache from desktop app.
- Dash docsets downloaded blind — no way to know docset size or quality before committing.
- Dry-run mode absent; users cannot sanity-check source resolution before full download.

---

## 1.2.0 — "Rock-Solid Foundation"

**Theme:** Eliminate correctness issues, cut resource waste, make system trustworthy under adverse conditions, close worst usability gaps before building new features on top.

**Done when:**
- No job silently lost to OOM, process restart, or conflicting state.
- MDN refresh path does not visibly stall UI.
- Desktop app never returns 409 to a user starting a run.
- Cache management accessible and usable from desktop shell.
- All core conversion functions have unit tests.
- Checkpoint resume verifies content, not just file existence.

---

### 1.1.2 — Catalog-Driven Language Selection & Source Dropdowns

**Goal:** Replace error-prone free-text inputs with catalog-backed dropdowns. Make "download everything" one click.

**Status:** ✅ Done

**Delivered:**
- Run page source input switched to catalog-backed dropdown.
- Bulk page switched to searchable multi-select from live `/languages` catalog.
- Version filtering (`Latest only` / `All versions`) for suggestions and `Download all`.
- One-click `Download all` fills selection and starts bulk run.
- Bulk source dropdown wired end-to-end.
- Added `BulkRunRequest.source`, passed through to pipeline source resolution.

---

### 1.1.3 — Streaming Pipeline & MDN Efficiency

**Goal:** Prevent OOM for large docsets. Make MDN refresh non-blocking.

**Status:** ✅ Done

**Delivered:**
- Compiler switched to streaming writes, memory near one-document scale.
- MDN tarball handling moved to incremental archive scan and on-demand member reads.
- MDN refresh checks upstream commit SHA, skips unchanged large downloads.
- Per-domain runtime circuit breaker for repeated upstream failures.
- Adaptive memory-pressure guard drops concurrency under high RAM pressure.

---

### 1.1.4 — Job Queue & Error Messaging

**Goal:** Never tell user "busy, try again." Make error messages actionable.

**Status:** ✅ Done

**Delivered:**
- Bounded backend job queue with pending-position updates (`Queued (position N)`), plus `/jobs/queue`.
- Standardized structured `SourceError` payloads (`code`, `message`, `hint`, `is_retriable`) through pipeline and backend events.
- Desktop shell surfaces failure hints via `LastErrorHint` in dedicated warning block.
- Validation issues include actionable `suggestion` text, rendered in Reports.

---

### 1.1.5 — Cache Management Desktop UI

**Goal:** Users see, understand, clean up cached source data without touching filesystem.

**Status:** ✅ Done

**Delivered:**
- Full Cache page: per-source summaries, per-entry actions, source clear, full clear.
- Cache budget setting and enforcement (`cache_budget_exceeded`) with UI budget visibility.
- Dry-run pipeline/service path and desktop `Preview` workflow.

---

### 1.1.6 — Test Coverage Expansion

**Goal:** Converter functions, adapter edge cases, backend job logic all have unit tests.

**Status:** ✅ Done

**Delivered:**
- Focused unit suites for conversion, cache policies/metadata, adaptive concurrency behavior.
- Backend job lifecycle tests for queueing, cancellation, SSE replay.
- Mocked adapter tests for 404/corrupt/empty payload edge cases.

---

### 1.1.7 — Resume Hardening & Checkpoint Integrity

**Goal:** Resumed run never silently skips or duplicates content.

**Status:** ✅ Done

**Delivered:**
- Content hashes in checkpoint artifacts, resume-time hash validation, rollback to last verified artifact.
- Checkpoint persistence switched to atomic write/replace.
- Stale checkpoint detection/listing/deletion and desktop stale-cleanup action.
- Checkpoint schema versioning with safe discard on mismatch.

---

### 1.2.0 — Foundation Milestone Release

**Status:** ✅ Done

**Delivered:**
- Streaming compilation (OOM risk eliminated).
- MDN delta detection (no redundant 500MB downloads).
- Circuit breaker on all external HTTP calls.
- Job queue (no more 409 conflicts).
- Specific error codes and actionable hints in UI.
- Full `CachePage` with usage tracking, eviction controls, budget enforcement.
- Dry-run preview mode.
- Content-hashed checkpoint resume.
- Atomic checkpoint writes.
- Unit test suite for converters, cache, adaptive, adapters, job lifecycle.

---

## 1.3.0 — "Source Excellence"

**Theme:** Every source adapter high-confidence, self-reporting, quality-measurable. Users see what they get before committing to download. New sources cover single-page manuals and curated offline archives.

**Done when:**
- Dash docsets have pre-download size and quality hints.
- Conditional GET caching cuts unnecessary network traffic by >80% for unchanged content.
- Direct web crawl source adapter handles single-page manuals (GNU bash.html, POSIX spec, etc.).
- Every source has per-source quality confidence metric visible in language browser.
- Source health continuously monitored and surfaced in desktop UI.

---

### 1.2.1 — Conditional GET Caching

**Goal:** Honor `ETag` / `Last-Modified` headers, skip downloads when content unchanged.

**Status:** ✅ Done

**Delivered:**
- Conditional runtime requests with `If-None-Match` / `If-Modified-Since` and `NotModifiedResponse` handling.
- Conditional behavior wired into DevDocs dataset fetches and Dash docset refresh flow.
- Activated `validate-if-possible` policy: conditional validation instead of fallback no-op.

---

### 1.2.2 — Dash Pre-Download Intelligence

**Status:** ✅ Done

**Goal:** Show users what they get before downloading a Dash docset.

**Changes:**

1. **Dash metadata probe**  
   Before downloading full `.tgz`, `HEAD https://kapeli.com/feeds/{slug}.tgz`. Parse `Content-Length`. Store in `DashDocsetMeta(slug, tgz_size_bytes, last_modified)`. Expose via `LanguageCatalog.discovery_metadata["tgz_size_bytes"]`.

2. **Parallel catalog enrichment**  
   During `DashFeedSource.list_languages()`, fire HEAD requests per docset in parallel (bounded semaphore, 10 concurrent). Cache size hints in catalog manifest. Populate `LanguageCatalog.size_hint` from `tgz_size_bytes`.

3. **Size warnings in desktop UI**  
   `LanguagesPage` shows size badges beside Dash entries: "3 MB", "42 MB", "120 MB". `RunPage` shows size warning modal for docsets >50 MB: "This docset is approximately N MB. Continue?" (dismissible permanently per-language).

4. **Docset quality heuristic**  
   After downloading a Dash docset, record indexed entry count, document count, conversion success rate. On later catalog loads, compute `confidence`: `high` (many entries, >90% conversion success), `medium`, `low`. Show confidence badge on `LanguagesPage` for entries with prior download history.

---

### 1.2.3 — Per-Docset Conversion Profiles

**Status:** ✅ Done

**Goal:** Improve Dash conversion quality per docset; expose tunable profiles.

**Changes:**

1. **Dash conversion profile registry**  
   Add `dash_profiles.json` to `doc_ingest/sources/`. Format: `{ "Ruby": { "content_selectors": [...], "noise_selectors": [...] } }`. `DashFeedSource` loads it and passes matching profile to `convert_html_to_markdown()`. Falls back to `DASH_PROFILE` if no entry exists.

2. **Self-improving profile inference**  
   After each Dash docset fetch, record which CSS selectors found content roots vs. which fell back to `body`. Persist per-docset in cache metadata. Next fetch uses previously successful selectors as primary profile. Self-improving heuristic, no manual tuning.

3. **Profile editor in advanced settings**  
   `SettingsPage` → "Conversion Profiles" sub-section. Table of known profiles with editable selector lists. Users add custom selectors, test against cached HTML sample, save. "Test" action fetches one document from cached docset, applies profile, shows resulting markdown in split-view preview panel.

---

### 1.2.4 — Direct Web Crawl Source Adapter

**Status:** ✅ Done

**Goal:** Ingest single-page manuals (GNU bash, POSIX spec, Python docs) directly from web.

**Changes:**

1. **`WebPageSource` in `sources/web_page.py`**  
   Implements `DocumentationSource`. Discovery driven by `web_sources.json` (bundled in `doc_ingest/sources/`):
   ```json
   [
     {
       "slug": "bash-manual",
       "display_name": "Bash Manual",
       "homepage": "https://www.gnu.org/software/bash/",
       "doc_url": "https://www.gnu.org/software/bash/manual/bash.html",
       "core_topics": ["Builtins", "Shell Syntax", "Job Control"],
       "content_selector": "#main-content, .manual",
       "section_selector": "h2, h3",
       "family": "shell"
     }
   ]
   ```

2. **Fetch strategy**  
   Single-document sources: fetch URL, extract sections via `section_selector` into individual `Document` objects (one per top-level heading). Each heading + content = one document. Slug = heading text slugified. Turns a 500KB single-page manual into ~30 structured documents.

3. **Multi-page crawl support (bounded)**  
   For sources with `crawl_links: true` and `allowed_path_prefix`: after fetching entry page, extract `<a href>` links within prefix, deduplicate, fetch in order (bounded to `max_pages: 200`). Each page yields one or more documents. Crawl state persisted to checkpoint so incomplete crawls resume.

4. **Caching strategy**  
   Full page content cached in `cache/web_page/{slug}/`. Metadata tracks `Last-Modified`/`ETag` from server. TTL-based refresh applies; 7-day default TTL for pages with no caching headers.

5. **Registration**  
   `WebPageSource` registered in `SourceRegistry` after Dash in priority. Resolution order: `devdocs → mdn → dash → web_page`.

---

### 1.2.5 — Source Health Dashboard

**Status:** ✅ Done

**Goal:** Surface real-time source availability and quality in desktop.

**Changes:**

1. **`GET /sources/health` endpoint**  
   Per-source status: `{ "devdocs": { "status": "ok", "last_checked": "...", "catalog_age_hours": 2.1, "circuit_breaker": "closed" }, "mdn": { "status": "ok", "commit_sha": "abc123" }, "dash": { "status": "degraded", "reason": "429 at 14:32" }, "web_page": { "status": "ok" } }`.

2. **Source health indicator in sidebar**  
   Small colored dot per source (green/yellow/red) below app title. Hover shows detail from `/sources/health`. Red = circuit breaker open or last probe failed. Yellow = degraded or stale catalog. Green = all checks passing.

3. **Catalog staleness warnings**  
   If a source catalog is >7 days old (configurable), show warning in `LanguagesPage` for that source: "DevDocs catalog is 8 days old. Refresh?" with one-click refresh.

---

### 1.2.6 — Per-Source Quality Metrics

**Status:** ✅ Done

**Goal:** Every compiled language has measurable quality score informing future source selection.

**Changes:**

1. **Historical quality tracking**  
   After each successful run, store `SourceQualityRecord(source, slug, run_date, document_count, topics, validation_score, conversion_success_rate, skip_rate)` in `logs/quality_history.jsonl`. `list_output_bundles()` enriches bundle metadata with latest quality record.

2. **Source quality comparison**  
   When multiple sources serve the same language, `registry.py resolve()` ranks by latest `validation_score` from `quality_history.jsonl`. Users override source preference in `RunLanguageRequest`. `LanguagesPage` shows preferred source with "change source" dropdown for multi-source languages.

3. **Quality history in `ReportsPage`**  
   Sparkline of validation scores over last 10 runs per language. Shows quality trend (improving / stable / degrading) at a glance.

---

### 1.3.0 — Source Excellence Milestone Release

**Status:** ✅ Done

**Summary of what ships:**
- Conditional GET caching, no redundant downloads.
- Dash pre-download size and quality intelligence with confidence badges.
- Per-docset Dash conversion profiles with user-editable overrides.
- `WebPageSource` adapter for single-page manuals (bash, POSIX, etc.).
- Source health dashboard in desktop sidebar.
- Historical quality tracking with trend view in reports.

---

## 1.4.0 — "Output Intelligence"

**Theme:** Compiled output richer, more flexible, verifiable, version-tracked. Users get multiple output formats, control over structure and style, ability to track how documentation evolves across runs.

**Done when:**
- Chunking is heading-aware and semantically coherent.
- At least two extra output formats (HTML site, EPUB) stable.
- Every compiled document has integrity hash.
- Desktop shows per-document quality scores inline.
- Run output versioned; run diffs browsable.

---

### 1.3.1 — Semantic Chunking

**Status:** ✅ Done

**Goal:** Chunks respect document structure instead of splitting on arbitrary character counts.

**Changes:**

1. **Heading-aware chunk splitter**  
   `ChunkStrategy.semantic` (new value alongside `chars` and `tokens`). Splitter walks rendered markdown, identifies heading boundaries (`##`, `###`), creates chunks that:
   - Never split inside a code block.
   - Never split between a heading and its first paragraph.
   - Respect `chunk_max_chars` as soft limit (may exceed up to 1.5× to avoid splitting mid-section).
   - Group H3 sections under parent H2 if combined size under limit.
   - Prepend `<!-- chunk: N/T -->\n# Section Title\n` to each chunk for orientation context.

2. **Overlap preservation**  
   Where next chunk starts with an H3, prepend parent H2 heading text (not full content) for hierarchy context in vector embedding without doubling content.

3. **Chunk metadata in frontmatter**  
   When `emit_document_frontmatter: true`, chunk files gain: `chunk_index`, `chunk_total`, `parent_slug`, `parent_heading`, `section_heading`. Chunks become self-describing for RAG pipelines.

---

### 1.3.2 — Output Versioning

**Status:** ✅ Done

**Goal:** Every run's output traceable; run differences browsable.

**Changes:**

1. **Run manifest per language**  
   After successful compile, write `output/{language}/manifest.json`:
   ```json
   {
     "language": "Python 3.12",
     "source": "devdocs",
     "run_date": "2026-04-30T14:22:00Z",
     "mode": "full",
     "document_count": 412,
     "total_chars": 2847321,
     "content_sha256": "...",
     "documents": [
       { "slug": "classes", "title": "Classes", "sha256": "..." }
     ]
   }
   ```
   `content_sha256` = SHA256 of concatenated per-document hashes (deterministic aggregate).

2. **Run history archive**  
   Before overwriting output, move current `manifest.json` to `output/{language}/.history/{run_date_iso}.json`. Keep last 10 manifests (configurable). Content files not archived (too large); manifest only. Records past run contents without doubling storage.

3. **Diff view in desktop**  
   `ReportsPage` gains "Compare runs" mode. Selecting two historical manifests shows: documents added, removed, changed (where `sha256` differs). Summary: `+N documents, -N documents, ~N documents changed`.

---

### 1.3.3 — Advanced Validation (Link Checking & Integrity)

**Status:** ✅ Done

**Goal:** Validation catches more real problems; integrity hashes make tampering detectable.

**Changes:**

1. **Per-document integrity hashes**  
   `validate_documents()` computes `sha256(document_markdown)` per document, stores in `ValidationResult.document_hashes: dict[str, str]`. State store includes hashes. In validate-only mode, if output exists and hashes match, skip re-download.

2. **Internal link validation**  
   `_check_links()` (new function in `validator.py`): extract all `[text](link)` references. Relative links (no `https://`, no `dash://`): verify target file exists in language output directory. Anchor links (`#heading`): verify heading exists in current file. Report `broken_internal_link` issue per failure.

3. **HTML artifact detection improvement**  
   Current regex `<[a-zA-Z]+[^>]*>` too aggressive. Replace with targeted check for structural artifacts only: `<div`, `<span`, `<table`, `<p>` — run through simple state machine, not broad regex. Cuts false positives from Markdown table syntax.

4. **Validation report export**  
   Write machine-readable `output/{language}/validation.json` beside markdown after each run. Includes `composite_score`, per-component scores, all issues with file paths and line numbers. Consumable by CI pipelines or external tools.

---

### 1.3.4 — Per-Document Quality Scores in Desktop

**Status:** ✅ Done

**Goal:** Quality info visible per document, not only aggregate.

**Changes:**

1. **`GET /output/{language}/validation` endpoint**  
   Returns `validation.json` for a language. Includes per-document scores if `validate_documents()` ran.

2. **`OutputBrowserPage` quality indicators**  
   Colored dot beside each document in file tree: green (score ≥0.8), yellow (0.5–0.8), red (<0.5). Hover shows top issue for that document (e.g., "3 relative links, 1 HTML artifact").

3. **Report summary improvements**  
   `ReportsPage`: composite score as large number with trend arrow (↑/↓ vs last run), component breakdown with bars, top 5 issues across all documents with counts, lowest-scoring documents at bottom with links opening them in `OutputBrowserPage`.

---

### 1.3.5 — Template System for Output Customization

**Status:** ✅ Done

**Goal:** Users control how compiled output is structured and formatted.

**Changes:**

1. **Jinja2 template engine**  
   Add `doc_ingest/templates/`. Templates are `.md.j2` files. Context: `{{ language }}`, `{{ source }}`, `{{ documents }}` (list of `{title, slug, markdown, topic, source_url}`), `{{ run_date }}`, `{{ mode }}`. Applied per-document and for consolidated file.

2. **Bundled templates**  
   - `default.md.j2` — Current behavior, no change to existing output.
   - `detailed.md.j2` — Adds source URL, topic, run date as per-document frontmatter. Table of contents atop consolidated file.
   - `minimal.md.j2` — Strips all frontmatter and metadata; pure content. Optimized for LLM context window injection.
   - `api-reference.md.j2` — Groups documents by topic, sorts alphabetically within group, adds index section at top with per-topic anchor links.

3. **Template selection**  
   `DesktopSettings.output_template: str = "default"`. `SettingsPage` shows template dropdown with preview. `RunLanguageRequest.template: str | None` overrides global setting per-run.

4. **Custom template directory**  
   Users place `.md.j2` files in `%LOCALAPPDATA%\DevDocsDownloader\templates\`. These appear in template dropdown beside built-ins.

---

### 1.3.6 — Multi-Format Output: HTML Site

**Status:** ✅ Done

**Goal:** Compiled documentation available as navigable static HTML website.

**Changes:**

1. **HTML site generator in `doc_ingest/formats/html_site.py`**  
   Given a compiled language directory, produces `_site/{language}/`:
   - `index.html` — navigable table of contents (topic groups, alphabetical per-document links).
   - `{slug}.html` — each document as HTML with syntax highlighting (highlight.js bundled as static asset).
   - `_site/assets/` — CSS (clean, minimal, dark-mode-capable), JS (highlight.js, search index loader).
   - `search-index.json` — client-side JS full-text search within site.

2. **HTML format option in `RunLanguageRequest`**  
   `output_formats: list[Literal["markdown", "html", "epub"]] = ["markdown"]`. When `"html"` included, `services.py` calls `html_site.generate()` after successful markdown compilation. HTML generated from compiled markdown, not re-fetched from source.

3. **HTML site browser in desktop**  
   `OutputBrowserPage` adds "Open as website" button for languages with `_site/`. Click opens `index.html` in default browser.

---

### 1.4.0 — Output Intelligence Milestone Release

**Status:** ✅ Done

**Summary of what ships:**
- Semantic heading-aware chunking with orientation context and hierarchy-aware overlap.
- Per-run manifest with document-level integrity hashes.
- Run history with diff-view in `ReportsPage`.
- Internal link validation and improved HTML artifact detection.
- Machine-readable `validation.json` export.
- Per-document quality scores in `OutputBrowserPage`.
- Jinja2 template system: 4 built-in templates plus user custom templates.
- Static HTML site generation.

---

## 1.5.0 — "Search & Discovery"

**Theme:** Every compiled document instantly findable. App is the user's documentation interface, not just a download tool. Search, cross-referencing, instant access make compiled output useful day-to-day.

**Done when:**
- Full-text search across all compiled output returns results under 100ms for most queries.
- Cross-reference index links related APIs across languages.
- Semantic (embedding) search available as opt-in.
- Favorites and recently accessed tracked and surfaced.

---

### 1.4.1 — SQLite FTS5 Index

**Status:** ✅ Done

**Goal:** Full-text search index over all compiled output.

**Changes:**

1. **`doc_ingest/indexer.py` — new module**  
   SQLite database at `output/_search/index.db`:
   ```sql
   CREATE TABLE documents (
     id INTEGER PRIMARY KEY,
     language TEXT NOT NULL,
     slug TEXT NOT NULL,
     title TEXT,
     topic TEXT,
     source TEXT,
     file_path TEXT,
     run_date TEXT,
     content TEXT
   );
   CREATE VIRTUAL TABLE documents_fts USING fts5(
     title, topic, content,
     content=documents, content_rowid=id
   );
   ```

2. **Indexing on compile completion**  
   `services.py run_language()` calls `Indexer.index_language(language_dir)` after successful compile. Reads all `*.md` files (excluding chunks), strips frontmatter, inserts/replaces rows. Runs in background thread via `asyncio.to_thread()` so SSE events are not blocked.

3. **`GET /search?q={query}&limit=20&language={optional}` endpoint**  
   FTS5 query with snippet extraction. Returns language, slug, title, topic, file path, highlighted excerpt. Response target: <100ms.

---

### 1.4.2 — Search UI in Desktop

**Status:** ✅ Done

**Goal:** Instant search from anywhere in app.

**Changes:**

1. **Global search bar in sidebar**  
   Above nav buttons. Typing triggers debounced (300ms) `GET /search`. Results appear in flyout panel. Enter navigates to top result.

2. **Search results display**  
   Each result: language name, document title, topic tag, 2-line excerpt with query terms bolded. Clicking navigates to `OutputBrowserPage` with that file selected and opened in content preview pane.

3. **Keyboard navigation**  
   `Ctrl+F` focuses search bar. `↑`/`↓` navigate results. `Esc` dismisses. `Enter` opens top result.

4. **Search within document**  
   `OutputBrowserPage` content preview gets `Ctrl+G`: highlights all occurrences of search term, scrolls to first, `F3`/`Shift+F3` cycle through.

---

### 1.4.3 — Cross-Reference Index

**Status:** ✅ Done

**Goal:** Surface related APIs and concepts across language boundaries.

**Changes:**

1. **Cross-reference extractor in `indexer.py`**  
   After indexing all languages, extract code identifiers (CamelCase, snake_case, `function()` patterns) from every document. Build inverted index: `identifier → list of (language, slug, title)`. Stored in SQLite:
   ```sql
   CREATE TABLE xrefs (term TEXT, language TEXT, slug TEXT, title TEXT);
   CREATE INDEX xrefs_term ON xrefs(term);
   ```

2. **`GET /xref?term={term}` endpoint**  
   Returns all documents across all languages mentioning the identifier, grouped by language.

3. **"Related documents" panel in `OutputBrowserPage`**  
   With a document open, collapsible "Related" section at bottom lists up to 10 cross-reference hits for the most prominent identifiers in the current document.

---

### 1.4.4 — Semantic Search (Optional Embeddings)

**Status:** ✅ Done

**Goal:** Similarity-based search for users installing the optional embedding dependency.

**Changes:**

1. **`doc_ingest/embedder.py` — optional module**  
   Guarded by `try: import sentence_transformers`. Listed in `pyproject.toml` under `[project.optional-dependencies] semantic = ["sentence-transformers>=2,<4"]`. Uses `all-MiniLM-L6-v2` by default (~80MB).

2. **Vector storage in SQLite**  
   `documents` table gains `embedding BLOB`. On indexing (if embedder available), compute and store embeddings. `GET /search/semantic?q={query}&limit=10` computes query embedding, runs cosine similarity, returns top-N. Falls back to FTS5 with `X-Search-Mode: fts5` response header if embedder not installed.

3. **Desktop opt-in**  
   `SettingsPage` → "Enable semantic search" toggle. First enable: "This will download a ~80MB model." Progress tracked via `POST /search/setup-embeddings`. After setup, results show "Keyword" / "Semantic" tab toggle.

---

### 1.4.5 — Favorites & Recents

**Status:** ✅ Done

**Goal:** Frequently accessed documents and languages one click away.

**Changes:**

1. **Favorites system**  
   `output/_search/favorites.json`. `OutputBrowserPage` has per-document star button. Starred documents appear in "Favorites" section atop file tree. `GET /favorites` and `POST /favorites` endpoints.

2. **Recents tracking**  
   Every document opened in `OutputBrowserPage` recorded in `output/_search/recents.json` (last 50, deduped by language+slug). Collapsible "Recent" section in sidebar shows last 5 with language and title.

3. **Quick-launch dashboard on `RunPage`**  
   On startup, show 3 most recently compiled languages as quick-action cards: language, last run date, document count, validation score indicator, one-click "Refresh" button.

---

### 1.5.0 — Search & Discovery Milestone Release

**Status:** ✅ Done

**Summary of what ships:**
- SQLite FTS5 index over all compiled output.
- Global search bar in sidebar with full keyboard shortcuts.
- Cross-reference index linking related APIs across languages.
- Opt-in semantic search with local embedding model.
- Favorites and recents with quick-launch dashboard.

---

## 1.6.0 — "Automation & Scheduling"

**Theme:** Documentation stays fresh automatically. Users define refresh policies, schedules, notification preferences. Running a refresh is optional — app does it.

**Done when:**
- A language can have a configured refresh schedule running without user interaction.
- Windows toast notifications fire on job completion and failure.
- Webhook outputs notify external systems when docs change.
- Batch profiles saved, versioned, schedulable.

---

### 1.5.1 — Job Scheduler

**Goal:** Cron-like scheduling for recurring documentation refreshes.

**Changes:**

1. **`ScheduledJobStore`** persists schedules to `%LOCALAPPDATA%\DevDocsDownloader\schedules.json`. Each entry: `{id, language_or_preset, cron_expression, mode, last_run, next_run, enabled}`. Background `Scheduler` coroutine wakes every 60 seconds, checks `next_run` for all enabled schedules, submits due jobs to queue. `cron_expression` supports standard 5-field cron syntax (`0 3 * * *` = daily at 3am).

2. **`GET/POST/DELETE /schedules` endpoints**  
   CRUD for schedules. `POST /schedules` validates cron expression, returns computed `next_run`. `SettingsPage` → Schedules tab: list all schedules with add/edit/delete.

3. **Next-run indicator on `RunPage`**  
   Language quick-action cards show "Next refresh: Tuesday 03:00" if a schedule is configured.

---

### 1.5.2 — Windows Toast Notifications

**Goal:** Users know when a job completes without watching app.

**Changes:**

1. **`NotificationService` in C# shell**  
   Uses `Windows.UI.Notifications.ToastNotificationManager`. Triggered by job status change events in `MainWindowViewModel`. Template: "DevDocsDownloader — Python 3.12 ready — 412 documents compiled." Action buttons: "Open" (navigates to `OutputBrowserPage`) and "Dismiss".

2. **Notification preferences**  
   `SettingsPage` → Notifications: toggles for "Notify on job complete", "Notify on job failure", "Notify on scheduled refresh". All default to `true`.

3. **In-app notification history**  
   Bell icon in sidebar header. Last 20 notifications in memory; click opens dropdown with "Clear all".

---

### 1.5.3 — Per-Language Auto-Refresh Policies

**Goal:** Each language has own cache freshness and refresh policy, independent of global settings.

**Changes:**

1. **`LanguageSettings` store**  
   `LanguageSettings(slug, source, cache_policy, cache_ttl_hours, auto_refresh_schedule_id, output_template, preferred_mode)`. Persisted in `%LOCALAPPDATA%\DevDocsDownloader\language_settings.json`. `GET/PATCH /language-settings/{slug}` endpoints.

2. **Inheritance model**  
   Global settings → per-language override → request-level override. Desktop sends per-language settings when submitting a scheduled run.

3. **Settings UI on `LanguagesPage`**  
   Selecting a language opens detail panel (right column): source info, last compiled, quality score, per-language cache policy, TTL, auto-refresh schedule.

---

### 1.5.4 — Webhook Output Triggers

**Goal:** Notify external systems when documentation is compiled.

**Changes:**

1. **Webhook configuration**  
   `DesktopSettings.webhooks: list[WebhookConfig]`. `WebhookConfig(url, method, headers, events, secret)`. `events`: `["run.completed", "run.failed", "validation.score_change"]`.

2. **Webhook delivery in `services.py`**  
   After `run_language()` completes, fire `POST {url}` with JSON body: `{event, language, slug, source, document_count, validation_score, output_path, run_date}`. Sign with `HMAC-SHA256(body, secret)` in `X-DevDocs-Signature` header. Retry up to 3 times with exponential backoff. Log delivery outcomes.

3. **Webhook UI in settings**  
   `SettingsPage` → Webhooks: list with URL, events, last delivery status. "Test" button sends synthetic `run.completed`. Delivery log (last 20 attempts per webhook).

---

### 1.5.5 — Saved Batch Profiles (Versioned)

**Goal:** Bulk run configurations are first-class named artifacts, not throwaway settings.

**Changes:**

1. **Profile persistence**  
   `BatchProfile(id, name, languages, mode, template, description, created_date, version_history)`. Saved to `%LOCALAPPDATA%\DevDocsDownloader\profiles\{id}.json`. `GET/POST/PUT/DELETE /profiles` endpoints.

2. **Profile versioning**  
   On `PUT /profiles/{id}`, append current version to `version_history` (last 10) before overwriting. Each history entry: `{saved_date, languages, description}`. UI shows "Version history" dropdown with restore.

3. **`BulkPage` redesign**  
   Profile-centric UI: left panel = profile list (saved + one "unsaved" working config). Center = language list with drag-to-reorder. Right = output and schedule settings. "Save as profile" persists current working config.

4. **Profile auto-scheduling**  
   Each profile can have `schedule_id`. Creating a scheduled profile run creates the schedule automatically. `BulkPage` shows "Run now" and "Scheduled: daily 03:00" per profile.

---

### 1.6.0 — Automation Milestone Release

**Summary of what ships:**
- Cron-based job scheduler with configurable expressions.
- Windows toast notifications (completion, failure, schedule).
- Per-language cache and refresh policy overrides.
- Webhook output triggers with HMAC signing and delivery logging.
- Named, versioned batch profiles with scheduling support.

---

## 1.7.0 — "Extensibility & Plugins"

**Theme:** Third parties and power users build on the platform. Custom sources, custom conversion logic, post-processing hooks: documented, stable, safe.

**Done when:**
- A developer can implement a `DocumentationSource` plugin and install it without touching core code.
- Plugin API versioned and documented with stability guarantees.
- Custom conversion profiles creatable and testable without code changes.
- Pre/post run scripts supported.

---

### 1.6.1 — Plugin Protocol Stabilization

**Goal:** Freeze and document the entry point interface.

**Changes:**

1. **`documentation/plugin_api.md`**  
   Covers: entry point group `devdocsdownloader.sources`, required protocol (`name`, `list_languages`, `fetch`, `events`), recommended `DocumentationSourceBase` class, required packaging (setuptools entry point declaration), stability guarantees through 2.0.0.

2. **Plugin loader improvements**  
   `SourceRegistry._load_entry_point_sources()` currently silently skips bad plugins. Add validation: a loaded plugin missing required methods raises a clear error naming the missing method and plugin package. Log successful plugin loads at `INFO` level with plugin name and version.

3. **Plugin sandboxing (basic)**  
   Wrap plugin `fetch()` calls with timeout (default 5 minutes, configurable). If `fetch()` doesn't yield first document within `plugin_first_document_timeout_seconds`, fail job with clear timeout error naming the plugin.

---

### 1.6.2 — Plugin Manager in Desktop

**Goal:** Users see installed plugins and configure them from UI.

**Changes:**

1. **`GET /plugins` endpoint**  
   Returns installed source plugins: name, version, package, source count, status (active/disabled/errored). Errors include load-time failure message.

2. **`PluginsPage` in desktop**  
   New nav entry "Plugins". Lists installed plugins. Allows disabling (adds to `disabled_plugins` list in settings). Shows plugin-provided `description` and `homepage`.

3. **Plugin configuration pass-through**  
   Plugin factory receives `PluginConfig(settings_dict)` populated from `DesktopSettings.plugin_configs: dict[str, dict]` keyed by plugin name. `PluginsPage` renders a generic key-value editor per plugin config.

---

### 1.6.3 — Custom Conversion Profile Editor

**Goal:** Power users tune CSS selectors and noise filters without editing files.

**Changes:**

1. **`ConversionProfile` model**  
   `ConversionProfile(name, base_profile, content_selectors, noise_selectors, post_processors)`. `post_processors`: list of `PostProcessor(type: Literal["strip_regex", "replace_regex", "prepend_text", "append_text"], pattern, replacement)`. Persisted to `%LOCALAPPDATA%\DevDocsDownloader\conversion_profiles\{name}.json`.

2. **Profile tester**  
   `POST /conversion-profiles/test` accepts `{profile_name, html_sample}`, returns resulting markdown. Desktop profile editor: HTML input left, Markdown preview right, re-renders as selectors are edited.

3. **Profile assignment**  
   `RunLanguageRequest.conversion_profile: str | None`. Language settings gains `conversion_profile` field. Pipeline passes profile to `convert_html_to_markdown()` instead of default.

---

### 1.6.4 — Script Hooks

**Goal:** Pre and post-run scripts allow arbitrary automation.

**Changes:**

1. **Hook configuration**  
   `DesktopSettings.hooks: HookConfig`. `HookConfig(pre_run: str | None, post_run: str | None, on_failure: str | None)`. Each is a path to an executable (`.ps1`, `.bat`, `.py`, `.sh`). Environment variables passed: `DEVDOCS_LANGUAGE`, `DEVDOCS_SOURCE`, `DEVDOCS_OUTPUT_PATH`, `DEVDOCS_DOCUMENT_COUNT`, `DEVDOCS_VALIDATION_SCORE`, `DEVDOCS_RUN_STATUS`.

2. **Hook execution in `services.py`**  
   Pre-run hook: 60s timeout; non-zero exit aborts job. Post-run hook: runs after success, non-zero logged as warning. On-failure hook: runs after failure. Hook stdout/stderr logged to `logs/hooks.log`.

3. **Hook management in settings**  
   `SettingsPage` → Hooks: file pickers per hook type. "Test hook" runs with dummy environment variables, shows stdout/stderr in dialog.

---

### 1.6.5 — Plugin & Extension Documentation

**Goal:** External developers have everything needed to build a production-quality source plugin.

**Changes:**

1. **`documentation/plugin_development_guide.md`**  
   Step-by-step: scaffold plugin package, implement `DocumentationSourceBase`, test against mock `SourceRuntime`, register entry point, package and distribute on PyPI. Includes complete working example (`ExampleWikiSource`).

2. **`documentation/conversion_profile_guide.md`**  
   CSS selector tuning methodology: find content roots with browser devtools, remove noise elements, test profiles, contribute profiles back to `dash_profiles.json` or `web_sources.json`.

3. **`documentation/api_stability.md`**  
   Defines stable modules (`sources/base.py` protocol, `models.py` public classes, `services.py` public methods) vs. unstable (compiler internals, validator internals, `adaptive.py`). Promise kept until 3.0.0.

---

### 1.7.0 — Extensibility Milestone Release

**Summary of what ships:**
- Stable, documented, validated plugin loading system.
- Plugin Manager page in desktop with per-plugin configuration.
- Custom conversion profile editor with live preview.
- Pre/post run script hooks with env variable context.
- Complete plugin development guide, conversion profile guide, API stability policy.

---

## 1.8.0 — "Performance & Scale"

**Theme:** System handles large corpora (100+ languages, MDN at full size, 50+ Dash docsets) without degrading. Memory bounded. Network usage minimal. Response time stays fast under all workloads.

**Done when:**
- Compiling 100 languages in parallel does not OOM on an 8GB machine.
- Incremental recompile (only changed documents) works correctly.
- Concurrency defaults tuned from real benchmark data.
- FTS search returns results in <50ms for largest realistic corpus.

---

### 1.7.1 — Streaming Pipeline Writes

**Goal:** Peak memory is O(one document), not O(total corpus).

**Changes:**

1. **True streaming in `compiler.py`**  
   `LanguageOutputBuilder` moves to generator-pull model. Consolidated `.md` file opened once at compilation start; `flush_document(doc)` appends immediately and releases the markdown string. Per-document files written on `flush_document()` instantly. Chunk files written per-document, not batched at end.

2. **HTML site streaming**  
   `html_site.generate()` streams HTML generation one document at a time. `index.html` built from header template + streaming document list + footer template. Never loads all markdown into memory at once.

3. **FTS indexer streaming**  
   `Indexer.index_language()` processes documents one at a time from filesystem. SQLite `executemany()` in batches of 100 rows.

---

### 1.7.2 — Parallel Source Fetching with Fair Scheduling

**Goal:** Multiple sources fetched in parallel, no source starving others.

**Changes:**

1. **Fair-share scheduler**  
   `run_many()` with languages from multiple sources: each source gets a fair share of global concurrency limit. With limit=4 and DevDocs + Dash queued: 2 slots each. Prevents slow Dash tarball downloads blocking fast DevDocs fetches. Implemented via per-source `asyncio.Semaphore`.

2. **Priority classes**  
   `RunManyRequest` languages gain `priority: Literal["high", "normal", "low"] = "normal"`. High-priority languages front of queue. Low-priority yield to normal/high when both waiting. Presets can specify per-language priority.

3. **Download rate limiting**  
   `SourceRuntime` gains `max_bandwidth_mbps: float | None = None`. Token bucket rate limiter on response body reads enforces limit globally. Metered connections can set e.g. 5 Mbps for background refreshes.

---

### 1.7.3 — Incremental Compilation

**Goal:** When only some documents changed, recompile only those.

**Changes:**

1. **Change detection**  
   During fetch, compute `sha256(document.markdown)` before writing. Compare against hash in `manifest.json` from last run. Hash matches = unchanged; hash differs or new = changed.

2. **Selective recompile**  
   With `incremental: bool = True` in `RunLanguageRequest`: only changed documents written. Consolidated `.md` rebuilt by reading unchanged documents from disk and appending changed ones. FTS index updated only for changed documents.

3. **Incremental chunking**  
   Only chunks for changed documents regenerated. Unchanged chunk files left on disk. Incremental mode is O(changed_docs) not O(total_docs).

4. **UI opt-in**  
   `RunPage` and scheduled jobs default to incremental if a prior run exists. "Force full recompile" checkbox overrides. Incremental mode shows "N documents changed, M skipped" in run log.

---

### 1.7.4 — Tiered Caching System

**Goal:** Hot data in memory; warm data on disk; cold data cleared on TTL.

**Changes:**

1. **Memory cache tier in `SourceRuntime`**  
   `LRUCache(max_entries=50, max_bytes=50 * 1024 * 1024)` for recently fetched catalog entries and small JSON responses. Keyed by URL + ETag. Bypassed for large responses (>1MB). Prevents re-reading DevDocs `index.json` from disk on every fetch when the same language compiles multiple times per session.

2. **Disk cache cold tier**  
   Add `cold/` subdirectory per source: entries older than `cold_threshold_days` (default 30) moved there by background maintenance task. `cold/` entries accessed on miss but not surfaced in `CachePage` summary counts. "Show cold storage" toggle in `CachePage` reveals them.

3. **Cache maintenance task**  
   `BackendJobManager` starts `CacheMaintenanceTask` at startup: runs every 24 hours, evicts entries beyond budget, moves stale entries to cold, computes usage summary. Written to `cache/_maintenance_log.json`.

---

### 1.7.5 — Concurrency Benchmarks & Tuned Defaults

**Goal:** Default settings empirically derived, tuning process documented.

**Changes:**

1. **`scripts/benchmark_concurrency.py`**  
   Runs pipeline with varying concurrency (1, 2, 4, 6, 8) against a fixed set of languages from cached data. Records wall time, peak memory, network bytes, document count, validation score. Outputs JSON report. Not in test runner — run manually before milestone releases.

2. **Tuned defaults**  
   From benchmarks targeting a 4-core, 8GB RAM machine: update `LanguageConcurrency` default in `DesktopSettings`, adaptive controller min/max, HTTP semaphore limits. Document results in `documentation/performance_benchmarks.md`.

3. **Auto-tune in settings**  
   `SettingsPage` → Performance → "Auto-tune" button: runs benchmark script against 3 test languages, sets optimal defaults from machine's actual performance. Progress shown as running job.

---

### 1.8.0 — Performance Milestone Release

**Summary of what ships:**
- Streaming writes eliminating OOM risk entirely.
- Fair-share parallel source fetching.
- Incremental compilation (only changed documents rebuilt).
- Tiered caching (LRU memory + cold disk tier + maintenance task).
- Empirical concurrency benchmarks published, tuned defaults, auto-tune button.

---

## 1.9.0 — "UX & Polish"

**Theme:** Desktop app is a pleasure to use. Navigation fast and keyboard-driven. New users guided through initial setup. Interface communicates state clearly. Accessibility is not an afterthought.

**Done when:**
- Every primary user flow completable entirely via keyboard.
- New users compile their first language within 5 minutes of installing.
- Interface readable under high-DPI, light, and dark themes.
- App updates itself without user downloading a new installer.

---

### 1.8.1 — UI Design Refresh

**Goal:** Consistent visual language, better information density, dark mode.

**Changes:**

1. **Design system in code**  
   Extract colors, spacing, typography from `MainWindow.xaml.cs` into `DesignSystem.cs`. All inline `ColorHelper.FromArgb(...)` replaced with `DesignSystem.Surface`, `DesignSystem.Accent`, `DesignSystem.Text`, etc. Global design changes become one-line edits.

2. **Light and dark theme support**  
   `SettingsPage` → Appearance → Theme toggle (System / Light / Dark). Stored in settings. Use `Microsoft.UI.Xaml.ElementTheme` to propagate through WinUI tree. Validate WCAG AA contrast ratios in both themes.

3. **Visual hierarchy improvements**  
   - Sidebar: nav buttons get Segoe MDL2 / Fluent System Icons glyphs. Language labels capped with ellipsis and hover tooltip. Active job card collapses to compact single-line when idle.
   - Pages: consistent header (page title, subtitle, right-aligned action buttons). Content areas use `ScrollViewer` where content can overflow. Tables use `DataGrid` instead of `StackPanel` lists.
   - Status semantics: blue=running, green=complete, yellow=warning, red=failed, gray=idle — consistent everywhere (job status, quality scores, source health, notification dots).

---

### 1.8.2 — Full Keyboard Navigation

**Goal:** Every action reachable without a mouse.

**Changes:**

1. **Global keyboard shortcuts**  
   `Ctrl+1` through `Ctrl+9`: navigate to pages 1–9. `Ctrl+F`: focus search bar. `Ctrl+R`: run current language from `RunPage`. `Ctrl+Shift+R`: bulk run active profile from `BulkPage`. `Ctrl+,`: open settings. `F5`: refresh active page data. `Escape`: dismiss flyout/dialog. Reference displayed in `SettingsPage` → Keyboard.

2. **Tab order audit**  
   Walk every page; all interactive elements in logical tab order. Fix mouse-only elements by adding `IsTabStop=True` and `AutomationProperties.Name`.

3. **List navigation**  
   `LanguagesPage`: Up/Down moves selection, Enter runs, Space toggles for bulk. `OutputBrowserPage`: arrow navigation in file tree, Enter opens, Delete deletes.

---

### 1.8.3 — Onboarding Wizard

**Goal:** New users compile their first language in one session.

**Changes:**

1. **First-run detection**  
   Check `DesktopSettings.first_run_completed: bool`. If false, show onboarding overlay on `RunPage`.

2. **4-step wizard**  
   - Step 1: "Welcome" — app overview, key capabilities.
   - Step 2: "Set output folder" — file picker for `output_dir`, shows disk space.
   - Step 3: "Pick your first language" — simplified picker (top 20 by popularity: Python, JavaScript, TypeScript, Rust, Go, etc.).
   - Step 4: "Run" — triggers dry-run preview for selected language, shows estimated document count, then prompts "Download now?" Full run on confirmation.
   On completion: `first_run_completed = true`.

3. **Contextual hints**  
   After onboarding, show dismissible hints (one per session) for key features: "Did you know you can schedule automatic refreshes?" / "Try searching with Ctrl+F." / "Set up webhooks to push to your AI pipeline." Shown as non-intrusive info bar atop relevant pages.

---

### 1.8.4 — Settings Profiles & Workspaces

**Goal:** Users with multiple use cases switch contexts cleanly.

**Changes:**

1. **Settings profiles**  
   `SettingsProfile(id, name, settings_snapshot)`. Persisted to `%LOCALAPPDATA%\DevDocsDownloader\profiles\settings\`. `SettingsPage` header shows "Current profile: [name]" with dropdown. Creating a new profile copies current settings. Switching profiles reloads all settings.

2. **Workspace concept**  
   A workspace combines settings profile + active batch profile + output directory root. Switching workspace changes all three atomically. Workspaces listed in dropdown in sidebar header.

3. **Export/import settings**  
   "Export settings" in `SettingsPage` produces sanitized JSON file (no tokens or secrets) for sharing or backup. "Import settings" loads that file, prompts to create a new profile from it. Useful for team standardization.

---

### 1.8.5 — In-App Update Mechanism

**Goal:** App updates itself without users visiting GitHub.

**Changes:**

1. **Update checker**  
   On startup and every 24h: `GET https://api.github.com/repos/{owner}/{repo}/releases/latest`. Compare `tag_name` to current version. If newer: show "Update available: vN.N.N" banner in sidebar.

2. **Update downloader**  
   "Download & Install" button in update dialog:
   - `GET` the installer asset URL from the release JSON.
   - Download to `%TEMP%\DevDocsDownloader-Setup-{version}.exe`.
   - Verify SHA256 against `SHA256SUMS.txt` from the release.
   - Launch installer with `/SILENT` flag.
   - Close the app (installer relaunches after completion).

3. **Update settings**  
   `SettingsPage` → Updates: "Check automatically" toggle, "Check now" button, "Skip this version" (suppresses banner for current latest).

---

### 1.8.6 — Comprehensive Help System & Accessibility

**Goal:** Every feature explained in-app. Accessibility requirements met.

**Changes:**

1. **In-app help**  
   `SettingsPage` → Help tab: searchable FAQ, links to online documentation, diagnostic tools (copy logs, run health check, show version info). Each page has a `?` header button opening a contextual help flyout explaining page purpose and key actions.

2. **Accessibility audit**  
   - All images and icons: `AutomationProperties.Name`.
   - All interactive controls: accessible names set.
   - Color never the only means of conveying information (patterns or text labels alongside all color indicators).
   - Focus always visible (`FocusVisualKind.Reveal` or custom).
   - All text meets WCAG AA contrast in both light and dark themes.
   - Tested with Narrator (Windows built-in screen reader).

3. **Diagnostic report**  
   `SettingsPage` → Help → "Copy diagnostic report": app version, OS version, settings (redacted), last 50 log lines, source health status, queue status, memory usage — formatted as text block for bug reports.

---

### 1.9.0 — UX & Polish Milestone Release

**Summary of what ships:**
- Unified design system with light/dark theme support and consistent status semantics.
- Full keyboard navigation across all pages with global shortcuts.
- Onboarding wizard for new users.
- Settings profiles and workspaces.
- In-app automatic updater with SHA256 verification.
- Help system with contextual page help and full accessibility audit.

---

## 2.0.0 — "Premium Release"

**Theme:** Everything in one place, stable, signed, documented, ready for the world.

**Done when:**
- All 1.x milestone features stable and passing their test suites.
- Installer code-signed.
- Public documentation complete and hosted.
- Performance benchmarks published.
- Plugin API frozen.
- Upgrade guide exists for users coming from 1.x.

---

### 1.9.1 — Code Signing & Distribution Hardening

**Changes:**

1. **Authenticode signing**  
   Sign `DevDocsDownloader.Desktop.exe` and installer with EV code signing certificate. Configure GitHub Actions to retrieve certificate from a GitHub secret and sign during release workflow. Signed artifacts suppress Windows SmartScreen warnings entirely.

2. **SHA256SUMS verification hardening**  
   Verify `SHA256SUMS.txt` is GPG-detached-signed before trusting checksums. Public key bundled in installer, used by auto-updater.

3. **Auto-update rollback**  
   If app fails to start after an update (detected by update-tracking file), next installer run offers "Rollback to prior version." Prior installer cached in `%LOCALAPPDATA%\DevDocsDownloader\update_backup\`.

---

### 1.9.2 — Performance Regression Testing

**Changes:**

1. **Benchmark suite in CI**  
   `scripts/benchmark_regression.py`: runs against fixed set of cached docsets (no live downloads), asserts compilation time < baseline × 1.2, peak memory < baseline × 1.1, FTS search < 50ms. Baselines stored in `tests/performance_baselines.json`. CI fails on regression.

2. **Memory profile in tests**  
   `tests/test_memory_pressure.py` uses `tracemalloc` to verify compiling largest test fixtures does not exceed 150MB peak allocation. Guards against regression to pre-streaming-write behavior.

---

### 1.9.3 — Documentation Complete

All `documentation/` files reviewed, updated, consistent with 2.0.0 feature set:

1. **`architecture.md`** — Updated for streaming pipeline, tiered cache, plugin system, scheduler, search indexer, webhook system. Sequence diagrams for main flows.

2. **`plugin_api.md`** — Finalized API contract, marked stable through 3.0.0.

3. **`output_contract.md`** — Updated with template system outputs, multi-format files, `manifest.json` schema, `validation.json` schema, chunk frontmatter fields.

4. **`user_guide.md`** (new) — End-user guide: installation, onboarding, first run, scheduling, search, output formats, troubleshooting. No source code knowledge required.

5. **`developer_guide.md`** (new) — Source code orientation, architecture decisions, how to add a new source, how to write tests, how to contribute.

6. **`performance_benchmarks.md`** — Published benchmark results from 1.7.5 and 1.9.2, methodology, hardware spec, tuning guidance for different machine classes.

7. **`changelog.md`** — Complete changelog from 1.0.0 to 2.0.0, one entry per release.

---

### 1.9.4 — Beta Program & Release Candidate

**Changes:**

1. **Public beta**  
   Tag `2.0.0-beta.1`. Announce on GitHub Discussions. Collect structured feedback. Address P1 bugs in `2.0.0-beta.2` and `2.0.0-beta.3`.

2. **Release candidate**  
   Tag `2.0.0-rc.1` after beta issues resolved. Bug fixes only — no new features. RC period minimum 2 weeks. Promote to `2.0.0` when no P1/P2 bugs open for 7 consecutive days.

---

### 2.0.0 — Final Release

**What the user gets:**
- Premium documentation intelligence platform covering all documentation needs.
- Ingestion from 4 sources (DevDocs, MDN, Dash, WebPage) with pre-download intelligence and quality scoring.
- Output in 3 formats (Markdown, HTML site, EPUB) with 4 built-in templates and full Jinja2 customization.
- Semantic chunking for RAG pipelines with rich chunk frontmatter.
- Full-text and semantic search over all compiled output with cross-reference indexing.
- Cron-based scheduling with Windows notifications and webhook outputs.
- Stable plugin API for custom source adapters and conversion profiles.
- Streaming pipeline with incremental compilation and tiered caching.
- Professional WinUI 3 desktop: keyboard navigation, dark mode, onboarding, auto-update.
- Code-signed installer — no SmartScreen warnings.
- Complete user guide, developer guide, plugin API reference, performance benchmarks.

---

## Summary Table

| Milestone | Theme | Key Deliverables |
|-----------|-------|-----------------|
| **1.2.0** | Rock-Solid Foundation | Streaming writes, MDN delta, job queue, cache UI, dry-run, content hashing, circuit breaker |
| **1.3.0** | Source Excellence | Conditional GET, Dash intelligence, web crawl source, per-source quality metrics, source health |
| **1.4.0** | Output Intelligence | Semantic chunking, run versioning, link validation, templates, HTML site output |
| **1.5.0** | Search & Discovery | SQLite FTS5, global search UI, cross-reference index, semantic search, favorites & recents |
| **1.6.0** | Automation & Scheduling | Cron scheduler, toast notifications, webhooks, saved profiles, per-language policies |
| **1.7.0** | Extensibility & Plugins | Stable plugin API, plugin manager, conversion profile editor, script hooks, full docs |
| **1.8.0** | Performance & Scale | Streaming pipeline, fair scheduling, incremental compilation, tiered cache, benchmarks |
| **1.9.0** | UX & Polish | Design refresh, keyboard nav, onboarding, settings profiles, auto-update, accessibility |
| **2.0.0** | Premium Release | Signed installer, regression tests, complete documentation, beta program |

---

## Patch Version Map

| Patch | Parent milestone | Focus |
|-------|-----------------|-------|
| 1.1.2 | → 1.2.0 | Catalog-driven language selection and source dropdowns |
| 1.1.3 | → 1.2.0 | Streaming writes, MDN delta, circuit breaker |
| 1.1.4 | → 1.2.0 | Job queue and actionable error messaging |
| 1.1.5 | → 1.2.0 | Cache management UI, cache budgets, and dry-run previews |
| 1.1.6 | → 1.2.0 | Test coverage expansion |
| 1.1.7 | → 1.2.0 | Resume hardening and checkpoint integrity |
| 1.2.1 | → 1.3.0 | Conditional GET caching |
| 1.2.2 | → 1.3.0 | Dash pre-download intelligence |
| 1.2.3 | → 1.3.0 | Per-docset conversion profiles |
| 1.2.4 | → 1.3.0 | WebPageSource adapter |
| 1.2.5 | → 1.3.0 | Source health dashboard |
| 1.2.6 | → 1.3.0 | Per-source quality metrics |
| 1.3.1 | → 1.4.0 | Semantic chunking |
| 1.3.2 | → 1.4.0 | Output versioning & diff view |
| 1.3.3 | → 1.4.0 | Advanced validation (link checking, integrity) |
| 1.3.4 | → 1.4.0 | Per-document quality scores in desktop |
| 1.3.5 | → 1.4.0 | Jinja2 template system |
| 1.3.6 | → 1.4.0 | Static HTML site generation |
| 1.4.1 | → 1.5.0 | SQLite FTS5 index |
| 1.4.2 | → 1.5.0 | Search UI in desktop |
| 1.4.3 | → 1.5.0 | Cross-reference index |
| 1.4.4 | → 1.5.0 | Semantic search (optional embeddings) |
| 1.4.5 | → 1.5.0 | Favorites & recents |
| 1.5.1 | → 1.6.0 | Job scheduler (cron) |
| 1.5.2 | → 1.6.0 | Windows toast notifications |
| 1.5.3 | → 1.6.0 | Per-language auto-refresh policies |
| 1.5.4 | → 1.6.0 | Webhook output triggers |
| 1.5.5 | → 1.6.0 | Saved batch profiles (versioned) |
| 1.6.1 | → 1.7.0 | Plugin protocol stabilization |
| 1.6.2 | → 1.7.0 | Plugin manager in desktop |
| 1.6.3 | → 1.7.0 | Custom conversion profile editor |
| 1.6.4 | → 1.7.0 | Script hooks |
| 1.6.5 | → 1.7.0 | Plugin & extension documentation |
| 1.7.1 | → 1.8.0 | Streaming pipeline writes |
| 1.7.2 | → 1.8.0 | Parallel fair-share scheduling |
| 1.7.3 | → 1.8.0 | Incremental compilation |
| 1.7.4 | → 1.8.0 | Tiered caching system |
| 1.7.5 | → 1.8.0 | Concurrency benchmarks & tuned defaults |
| 1.8.1 | → 1.9.0 | UI design refresh & dark mode |
| 1.8.2 | → 1.9.0 | Full keyboard navigation |
| 1.8.3 | → 1.9.0 | Onboarding wizard |
| 1.8.4 | → 1.9.0 | Settings profiles & workspaces |
| 1.8.5 | → 1.9.0 | In-app auto-update mechanism |
| 1.8.6 | → 1.9.0 | Help system & accessibility audit |
| 1.9.1 | → 2.0.0 | Code signing & distribution hardening |
| 1.9.2 | → 2.0.0 | Performance regression testing |
| 1.9.3 | → 2.0.0 | Complete documentation |
| 1.9.4 | → 2.0.0 | Beta program & release candidate |

---

## Known Risks & Dependencies

| Risk | Mitigation |
|------|-----------|
| DevDocs changes structure of `docs.json` or `db.json` | Catalog caching + fallback; structured error on schema mismatch; monitor DevDocs releases |
| MDN tarball URL changes or moves | Abstract URL to config constant; version-pinnable via settings override |
| Kapeli scrape breaks (HTML changes) | Fall back to cached catalog; alert in source health dashboard |
| `sentence-transformers` model size grows | Version-pin model; allow user to choose alternative via settings |
| WinUI 3 / WindowsAppSDK breaking changes | Pin SDK version; review release notes on each upgrade; test on new WinUI releases |
| EV code signing certificate expires | Annual renewal reminder in release checklist; expiry tracked in CI |
| Plugin API needs breaking changes before 2.0.0 | Breaking changes only at minor version boundaries; 2-version deprecation window |
| SQLite FTS5 index grows too large for slow HDD | FTS index lives in output dir alongside content; user can exclude it; compression option |

---

## What Stays Out of Scope (Through 2.0.0)

- **Multi-user / server mode:** Desktop-first, single-user throughout.
- **Cloud sync:** Compiled output is local; users sync via own tools.
- **macOS / Linux desktop app:** CLI and Python library stay cross-platform; WinUI 3 shell is Windows-only.
- **Built-in AI summarization:** Output feeds AI pipelines; summarization is downstream.
- **Documentation generation** (Sphinx, Doxygen): Ingestion of existing docs only, not generation from source code.
- **Paid features / licensing:** Open-source through 2.0.0.
