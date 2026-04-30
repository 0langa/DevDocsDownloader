# DevDocsDownloader — Roadmap to 2.0.0

> **Current release:** 1.3.0  
> **Document scope:** All planned work from 1.2.0 through the 2.0.0 premium release.  
> **Last updated:** 2026-04-30

---

## Vision: What 2.0.0 Looks Like

DevDocsDownloader 2.0.0 is a **premium documentation intelligence platform** for power users, developers, and AI engineers who need high-quality, structured, richly formatted documentation available offline and on-demand.

By 2.0.0 the product:

- Ingests from every major documentation source with measurable quality confidence.
- Produces output in multiple formats (Markdown, HTML site, PDF, EPUB, chunked vector-ready JSON) with full customization over structure, style, detail level, and content depth.
- Indexes every compiled document for instant full-text and semantic search, accessible directly inside the app.
- Automates recurring documentation pulls on user-defined schedules with smart refresh policies.
- Ships with a first-class, keyboard-navigable, accessible desktop application with dark mode, onboarding, in-app help, and automatic updates.
- Is extensible via a stable plugin API so users and third-party developers can add new sources, custom conversion pipelines, and post-processing hooks.
- Handles corpora of any scale — from one language to hundreds — without memory pressure, using streaming compilation and tiered caching.
- Produces traceable, versioned output: every run is recorded, differences between runs are browsable, and rolling back to a prior version of compiled docs is a single click.
- Is code-signed, installer-distributed, and professionally documented.

---

## Milestone Philosophy

Each **minor version** (1.2.0, 1.3.0, …) is a named major milestone with a clear theme and a concrete "done" definition. The **patch versions** between milestones (1.1.5, 1.1.6, …) are focused, releasable increments that each add one meaningful capability or fix one meaningful class of problem. No patch version is a grab-bag.

Every patch version:
- Passes all existing tests plus any new tests written for its changes.
- Does not break the output contract.
- Ships with updated release notes.
- Maintains backward compatibility with existing settings, checkpoints, and compiled output.

---

## Architecture Baseline (v1.1.1)

Before planning forward, an honest accounting of current state.

**What works well:**
- Source adapter pattern (DevDocs, MDN, Dash) with clean protocol boundaries.
- Async pipeline with cooperative cancellation and SSE streaming.
- Checkpoint/resume system with per-document boundary tracking.
- FastAPI desktop backend with job history, health monitoring, and SSE reconnection.
- WinUI 3 desktop shell with 9 pages, real-time job tracking, and observable ViewModel.
- 113+ passing tests across integration, contract, and phase-level suites.
- Weighted validation scoring across 5 quality dimensions.

**Critical gaps going into 1.2.0:**
- Streaming writes now cap compilation memory near one document, but HTML site / future secondary outputs still need the same treatment.
- MDN now uses commit-SHA delta checks and archive indexing, but archive scans are still serial and can remain slow on very large refreshes.
- No job queue; desktop returns 409 if the user tries to run while another job is active.
- Empty `doc_key` in DevDocs single-page manuals (bash, etc.) emitted 0 documents until 1.0.9.2 fix — similar edge cases may exist elsewhere.
- Conversion quality is uneven; no per-source conversion profile tuning exposed to users.
- Validation catches structural issues but does not check link existence or document integrity hashes.
- Resume logic checks that artifact paths exist, not that their content is uncorrupted.
- No cache management UI; users cannot inspect or clear the cache from the desktop app.
- Dash docsets are downloaded blind — no way to know docset size or quality before committing.
- Dry-run mode absent; users cannot sanity-check source resolution before a full download.

---

## 1.2.0 — "Rock-Solid Foundation"

**Theme:** Eliminate correctness issues, reduce resource waste, make the system trustworthy under adverse conditions, and close the most frustrating usability gaps before building new features on top.

**Done when:**
- No job is ever silently lost due to OOM, process restart, or conflicting state.
- The MDN refresh path does not visibly stall the UI.
- The desktop app never returns 409 to a user trying to start a run.
- Cache management is accessible and usable from the desktop shell.
- All core conversion functions have unit tests.
- Checkpoint resume verifies content, not just file existence.

---

### 1.1.2 — Catalog-Driven Language Selection & Source Dropdowns

**Goal:** Replace error-prone free-text inputs with catalog-backed dropdowns. Make "download everything" a single click.

**Status:** ✅ Done

**Delivered:**
- Run page source input switched to catalog-backed dropdown.
- Bulk page switched to searchable multi-select from live `/languages` catalog.
- Added version filtering (`Latest only` / `All versions`) for suggestions and `Download all`.
- Added one-click `Download all` that fills selection and starts bulk run.
- Bulk source dropdown added and wired end-to-end.
- Added `BulkRunRequest.source` and passed through to pipeline source resolution.

---

### 1.1.3 — Streaming Pipeline & MDN Efficiency

**Goal:** Prevent OOM for large docsets. Make MDN refresh non-blocking.

**Status:** ✅ Done

**Delivered:**
- Compiler switched to streaming writes to keep memory near one-document scale.
- MDN tarball handling moved to incremental archive scan and on-demand member reads.
- MDN refresh now checks upstream commit SHA and skips unchanged large downloads.
- Added per-domain runtime circuit breaker for repeated upstream failures.
- Added adaptive memory-pressure guard that drops concurrency under high RAM pressure.

---

### 1.1.4 — Job Queue & Error Messaging

**Goal:** Never tell the user "busy, try again." Make error messages actionable.

**Status:** ✅ Done

**Delivered:**
- Added bounded backend job queue with pending-position updates (`Queued (position N)`), plus `/jobs/queue`.
- Standardized structured `SourceError` payloads (`code`, `message`, `hint`, `is_retriable`) through pipeline and backend events.
- Desktop shell now surfaces failure hints via `LastErrorHint` in a dedicated warning block.
- Validation issues now include actionable `suggestion` text, rendered in Reports.

---

### 1.1.5 — Cache Management Desktop UI

**Goal:** Users can see, understand, and clean up cached source data without touching the filesystem.

**Status:** ✅ Done

**Delivered:**
- Implemented full Cache page with per-source summaries, per-entry actions, source clear, and full clear.
- Added cache budget setting and enforcement (`cache_budget_exceeded`) with UI budget visibility.
- Added dry-run pipeline/service path and desktop `Preview` workflow.

---

### 1.1.6 — Test Coverage Expansion

**Goal:** Converter functions, adapter edge cases, and backend job logic all have unit tests.

**Status:** ✅ Done

**Delivered:**
- Added focused unit suites for conversion, cache policies/metadata, and adaptive concurrency behavior.
- Added backend job lifecycle tests for queueing, cancellation, and SSE replay.
- Added mocked adapter tests for 404/corrupt/empty payload edge cases.

---

### 1.1.7 — Resume Hardening & Checkpoint Integrity

**Goal:** A resumed run never silently skips or duplicates content.

**Status:** ✅ Done

**Delivered:**
- Added content hashes to checkpoint artifacts and resume-time hash validation with rollback to last verified artifact.
- Switched checkpoint persistence to atomic write/replace.
- Added stale checkpoint detection/listing/deletion and desktop stale-cleanup action.
- Added checkpoint schema versioning with safe discard on mismatch.

---

### 1.2.0 — Foundation Milestone Release

**Status:** ✅ Done

**Delivered:**
- Streaming compilation (OOM risk eliminated).
- MDN delta detection (no redundant 500MB downloads).
- Circuit breaker on all external HTTP calls.
- Job queue (no more 409 conflicts).
- Specific error codes and actionable hints in UI.
- Full `CachePage` with usage tracking, eviction controls, and budget enforcement.
- Dry-run preview mode.
- Content-hashed checkpoint resume.
- Atomic checkpoint writes.
- Comprehensive unit test suite for converters, cache, adaptive, adapters, and job lifecycle.

---

## 1.3.0 — "Source Excellence"

**Theme:** Every source adapter is high-confidence, self-reporting, and quality-measurable. Users see what they are getting before committing to a download. New sources expand coverage to single-page manuals and curated offline archives.

**Done when:**
- Dash docsets have pre-download size and quality hints.
- Conditional GET caching reduces unnecessary network traffic by >80% for unchanged content.
- A direct web crawl source adapter handles single-page manuals (GNU bash.html, POSIX spec, etc.).
- Every source has a per-source quality confidence metric visible in the language browser.
- Source health is continuously monitored and surfaced in the desktop UI.

---

### 1.2.1 — Conditional GET Caching

**Goal:** Honor `ETag` / `Last-Modified` headers to skip downloads when content has not changed.

**Status:** ✅ Done

**Delivered:**
- Added conditional runtime requests with `If-None-Match` / `If-Modified-Since` and `NotModifiedResponse` handling.
- Wired conditional behavior into DevDocs dataset fetches and Dash docset refresh flow.
- Activated `validate-if-possible` policy to perform conditional validation instead of fallback no-op.

---

### 1.2.2 — Dash Pre-Download Intelligence

**Status:** ✅ Done

**Goal:** Show users what they are getting before downloading a Dash docset.

**Changes:**

1. **Dash metadata probe**  
   Before downloading a full `.tgz`, `HEAD https://kapeli.com/feeds/{slug}.tgz`. Parse `Content-Length`. Store in `DashDocsetMeta(slug, tgz_size_bytes, last_modified)`. Expose via `LanguageCatalog.discovery_metadata["tgz_size_bytes"]`.

2. **Parallel catalog enrichment**  
   During `DashFeedSource.list_languages()`, fire HEAD requests for each docset in parallel (bounded semaphore, 10 concurrent). Cache size hints in the catalog manifest. Populate `LanguageCatalog.size_hint` from `tgz_size_bytes`.

3. **Size warnings in desktop UI**  
   `LanguagesPage` shows size badges next to Dash entries: "3 MB", "42 MB", "120 MB". `RunPage` shows a size warning modal for docsets >50 MB: "This docset is approximately N MB. Continue?" (dismissible permanently per-language).

4. **Docset quality heuristic**  
   After downloading a Dash docset, record indexed entry count, document count, and conversion success rate. On subsequent catalog loads, compute `confidence`: `high` (many entries, >90% conversion success), `medium`, `low`. Show confidence badge on `LanguagesPage` for entries with prior download history.

---

### 1.2.3 — Per-Docset Conversion Profiles

**Status:** ✅ Done

**Goal:** Improve Dash conversion quality for specific docsets; expose tunable profiles.

**Changes:**

1. **Dash conversion profile registry**  
   Add `dash_profiles.json` to `doc_ingest/sources/`. Format: `{ "Ruby": { "content_selectors": [...], "noise_selectors": [...] } }`. `DashFeedSource` loads and passes the matching profile to `convert_html_to_markdown()`. Falls back to `DASH_PROFILE` if no entry exists.

2. **Self-improving profile inference**  
   After each Dash docset fetch, record which CSS selectors successfully found content roots vs. which fell back to `body`. Persist per-docset in cache metadata. Next fetch uses the previously successful selectors as the primary profile. Self-improving heuristic without manual tuning.

3. **Profile editor in advanced settings**  
   `SettingsPage` → "Conversion Profiles" sub-section. Table of known profiles with editable selector lists. Users can add custom selectors, test against a cached HTML sample, and save. "Test" action fetches one document from the cached docset, applies the profile, and shows resulting markdown in a split-view preview panel.

---

### 1.2.4 — Direct Web Crawl Source Adapter

**Status:** ✅ Done

**Goal:** Ingest single-page manuals (GNU bash, POSIX spec, Python docs) directly from the web.

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
   For single-document sources: fetch the URL, extract sections using `section_selector` to split into individual `Document` objects (one per top-level heading). Each heading + its content = one document. Slug = heading text slugified. Turns a 500KB single-page manual into ~30 structured documents.

3. **Multi-page crawl support (bounded)**  
   For sources with `crawl_links: true` and `allowed_path_prefix`: after fetching the entry page, extract `<a href>` links within the prefix, deduplicate, and fetch in order (bounded to `max_pages: 200`). Each page yields one or more documents. Persist crawl state to checkpoint so incomplete crawls resume.

4. **Caching strategy**  
   Full page content cached in `cache/web_page/{slug}/`. Metadata tracks `Last-Modified`/`ETag` from server. TTL-based refresh applies; 7-day default TTL for pages with no caching headers.

5. **Registration**  
   `WebPageSource` registered in `SourceRegistry` after Dash in priority. Resolution order: `devdocs → mdn → dash → web_page`.

---

### 1.2.5 — Source Health Dashboard

**Status:** ✅ Done

**Goal:** Surface real-time source availability and quality in the desktop.

**Changes:**

1. **`GET /sources/health` endpoint**  
   Per-source status: `{ "devdocs": { "status": "ok", "last_checked": "...", "catalog_age_hours": 2.1, "circuit_breaker": "closed" }, "mdn": { "status": "ok", "commit_sha": "abc123" }, "dash": { "status": "degraded", "reason": "429 at 14:32" }, "web_page": { "status": "ok" } }`.

2. **Source health indicator in sidebar**  
   Small colored dot per source (green/yellow/red) below the app title. Hovering shows the detail from `/sources/health`. Red = circuit breaker open or last probe failed. Yellow = degraded or stale catalog. Green = all checks passing.

3. **Catalog staleness warnings**  
   If a source catalog is >7 days old (configurable), show a warning in `LanguagesPage` for that source: "DevDocs catalog is 8 days old. Refresh?" with one-click refresh.

---

### 1.2.6 — Per-Source Quality Metrics

**Status:** ✅ Done

**Goal:** Every compiled language has a measurable quality score that informs future source selection.

**Changes:**

1. **Historical quality tracking**  
   After each successful run, store `SourceQualityRecord(source, slug, run_date, document_count, topics, validation_score, conversion_success_rate, skip_rate)` in `logs/quality_history.jsonl`. `list_output_bundles()` enriches bundle metadata with the latest quality record.

2. **Source quality comparison**  
   When multiple sources can serve the same language, `registry.py resolve()` ranks by latest `validation_score` from `quality_history.jsonl`. Users can override source preference in `RunLanguageRequest`. `LanguagesPage` shows preferred source with a "change source" dropdown for multi-source languages.

3. **Quality history in `ReportsPage`**  
   Sparkline of validation scores over the last 10 runs per language. Shows quality trend (improving / stable / degrading) at a glance.

---

### 1.3.0 — Source Excellence Milestone Release

**Status:** ✅ Done

**Summary of what ships:**
- Conditional GET caching eliminating redundant downloads.
- Dash pre-download size and quality intelligence with confidence badges.
- Per-docset Dash conversion profiles with user-editable overrides.
- `WebPageSource` adapter for single-page manuals (bash, POSIX, etc.).
- Source health dashboard in desktop sidebar.
- Historical quality tracking with trend view in reports.

---

## 1.4.0 — "Output Intelligence"

**Theme:** Compiled output is richer, more flexible, verifiable, and version-tracked. Users get multiple output formats, control over structure and style, and the ability to track how documentation evolves across runs.

**Done when:**
- Chunking is heading-aware and semantically coherent.
- At least two additional output formats (HTML site, EPUB) are stable.
- Every compiled document has an integrity hash.
- The desktop shows per-document quality scores inline.
- Run output is versioned; diffs between runs are browsable.

---

### 1.3.1 — Semantic Chunking

**Goal:** Produce chunks that respect document structure rather than splitting on arbitrary character counts.

**Changes:**

1. **Heading-aware chunk splitter**  
   `ChunkStrategy.semantic` (new value alongside `chars` and `tokens`). The splitter walks rendered markdown, identifies heading boundaries (`##`, `###`), and creates chunks that:
   - Never split inside a code block.
   - Never split between a heading and its first paragraph.
   - Respect `chunk_max_chars` as a soft limit (will exceed it up to 1.5× to avoid splitting mid-section).
   - Group H3 sections under their parent H2 if combined size is under the limit.
   - Prepend `<!-- chunk: N/T -->\n# Section Title\n` to each chunk for orientation context.

2. **Overlap preservation**  
   Where the next chunk starts with an H3, prepend the parent H2 heading text (not full content) to provide hierarchy context for vector embedding without doubling content.

3. **Chunk metadata in frontmatter**  
   When `emit_document_frontmatter: true`, chunk files gain: `chunk_index`, `chunk_total`, `parent_slug`, `parent_heading`, `section_heading`. Makes chunks self-describing for RAG pipelines.

---

### 1.3.2 — Output Versioning

**Goal:** Every run's output is traceable; differences between runs are browsable.

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
   `content_sha256` is the SHA256 of the concatenated per-document hashes (deterministic aggregate).

2. **Run history archive**  
   Before overwriting output, move current `manifest.json` to `output/{language}/.history/{run_date_iso}.json`. Keep last 10 manifests (configurable). Content files not archived (too large); only the manifest is. Records what was in each past run without doubling storage.

3. **Diff view in desktop**  
   `ReportsPage` gains a "Compare runs" mode. Selecting two historical manifests shows: documents added, documents removed, documents changed (where `sha256` differs). Summary: `+N documents, -N documents, ~N documents changed`.

---

### 1.3.3 — Advanced Validation (Link Checking & Integrity)

**Goal:** Validation catches more real problems; integrity hashes make tampering detectable.

**Changes:**

1. **Per-document integrity hashes**  
   `validate_documents()` computes `sha256(document_markdown)` for each document and stores results in `ValidationResult.document_hashes: dict[str, str]`. State store includes hashes. In validate-only mode, if output exists and hashes match, skip re-download.

2. **Internal link validation**  
   `_check_links()` (new function in `validator.py`): extract all `[text](link)` references. For relative links (no `https://`, no `dash://`): verify target file exists in the language output directory. For anchor links (`#heading`): verify the heading exists in the current file. Report `broken_internal_link` issue for each failure.

3. **HTML artifact detection improvement**  
   Current regex `<[a-zA-Z]+[^>]*>` is too aggressive. Replace with targeted check for structural artifacts only: `<div`, `<span`, `<table`, `<p>` — run through a simple state machine rather than a broad regex. Reduce false positives from Markdown table syntax.

4. **Validation report export**  
   Write machine-readable `output/{language}/validation.json` alongside markdown after each run. Includes: `composite_score`, per-component scores, all issues with file paths and line numbers. Consumable by CI pipelines or external tools.

---

### 1.3.4 — Per-Document Quality Scores in Desktop

**Goal:** Quality information is visible at the document level, not just aggregate.

**Changes:**

1. **`GET /output/{language}/validation` endpoint**  
   Returns `validation.json` for a language. Includes per-document scores if `validate_documents()` ran.

2. **`OutputBrowserPage` quality indicators**  
   Colored dot beside each document in the file tree: green (score ≥0.8), yellow (0.5–0.8), red (<0.5). Hovering shows the top issue for that document (e.g., "3 relative links, 1 HTML artifact").

3. **Report summary improvements**  
   `ReportsPage`: composite score as a large number with trend arrow (↑/↓ vs last run), breakdown by component with bars, top 5 issues across all documents with counts, lowest-scoring documents listed at bottom with links to open them in `OutputBrowserPage`.

---

### 1.3.5 — Template System for Output Customization

**Goal:** Users control exactly how compiled output is structured and formatted.

**Changes:**

1. **Jinja2 template engine**  
   Add `doc_ingest/templates/`. Templates are `.md.j2` files. Context: `{{ language }}`, `{{ source }}`, `{{ documents }}` (list of `{title, slug, markdown, topic, source_url}`), `{{ run_date }}`, `{{ mode }}`. Applied per-document and for the consolidated file.

2. **Bundled templates**  
   - `default.md.j2` — Current behavior, no change to existing output.
   - `detailed.md.j2` — Adds source URL, topic, run date as frontmatter per document. Table of contents at top of consolidated file.
   - `minimal.md.j2` — Strips all frontmatter and metadata; pure content only. Optimized for LLM context window injection.
   - `api-reference.md.j2` — Groups documents by topic, sorts alphabetically within each group, adds index section at top with anchor links per topic.

3. **Template selection**  
   `DesktopSettings.output_template: str = "default"`. `SettingsPage` shows a template dropdown with preview. `RunLanguageRequest.template: str | None` overrides global setting per-run.

4. **Custom template directory**  
   Users place `.md.j2` files in `%LOCALAPPDATA%\DevDocsDownloader\templates\`. These appear in the template dropdown alongside built-ins.

---

### 1.3.6 — Multi-Format Output: HTML Site

**Goal:** Compiled documentation available as a navigable static HTML website.

**Changes:**

1. **HTML site generator in `doc_ingest/formats/html_site.py`**  
   Given a compiled language directory, produces `_site/{language}/`:
   - `index.html` — navigable table of contents (topic groups, alphabetical links per document).
   - `{slug}.html` — each document rendered as HTML with syntax highlighting (highlight.js bundled as static asset).
   - `_site/assets/` — CSS (clean, minimal, dark-mode-capable), JS (highlight.js, search index loader).
   - `search-index.json` — client-side JS full-text search within the site.

2. **HTML format option in `RunLanguageRequest`**  
   `output_formats: list[Literal["markdown", "html", "epub"]] = ["markdown"]`. When `"html"` is included, `services.py` calls `html_site.generate()` after successful markdown compilation. HTML generated from compiled markdown, not re-fetched from source.

3. **HTML site browser in desktop**  
   `OutputBrowserPage` adds "Open as website" button for languages with `_site/`. Clicking opens `index.html` in the default browser.

---

### 1.4.0 — Output Intelligence Milestone Release

**Summary of what ships:**
- Semantic heading-aware chunking with orientation context and hierarchy-aware overlap.
- Per-run manifest with document-level integrity hashes.
- Run history with diff-view in `ReportsPage`.
- Internal link validation and improved HTML artifact detection.
- Machine-readable `validation.json` export.
- Per-document quality scores in `OutputBrowserPage`.
- Jinja2 template system with 4 built-in templates and user custom templates.
- Static HTML site generation.

---

## 1.5.0 — "Search & Discovery"

**Theme:** Every compiled document is instantly findable. The app is the user's documentation interface, not just a download tool. Search, cross-referencing, and instant access make the compiled output useful day-to-day.

**Done when:**
- Full-text search across all compiled output returns results in under 100ms for most queries.
- Cross-reference index links related APIs across languages.
- Semantic (embedding) search is available as opt-in.
- Favorites and recently accessed are tracked and surfaced.

---

### 1.4.1 — SQLite FTS5 Index

**Goal:** Build a full-text search index over all compiled output.

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
   `services.py run_language()` calls `Indexer.index_language(language_dir)` after successful compile. Reads all `*.md` files (excluding chunks), strips frontmatter, inserts/replaces rows. Run in background thread via `asyncio.to_thread()` so it does not block SSE events.

3. **`GET /search?q={query}&limit=20&language={optional}` endpoint**  
   FTS5 query with snippet extraction. Returns: language, slug, title, topic, file path, highlighted excerpt. Response target: <100ms.

---

### 1.4.2 — Search UI in Desktop

**Goal:** Instant search from anywhere in the app.

**Changes:**

1. **Global search bar in sidebar**  
   Above nav buttons. Typing triggers a debounced (300ms) `GET /search`. Results appear in a flyout panel. Pressing Enter navigates to the top result.

2. **Search results display**  
   Each result: language name, document title, topic tag, 2-line excerpt with query terms bolded. Clicking a result navigates to `OutputBrowserPage` with that file selected and opened in the content preview pane.

3. **Keyboard navigation**  
   `Ctrl+F` focuses search bar. `↑`/`↓` navigate results. `Esc` dismisses. `Enter` opens top result.

4. **Search within document**  
   `OutputBrowserPage` content preview gets `Ctrl+G`: highlights all occurrences of the search term, scrolls to first, `F3`/`Shift+F3` cycle through.

---

### 1.4.3 — Cross-Reference Index

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
   When a document is open, a collapsible "Related" section at the bottom lists up to 10 cross-reference hits for the most prominent identifiers in the current document.

---

### 1.4.4 — Semantic Search (Optional Embeddings)

**Goal:** Similarity-based search for users who install the optional embedding dependency.

**Changes:**

1. **`doc_ingest/embedder.py` — optional module**  
   Guarded by `try: import sentence_transformers`. Listed in `pyproject.toml` under `[project.optional-dependencies] semantic = ["sentence-transformers>=2,<4"]`. Uses `all-MiniLM-L6-v2` by default (~80MB).

2. **Vector storage in SQLite**  
   `documents` table gains `embedding BLOB`. On indexing (if embedder available), compute and store embeddings. `GET /search/semantic?q={query}&limit=10` computes query embedding, runs cosine similarity, returns top-N results. Falls back to FTS5 with `X-Search-Mode: fts5` response header if embedder not installed.

3. **Desktop opt-in**  
   `SettingsPage` → "Enable semantic search" toggle. First enable: "This will download a ~80MB model." Progress tracked via `POST /search/setup-embeddings`. After setup, search results show "Keyword" / "Semantic" tab toggle.

---

### 1.4.5 — Favorites & Recents

**Goal:** Frequently accessed documents and languages are one click away.

**Changes:**

1. **Favorites system**  
   `output/_search/favorites.json`. `OutputBrowserPage` has a star button per document. Starred documents appear in a "Favorites" section at top of the file tree. `GET /favorites` and `POST /favorites` endpoints.

2. **Recents tracking**  
   Every document opened in `OutputBrowserPage` recorded in `output/_search/recents.json` (last 50, deduped by language+slug). Collapsible "Recent" section in sidebar shows last 5 with language and title.

3. **Quick-launch dashboard on `RunPage`**  
   On startup, show 3 most recently compiled languages as quick-action cards: language, last run date, document count, validation score indicator, one-click "Refresh" button.

---

### 1.5.0 — Search & Discovery Milestone Release

**Summary of what ships:**
- SQLite FTS5 index over all compiled output.
- Global search bar in sidebar with full keyboard shortcuts.
- Cross-reference index linking related APIs across languages.
- Opt-in semantic search with local embedding model.
- Favorites and recents with quick-launch dashboard.

---

## 1.6.0 — "Automation & Scheduling"

**Theme:** Documentation stays fresh automatically. Users define refresh policies, schedules, and notification preferences. Running a refresh is optional — the app does it for you.

**Done when:**
- A language can have a configured refresh schedule that runs without user interaction.
- Windows toast notifications fire on job completion and failure.
- Webhook outputs notify external systems when docs change.
- Batch profiles are saved, versioned, and schedulable.

---

### 1.5.1 — Job Scheduler

**Goal:** Cron-like scheduling for recurring documentation refreshes.

**Changes:**

1. **`ScheduledJobStore`** persists schedules to `%LOCALAPPDATA%\DevDocsDownloader\schedules.json`. Each entry: `{id, language_or_preset, cron_expression, mode, last_run, next_run, enabled}`. Background `Scheduler` coroutine wakes every 60 seconds, checks `next_run` for all enabled schedules, and submits due jobs to the queue. `cron_expression` supports standard 5-field cron syntax (`0 3 * * *` = daily at 3am).

2. **`GET/POST/DELETE /schedules` endpoints**  
   CRUD for schedules. `POST /schedules` validates cron expression and returns computed `next_run`. `SettingsPage` → Schedules tab: list all schedules with add/edit/delete.

3. **Next-run indicator on `RunPage`**  
   Language quick-action cards show "Next refresh: Tuesday 03:00" if a schedule is configured.

---

### 1.5.2 — Windows Toast Notifications

**Goal:** Users know when a job completes without watching the app.

**Changes:**

1. **`NotificationService` in C# shell**  
   Uses `Windows.UI.Notifications.ToastNotificationManager`. Triggered by job status change events in `MainWindowViewModel`. Template: "DevDocsDownloader — Python 3.12 ready — 412 documents compiled." Action buttons: "Open" (navigates to `OutputBrowserPage`) and "Dismiss".

2. **Notification preferences**  
   `SettingsPage` → Notifications: toggles for "Notify on job complete", "Notify on job failure", "Notify on scheduled refresh". All default to `true`.

3. **In-app notification history**  
   Bell icon in sidebar header. Last 20 notifications in memory; clicking opens a dropdown with "Clear all".

---

### 1.5.3 — Per-Language Auto-Refresh Policies

**Goal:** Each language has its own cache freshness and refresh policy independent of global settings.

**Changes:**

1. **`LanguageSettings` store**  
   `LanguageSettings(slug, source, cache_policy, cache_ttl_hours, auto_refresh_schedule_id, output_template, preferred_mode)`. Persisted in `%LOCALAPPDATA%\DevDocsDownloader\language_settings.json`. `GET/PATCH /language-settings/{slug}` endpoints.

2. **Inheritance model**  
   Global settings → per-language settings override → request-level override. Desktop sends per-language settings when submitting a scheduled run.

3. **Settings UI on `LanguagesPage`**  
   Selecting a language opens a detail panel (right column) with: source info, last compiled, quality score, and per-language cache policy, TTL, and auto-refresh schedule.

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
   On `PUT /profiles/{id}`, append current version to `version_history` (last 10) before overwriting. Each history entry: `{saved_date, languages, description}`. UI shows "Version history" dropdown with restore capability.

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

**Theme:** Third parties and power users can build on the platform. Custom sources, custom conversion logic, and post-processing hooks are documented, stable, and safe.

**Done when:**
- A developer can implement a `DocumentationSource` plugin and install it without touching core code.
- The plugin API is versioned and documented with stability guarantees.
- Custom conversion profiles can be created and tested without code changes.
- Pre/post run scripts are supported.

---

### 1.6.1 — Plugin Protocol Stabilization

**Goal:** Freeze and document the entry point interface.

**Changes:**

1. **`documentation/plugin_api.md`**  
   Covers: entry point group `devdocsdownloader.sources`, required protocol (`name`, `list_languages`, `fetch`, `events`), recommended `DocumentationSourceBase` class, required packaging (setuptools entry point declaration), stability guarantees through 2.0.0.

2. **Plugin loader improvements**  
   `SourceRegistry._load_entry_point_sources()` currently silently skips bad plugins. Add validation: if a loaded plugin is missing required methods, raise a clear error naming the missing method and the plugin package. Log successful plugin loads at `INFO` level with plugin name and version.

3. **Plugin sandboxing (basic)**  
   Wrap plugin `fetch()` calls with a timeout (default 5 minutes, configurable). If `fetch()` doesn't yield the first document within `plugin_first_document_timeout_seconds`, fail the job with a clear timeout error naming the plugin.

---

### 1.6.2 — Plugin Manager in Desktop

**Goal:** Users see installed plugins and configure them from the UI.

**Changes:**

1. **`GET /plugins` endpoint**  
   Returns installed source plugins: name, version, package, source count, status (active/disabled/errored). Errors include the failure message from load time.

2. **`PluginsPage` in desktop**  
   New nav entry "Plugins". Lists installed plugins. Allows disabling (adds to `disabled_plugins` list in settings). Shows plugin-provided `description` and `homepage`.

3. **Plugin configuration pass-through**  
   Plugin factory receives `PluginConfig(settings_dict)` populated from `DesktopSettings.plugin_configs: dict[str, dict]` keyed by plugin name. `PluginsPage` renders a generic key-value editor for each plugin's config.

---

### 1.6.3 — Custom Conversion Profile Editor

**Goal:** Power users tune CSS selectors and noise filters without editing files.

**Changes:**

1. **`ConversionProfile` model**  
   `ConversionProfile(name, base_profile, content_selectors, noise_selectors, post_processors)`. `post_processors`: list of `PostProcessor(type: Literal["strip_regex", "replace_regex", "prepend_text", "append_text"], pattern, replacement)`. Persisted to `%LOCALAPPDATA%\DevDocsDownloader\conversion_profiles\{name}.json`.

2. **Profile tester**  
   `POST /conversion-profiles/test` accepts `{profile_name, html_sample}`, returns resulting markdown. Desktop profile editor: HTML input on left, Markdown preview on right, re-renders as selectors are edited.

3. **Profile assignment**  
   `RunLanguageRequest.conversion_profile: str | None`. Language settings gains `conversion_profile` field. Pipeline passes the profile to `convert_html_to_markdown()` instead of the default.

---

### 1.6.4 — Script Hooks

**Goal:** Pre and post-run scripts allow arbitrary automation.

**Changes:**

1. **Hook configuration**  
   `DesktopSettings.hooks: HookConfig`. `HookConfig(pre_run: str | None, post_run: str | None, on_failure: str | None)`. Each is a path to an executable (`.ps1`, `.bat`, `.py`, `.sh`). Environment variables passed: `DEVDOCS_LANGUAGE`, `DEVDOCS_SOURCE`, `DEVDOCS_OUTPUT_PATH`, `DEVDOCS_DOCUMENT_COUNT`, `DEVDOCS_VALIDATION_SCORE`, `DEVDOCS_RUN_STATUS`.

2. **Hook execution in `services.py`**  
   Pre-run hook: executed with 60s timeout; non-zero exit aborts job. Post-run hook: executed after success, non-zero logged as warning. On-failure hook: executed after failure. Hook stdout/stderr logged to `logs/hooks.log`.

3. **Hook management in settings**  
   `SettingsPage` → Hooks: file pickers for each hook type. "Test hook" runs with dummy environment variables, shows stdout/stderr in a dialog.

---

### 1.6.5 — Plugin & Extension Documentation

**Goal:** External developers have everything needed to build a production-quality source plugin.

**Changes:**

1. **`documentation/plugin_development_guide.md`**  
   Step-by-step: scaffold a plugin package, implement `DocumentationSourceBase`, test against a mock `SourceRuntime`, register the entry point, package and distribute on PyPI. Includes a complete working example (`ExampleWikiSource`).

2. **`documentation/conversion_profile_guide.md`**  
   CSS selector tuning methodology: find content roots using browser devtools, remove noise elements, test profiles, contribute profiles back to `dash_profiles.json` or `web_sources.json`.

3. **`documentation/api_stability.md`**  
   Defines which modules are stable (`sources/base.py` protocol, `models.py` public classes, `services.py` public methods) vs. unstable (compiler internals, validator internals, `adaptive.py`). Promise kept until 3.0.0.

---

### 1.7.0 — Extensibility Milestone Release

**Summary of what ships:**
- Stable, documented, validated plugin loading system.
- Plugin Manager page in desktop with per-plugin configuration.
- Custom conversion profile editor with live preview.
- Pre/post run script hooks with env variable context.
- Complete plugin development guide, conversion profile guide, and API stability policy.

---

## 1.8.0 — "Performance & Scale"

**Theme:** The system handles large corpora (100+ languages, MDN at full size, 50+ Dash docsets) without degrading. Memory usage is bounded. Network usage is minimal. Response time stays fast under all workloads.

**Done when:**
- Compiling 100 languages in parallel does not OOM on an 8GB machine.
- Incremental recompile (only changed documents) works correctly.
- Concurrency defaults are tuned from real benchmark data.
- FTS search returns results in <50ms for the largest realistic corpus.

---

### 1.7.1 — Streaming Pipeline Writes

**Goal:** Peak memory usage is O(one document), not O(total corpus).

**Changes:**

1. **True streaming in `compiler.py`**  
   `LanguageOutputBuilder` moves to generator-pull model. The consolidated `.md` file is opened once at compilation start; `flush_document(doc)` appends immediately and releases the markdown string. Per-document files written on `flush_document()` instantly. Chunk files written per-document, not batched at end.

2. **HTML site streaming**  
   `html_site.generate()` streams HTML generation one document at a time. `index.html` built from header template + streaming document list + footer template. Never loads all markdown into memory at once.

3. **FTS indexer streaming**  
   `Indexer.index_language()` processes documents one at a time from the filesystem. SQLite `executemany()` in batches of 100 rows.

---

### 1.7.2 — Parallel Source Fetching with Fair Scheduling

**Goal:** Multiple sources fetched in parallel without any one source starving the others.

**Changes:**

1. **Fair-share scheduler**  
   `run_many()` with languages from multiple sources: assign each source a fair share of the global concurrency limit. With limit=4 and DevDocs + Dash languages queued: 2 slots each. Prevents slow Dash tarball downloads from blocking fast DevDocs fetches. Implemented via per-source `asyncio.Semaphore`.

2. **Priority classes**  
   `RunManyRequest` languages gain `priority: Literal["high", "normal", "low"] = "normal"`. High-priority languages front of queue. Low-priority yield to normal/high when both waiting. Presets can specify per-language priority.

3. **Download rate limiting**  
   `SourceRuntime` gains `max_bandwidth_mbps: float | None = None`. Token bucket rate limiter on response body reads enforces this limit globally. Users with metered connections can set e.g. 5 Mbps for background refreshes.

---

### 1.7.3 — Incremental Compilation

**Goal:** When only some documents changed, recompile only those documents.

**Changes:**

1. **Change detection**  
   During fetch, compute `sha256(document.markdown)` before writing. Compare against hash in `manifest.json` from the last run. Documents where hash matches = unchanged; hash differs or new = changed.

2. **Selective recompile**  
   When `incremental: bool = True` in `RunLanguageRequest`: only changed documents are written. Consolidated `.md` rebuilt by reading unchanged documents from disk and appending changed ones. FTS index updated only for changed documents.

3. **Incremental chunking**  
   Only chunks for changed documents are regenerated. Unchanged chunk files left on disk. Incremental mode is O(changed_docs) not O(total_docs).

4. **UI opt-in**  
   `RunPage` and scheduled jobs default to incremental if a prior run exists. "Force full recompile" checkbox overrides. Incremental mode shows "N documents changed, M skipped" in the run log.

---

### 1.7.4 — Tiered Caching System

**Goal:** Hot data stays in memory; warm data on disk; cold data cleared on TTL.

**Changes:**

1. **Memory cache tier in `SourceRuntime`**  
   `LRUCache(max_entries=50, max_bytes=50 * 1024 * 1024)` for recently fetched catalog entries and small JSON responses. Keyed by URL + ETag. Bypassed for large responses (>1MB). Prevents re-reading DevDocs `index.json` from disk on every fetch when the same language is compiled multiple times in one session.

2. **Disk cache cold tier**  
   Add `cold/` subdirectory per source: entries older than `cold_threshold_days` (default 30) moved there by a background maintenance task. `cold/` entries accessed on miss but not surfaced in `CachePage` summary counts. "Show cold storage" toggle in `CachePage` reveals them.

3. **Cache maintenance task**  
   `BackendJobManager` starts `CacheMaintenanceTask` at startup: runs every 24 hours, evicts entries beyond budget, moves stale entries to cold, computes usage summary. Written to `cache/_maintenance_log.json`.

---

### 1.7.5 — Concurrency Benchmarks & Tuned Defaults

**Goal:** Default settings are empirically derived and the tuning process is documented.

**Changes:**

1. **`scripts/benchmark_concurrency.py`**  
   Runs the pipeline with varying concurrency (1, 2, 4, 6, 8) against a fixed set of languages from cached data. Records: wall time, peak memory, network bytes, document count, validation score. Outputs JSON report. Not in the test runner — run manually before milestone releases.

2. **Tuned defaults**  
   Based on benchmarks targeting a 4-core, 8GB RAM machine: update `LanguageConcurrency` default in `DesktopSettings`, adaptive controller min/max, HTTP semaphore limits. Document results in `documentation/performance_benchmarks.md`.

3. **Auto-tune in settings**  
   `SettingsPage` → Performance → "Auto-tune" button: runs the benchmark script against 3 test languages, sets optimal defaults based on the machine's actual performance. Progress shown as a running job.

---

### 1.8.0 — Performance Milestone Release

**Summary of what ships:**
- Streaming writes eliminating OOM risk entirely.
- Fair-share parallel source fetching.
- Incremental compilation (only changed documents rebuilt).
- Tiered caching (LRU memory + cold disk tier + maintenance task).
- Empirical concurrency benchmarks published, tuned defaults, and auto-tune button.

---

## 1.9.0 — "UX & Polish"

**Theme:** The desktop application is a pleasure to use. Navigation is fast and keyboard-driven. New users are guided through initial setup. The interface communicates state clearly. Accessibility is not an afterthought.

**Done when:**
- Every primary user flow is completable entirely via keyboard.
- New users can successfully compile their first language within 5 minutes of installing.
- The interface is readable under high-DPI, light, and dark themes.
- The app updates itself without requiring the user to download a new installer.

---

### 1.8.1 — UI Design Refresh

**Goal:** Consistent visual language, improved information density, and dark mode.

**Changes:**

1. **Design system in code**  
   Extract colors, spacing, and typography from `MainWindow.xaml.cs` into `DesignSystem.cs`. All inline `ColorHelper.FromArgb(...)` replaced with `DesignSystem.Surface`, `DesignSystem.Accent`, `DesignSystem.Text`, etc. Makes global design changes one-line edits.

2. **Light and dark theme support**  
   `SettingsPage` → Appearance → Theme toggle (System / Light / Dark). Stored in settings. Use `Microsoft.UI.Xaml.ElementTheme` to propagate through the WinUI tree. Validate WCAG AA contrast ratios in both themes.

3. **Visual hierarchy improvements**  
   - Sidebar: nav buttons get Segoe MDL2 / Fluent System Icons glyphs. Language labels capped with ellipsis and tooltip on hover. Active job card collapses to compact single-line when idle.
   - Pages: consistent header (page title, subtitle, action buttons right-aligned). Content areas use `ScrollViewer` where content can overflow. Tables use `DataGrid` instead of `StackPanel` lists.
   - Status semantics: blue=running, green=complete, yellow=warning, red=failed, gray=idle — consistent everywhere (job status, quality scores, source health, notification dots).

---

### 1.8.2 — Full Keyboard Navigation

**Goal:** Every action reachable without a mouse.

**Changes:**

1. **Global keyboard shortcuts**  
   `Ctrl+1` through `Ctrl+9`: navigate to pages 1–9. `Ctrl+F`: focus search bar. `Ctrl+R`: run current language from `RunPage`. `Ctrl+Shift+R`: bulk run active profile from `BulkPage`. `Ctrl+,`: open settings. `F5`: refresh active page data. `Escape`: dismiss flyout/dialog. Reference displayed in `SettingsPage` → Keyboard.

2. **Tab order audit**  
   Walk every page; ensure all interactive elements are in logical tab order. Fix mouse-only elements by adding `IsTabStop=True` and `AutomationProperties.Name`.

3. **List navigation**  
   `LanguagesPage`: Up/Down to move selection, Enter to run, Space to toggle for bulk. `OutputBrowserPage`: arrow navigation in file tree, Enter to open, Delete to delete.

---

### 1.8.3 — Onboarding Wizard

**Goal:** New users successfully compile their first language in one session.

**Changes:**

1. **First-run detection**  
   Check `DesktopSettings.first_run_completed: bool`. If false, show onboarding overlay on `RunPage`.

2. **4-step wizard**  
   - Step 1: "Welcome" — app overview, key capabilities.
   - Step 2: "Set output folder" — file picker for `output_dir`, shows disk space.
   - Step 3: "Pick your first language" — simplified picker (top 20 by popularity: Python, JavaScript, TypeScript, Rust, Go, etc.).
   - Step 4: "Run" — triggers a dry-run preview for the selected language, shows estimated document count, then prompts "Download now?" Full run on confirmation.
   On completion: `first_run_completed = true`.

3. **Contextual hints**  
   After onboarding, show dismissible hints (one per session) for key features: "Did you know you can schedule automatic refreshes?" / "Try searching with Ctrl+F." / "Set up webhooks to push to your AI pipeline." Shown as a non-intrusive info bar at the top of relevant pages.

---

### 1.8.4 — Settings Profiles & Workspaces

**Goal:** Users with multiple use cases switch contexts cleanly.

**Changes:**

1. **Settings profiles**  
   `SettingsProfile(id, name, settings_snapshot)`. Persisted to `%LOCALAPPDATA%\DevDocsDownloader\profiles\settings\`. `SettingsPage` → header shows "Current profile: [name]" with a dropdown. Creating a new profile copies current settings. Switching profiles reloads all settings.

2. **Workspace concept**  
   A workspace combines: settings profile + active batch profile + output directory root. Switching workspace changes all three atomically. Workspaces listed in a dropdown in the sidebar header.

3. **Export/import settings**  
   "Export settings" in `SettingsPage` produces a sanitized JSON file (no tokens or secrets) for sharing or backup. "Import settings" loads from that file, prompts to create a new profile from it. Useful for team standardization.

---

### 1.8.5 — In-App Update Mechanism

**Goal:** The app updates itself without requiring users to visit GitHub.

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
   `SettingsPage` → Updates: "Check automatically" toggle, "Check now" button, "Skip this version" (suppresses banner for the current latest).

---

### 1.8.6 — Comprehensive Help System & Accessibility

**Goal:** Every feature is explained in-app. Accessibility requirements are met.

**Changes:**

1. **In-app help**  
   `SettingsPage` → Help tab: searchable FAQ, links to online documentation, diagnostic tools (copy logs, run health check, show version info). Each page has a `?` button in the header that opens a contextual help flyout explaining the page's purpose and key actions.

2. **Accessibility audit**  
   - All images and icons: `AutomationProperties.Name`.
   - All interactive controls: accessible names set.
   - Color never the only means of conveying information (patterns or text labels alongside all color indicators).
   - Focus always visible (`FocusVisualKind.Reveal` or custom).
   - All text meets WCAG AA contrast in both light and dark themes.
   - Tested with Narrator (Windows built-in screen reader).

3. **Diagnostic report**  
   `SettingsPage` → Help → "Copy diagnostic report": app version, OS version, settings (redacted), last 50 log lines, source health status, queue status, memory usage — formatted as a text block for bug reports.

---

### 1.9.0 — UX & Polish Milestone Release

**Summary of what ships:**
- Unified design system with light/dark theme support and consistent status semantics.
- Full keyboard navigation across all pages with global shortcuts.
- Onboarding wizard for new users.
- Settings profiles and workspaces.
- In-app automatic updater with SHA256 verification.
- Comprehensive help system with contextual page help and full accessibility audit.

---

## 2.0.0 — "Premium Release"

**Theme:** Everything in one place, stable, signed, documented, and ready for the world.

**Done when:**
- All 1.x milestone features are stable and passing their test suites.
- The installer is code-signed.
- Public documentation is complete and hosted.
- Performance benchmarks are published.
- The plugin API is frozen.
- An upgrade guide exists for users coming from 1.x.

---

### 1.9.1 — Code Signing & Distribution Hardening

**Changes:**

1. **Authenticode signing**  
   Sign `DevDocsDownloader.Desktop.exe` and the installer with an EV code signing certificate. Configure GitHub Actions to retrieve the certificate from a GitHub secret and sign during the release workflow. Signed artifacts suppress Windows SmartScreen warnings entirely.

2. **SHA256SUMS verification hardening**  
   Verify `SHA256SUMS.txt` is GPG-detached-signed before trusting checksums. Public key bundled in the installer and used by the auto-updater.

3. **Auto-update rollback**  
   If the app fails to start after an update (detected by an update-tracking file), the next installer run offers "Rollback to prior version." Prior installer cached in `%LOCALAPPDATA%\DevDocsDownloader\update_backup\`.

---

### 1.9.2 — Performance Regression Testing

**Changes:**

1. **Benchmark suite in CI**  
   `scripts/benchmark_regression.py`: runs against a fixed set of cached docsets (no live downloads), asserts: compilation time < baseline × 1.2, peak memory < baseline × 1.1, FTS search < 50ms. Baselines stored in `tests/performance_baselines.json`. CI fails on regression.

2. **Memory profile in tests**  
   `tests/test_memory_pressure.py` uses `tracemalloc` to verify that compiling the largest test fixtures does not exceed 150MB peak allocation. Guards against regressions to pre-streaming-write behavior.

---

### 1.9.3 — Documentation Complete

All `documentation/` files reviewed, updated, and consistent with 2.0.0 feature set:

1. **`architecture.md`** — Updated to reflect streaming pipeline, tiered cache, plugin system, scheduler, search indexer, webhook system. Sequence diagrams for main flows.

2. **`plugin_api.md`** — Finalized API contract, marked stable through 3.0.0.

3. **`output_contract.md`** — Updated with template system outputs, multi-format files, `manifest.json` schema, `validation.json` schema, chunk frontmatter fields.

4. **`user_guide.md`** (new) — End-user guide: installation, onboarding, first run, scheduling, search, output formats, troubleshooting. No source code knowledge required.

5. **`developer_guide.md`** (new) — Source code orientation, architecture decisions, how to add a new source, how to write tests, how to contribute.

6. **`performance_benchmarks.md`** — Published benchmark results from 1.7.5 and 1.9.2, methodology, hardware spec, guidance on tuning for different machine classes.

7. **`changelog.md`** — Complete changelog from 1.0.0 to 2.0.0, one entry per release.

---

### 1.9.4 — Beta Program & Release Candidate

**Changes:**

1. **Public beta**  
   Tag `2.0.0-beta.1`. Announce on GitHub Discussions. Collect structured feedback. Address P1 bugs in `2.0.0-beta.2` and `2.0.0-beta.3`.

2. **Release candidate**  
   Tag `2.0.0-rc.1` after beta issues resolved. Bug fixes only — no new features. RC period minimum 2 weeks. Promote to `2.0.0` when no P1/P2 bugs are open for 7 consecutive days.

---

### 2.0.0 — Final Release

**What the user gets:**
- A premium documentation intelligence platform that handles all documentation needs.
- Ingestion from 4 sources (DevDocs, MDN, Dash, WebPage) with pre-download intelligence and quality scoring.
- Output in 3 formats (Markdown, HTML site, EPUB) with 4 built-in templates and full customization via Jinja2.
- Semantic chunking for RAG pipelines with rich chunk frontmatter.
- Full-text and semantic search over all compiled output with cross-reference indexing.
- Cron-based scheduling with Windows notifications and webhook outputs.
- Stable plugin API for custom source adapters and conversion profiles.
- Streaming pipeline with incremental compilation and tiered caching.
- Professional WinUI 3 desktop with keyboard navigation, dark mode, onboarding, and auto-update.
- Code-signed installer — no SmartScreen warnings.
- Complete user guide, developer guide, plugin API reference, and performance benchmarks.

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
- **Cloud sync:** Compiled output is local; users sync via their own tools.
- **macOS / Linux desktop app:** CLI and Python library remain cross-platform; WinUI 3 shell is Windows-only.
- **Built-in AI summarization:** Output feeds AI pipelines; summarization is downstream.
- **Documentation generation** (Sphinx, Doxygen): Ingestion of existing docs only, not generation from source code.
- **Paid features / licensing:** Open-source through 2.0.0.
