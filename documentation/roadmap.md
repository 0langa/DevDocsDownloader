# DevDocsDownloader Roadmap

## Current State (v1.0.8)

The project ships as a Windows-native WinUI3 desktop app backed by a frozen Python FastAPI process. The pipeline supports three source adapters (DevDocs, MDN, Dash), a CLI, a legacy NiceGUI GUI, and a loopback HTTP/SSE desktop API. The WinUI shell covers Languages, Run, Bulk Run, Presets, Reports, Output Browser, Checkpoints, Cache, and Settings pages. CI builds an Inno Setup installer and a portable zip on tag push.

### What works
- Source catalog resolution with normalization for special-char language names (C++, C#, F#, Node.js, .NET)
- Streaming SSE job progress from Python backend to WinUI shell without UI freeze
- DPI-aware minimum window size enforcement without infinite resize loop
- Backend process termination on window close (no orphaned exe)
- Checkpoint resume on failed runs; stable output contract with optional chunking and frontmatter
- Adaptive bulk scheduling, cache policies, and per-document validation reports
- GitHub Actions release pipeline producing installer + portable zip + SHA256SUMS

---

## Known Bugs and Limitations

### Critical

**1. Cancel does not stop the active download**
`BackendJobManager.cancel()` calls `task.cancel()` which raises `CancelledError` into the asyncio task. However, the crawler is blocked inside an `httpx` network request with no internal checkpoint. The `CancelledError` cannot interrupt a blocking `await` inside a C-extension network read. The current crawl request completes before the task notices cancellation. Practically: pressing Cancel has no visible effect until the current document finishes downloading.

Root cause: no cooperative cancellation boundary in `DocumentationPipeline._run_language()` or the source adapters. The task cancel propagates only at the next `await` that actually yields — httpx may not yield until the full request is done.

**2. Job history lost on backend restart**
`BackendJobManager.jobs` is in-memory. If the backend process restarts (e.g., crash, kill), the shell still shows the last known job state from the SSE stream (which was also in-memory). On reconnect the shell cannot recover job status. The shell does not currently handle backend restart at all.

**3. SSE reconnection not implemented**
`DesktopBackendClient.StreamJobEventsAsync` opens one SSE stream per job. If the stream disconnects mid-job (network hiccup, backend restart), the shell has no reconnect logic. The job may still be running but the shell shows no further progress.

**4. Backend startup failure not surfaced in UI**
`App.OnLaunched` calls `await MainViewModel.InitializeAsync()` which starts the backend. If the backend fails to start (port conflict, missing exe, crash during health check), the exception propagates to `OnLaunched` and is logged but the UI shows a blank window with no user-facing error dialog.

### High

**5. Single-job queue with no queuing UI**
The backend returns HTTP 409 if a second job is submitted while one is running. The WinUI shell shows an error but provides no queue view, no pending indicator, and no way to see what is blocking. Users must know to wait.

**6. Validation score is not meaningful as a quality signal**
`validate_output()` applies flat `-0.3` per error and `-0.1` per warning against a `1.0` baseline. Large languages with hundreds of valid documents get the same score penalty as tiny broken ones. The score has no denominator tied to document count or source size, so a 2000-document C++ output with one unbalanced code fence scores identically to a 5-document stub with the same fence issue.

**7. Dash source is untested end-to-end**
`DashFeedSource` is included in the registry and listed in the UI, but it has never been exercised in a real desktop release run. The Dash archive format is complex; there may be extraction, slug, or encoding failures that only appear at runtime against real Dash feeds.

**8. Output directory grows unbounded**
There is no retention policy, cleanup UI, or size limit for the output directory. After many runs the output folder accumulates old language folders, chunk exports, and report history with no way to prune from the app.

**9. No backend health monitoring after startup**
The shell polls health once at startup and then assumes the backend is alive forever. If the backend crashes mid-session, the shell silently fails on the next API call with a generic HTTP error rather than prompting the user to restart.

### Medium

**10. Language normalization edge cases**
`_normalise_lang()` covers `++→pp`, `#→sharp`, `.→""`. Missing: `&` (e.g., `HTML & CSS`), version suffixes typed without `~` (e.g., `python3.12`), Unicode non-ASCII names. The `_exact_match` prefix and contains buckets compensate for some cases, but ambiguous user input like `"react native"` or `"vue 3"` may resolve to the wrong version.

**11. Settings changes do not affect in-flight or already-resolved config**
`DesktopSettings` is read at job submission time. Changes to output dir, cache policy, or chunking while a job is running or while catalogs are cached are silently ignored until the next run. There is no visible indication that settings were applied.

**12. No UI feedback for catalog refresh failure**
`/refresh-catalogs` returns a count of refreshed sources. If DevDocs or MDN is unreachable, the endpoint still returns 200 with a partial count. The shell shows a success message even if 0 catalogs refreshed.

**13. Unsigned binary — Windows SmartScreen warning**
The installer and portable zip ship an unsigned exe. First-run users see a SmartScreen warning. This is a distribution friction issue with no workaround short of EV code signing.

**14. PRI file copy in CI is fragile**
The release workflow manually greps for `DevDocsDownloader.Desktop.pri` after msbuild and throws if not found. This is a workaround for `EnableMsixTooling=false` with no MSIX packaging. The search path is `bin/**` which is fragile if the build configuration changes output structure.

**15. Legacy NiceGUI GUI still present**
`doc_ingest/gui/` is a full NiceGUI application that duplicates most of the desktop backend API surface. It adds test fixture infrastructure (`tmp/gui-*`) and is exercised in CI. It was explicitly called out as a migration bridge to be removed after WinUI parity — that point has passed.

### Low

**16. No auto-update**
Users must manually download new releases from GitHub. There is no update check, update notification, or in-app update mechanism.

**17. No export / package output feature**
The Output Browser shows generated Markdown but provides no way to copy, zip, or open the output folder from the UI. Users must navigate to `Documents\DevDocsDownloader\output` manually.

**18. Job event history not paginated**
`BackendJob.events` accumulates all SSE events in memory for the lifetime of the backend process. Long bulk runs with many documents produce very large event lists. The `/jobs/{id}/events?from_index=N` cursor exists but the shell always streams from 0.

---

## Roadmap

### Immediate — v1.0.x patch releases

These are bugs with clear fix paths and no design uncertainty.

#### P1-A: Cooperative cancellation
Add cancellation checkpoints inside `DocumentationPipeline._run_language()`. After each document is fetched and compiled (the `_on_document` callback), check a `CancellationToken`-equivalent passed down from `BackendJobManager`. The simplest form: pass the `asyncio.Task` itself and check `asyncio.current_task().cancelled()` at the top of the compile loop, or use a shared `threading.Event` / asyncio `Event` that the cancel endpoint sets before calling `task.cancel()`. Source adapters that use streaming HTTP responses should close the response early.

Fix boundary: `pipeline._run_language` compile loop → `compile_from_stream` → per-document callback.

#### P1-B: Backend startup error dialog
In `App.OnLaunched`, wrap `await MainViewModel.InitializeAsync()` in a try/catch and show a modal `ContentDialog` with the error message and a "Close" button instead of letting the window sit blank.

#### P1-C: Backend crash detection and reconnect prompt
Add a periodic health ping (every 30s or on next API call failure) in `MainWindowViewModel`. If the backend is unreachable, show a non-blocking banner with a "Restart backend" button.

#### P1-D: Catalog refresh failure feedback
`/refresh-catalogs` should return per-source status (ok/failed) not just a count. The shell should show which sources failed.

---

### Near-term — v1.1.0

#### N1: Remove legacy NiceGUI GUI
Delete `doc_ingest/gui/`, remove the `gui` CLI subcommand, remove NiceGUI from `pyproject.toml` dependencies, and clean up `tmp/gui-*` test fixtures and their CI coverage. The WinUI shell is the supported GUI.

**Risk:** NiceGUI tests cover some DocumentationService paths not covered elsewhere. Audit test coverage before deleting and add CLI/service-level tests for any uncovered paths.

#### N2: Open output folder from UI
Add an "Open folder" button to the Output Browser page that calls `Process.Start("explorer.exe", outputPath)` from the shell.

#### N3: Job queue UI
Replace the 409 error toast with a queued-job indicator. When a job is already running, show a pending badge and allow the user to cancel the queued request or wait. If the backend remains single-job, the shell can simulate queuing locally by holding the request until the active job completes.

#### N4: Output retention / cleanup UI
Add a "Manage storage" view (or settings section) that lists downloaded languages with disk size and last-run date. Allow deleting individual language output folders from the UI.

#### N5: Settings apply/reload feedback
Show which settings are in effect for the current run. After saving settings, display a "Settings saved — will apply to next run" confirmation. If output_dir changes, warn that the previous output folder is not moved.

---

### Medium-term — v1.2.0

#### M1: Language normalization hardening
Extend `_normalise_lang()` to cover:
- Ampersand removal (`HTML & CSS` → `htmlcss`, match `html` family)
- Version suffix with dot (`python3.12` → `python312` or strip suffix and fall back to base family)
- Add an explicit alias table for high-traffic ambiguous names (`"react native"`, `"node"`, `"ts"`, `"js"`, `"py"`)

Add regression tests for all new normalizations against the DevDocs/MDN catalog fixtures.

#### M2: Improved validation scoring
Replace flat deduction scoring with a document-weighted model:
- Base score computed per-document (skipped, failed, warnings relative to discovered count)
- Language-level issues apply to the language score, not per-document score
- Expose separate `structure_score`, `completeness_score`, and `conversion_score` fields
- Keep `score` as the composite for backward compatibility

#### M3: Dash source validation
Run a scoped acceptance test against at least 3 real Dash feeds (e.g., Python, Go, Swift) in CI behind `DEVDOCS_LIVE_EXTRACTION_TESTS=1`. Fix any extraction, slug normalization, or encoding failures found.

#### M4: SSE reconnect in shell
`DesktopBackendClient.StreamJobEventsAsync` should reconnect on stream close if the job is still running. Use `from_index` to resume from the last received event. Add a max-retry limit with exponential backoff.

#### M5: PRI packaging fix
Replace the manual PRI search-and-copy step with a proper MSBuild target or a `Directory.Build.targets` customization that copies the PRI to `PublishDir` as part of the publish step. Remove the grep-and-throw workaround.

---

### Long-term / Post-v1.2.0

#### L1: Code signing
Obtain an EV code signing certificate. Sign the installer and the desktop exe before release. Remove the SmartScreen friction.

#### L2: Auto-update
Add an update check on startup against the GitHub Releases API. Show an in-app banner when a newer version is available with a link to the release page. Do not implement silent auto-install — just notification.

#### L3: Persistent job history
Write job summaries and event snapshots to a local SQLite or JSON-lines file in `%LOCALAPPDATA%\DevDocsDownloader\jobs\`. On backend restart, load recent history. The shell can display the last N jobs with their final status without needing the in-memory event queue.

#### L4: Semantic validation per source
Add source-specific validation rules:
- DevDocs: verify expected topic names from the known catalog topics list
- MDN: verify BCD (Browser Compatibility Data) sections parse without error
- Dash: verify index database entries match emitted documents

#### L5: PDF/DOCX/browser conversion
Reintroduce only when a real adapter with fixture coverage exists. Do not add dependencies speculatively.

#### L6: macOS/Linux support
The Python backend is cross-platform. The WinUI shell is Windows-only. Long-term options:
- Electron or Tauri wrapper around the backend API for macOS/Linux
- Or: ship the CLI + NiceGUI GUI on non-Windows and keep WinUI for Windows

This is speculative until there is concrete user demand.

---

## Architectural Risks

| Risk | Severity | Notes |
|------|----------|-------|
| In-memory job events | Medium | Large bulk runs accumulate all events; no eviction. Mitigated by `from_index` cursor but shell doesn't use it. |
| Single-job backend | Low | Acceptable for desktop use. Becomes a bottleneck if multi-user or scripted use grows. |
| PyInstaller frozen backend | Low | uvicorn bundling is fragile. `--collect-all uvicorn` works today; upstream changes may break it silently. |
| WinUI unpackaged (no MSIX) | Low | No auto-update via Store, no capability sandbox. Reduces distribution options. |
| Backend token in process args | Low | Token visible in `ps`/Task Manager on the local machine. Acceptable for loopback-only use. |
| Devdocs.io catalog API | Low | `DevDocsSource` fetches `https://devdocs.io/docs.json` on each catalog refresh. If devdocs.io changes its API, the source fails silently on the cached fallback until TTL expires. |
