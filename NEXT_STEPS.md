# DevDocsDownloader — Status & Roadmap
_Portfolio audit: 2026-07-11_

## What this is
A documentation ingestion platform: a Python 3.11 pipeline (`doc_ingest/`) that resolves language
docs from four sources (`devdocs`, `mdn`, `dash`, `web_page` under `doc_ingest/sources/`),
compiles validated Markdown bundles with manifests and quality scores, emits optional HTML/EPUB,
and indexes everything for FTS5 + optional semantic search (`doc_ingest/indexer.py`,
`doc_ingest/embedder.py`). A WinUI 3 (.NET 8) desktop shell
(`desktop/DevDocsDownloader.Desktop/`) drives a bundled FastAPI backend
(`doc_ingest/desktop_backend.py`) with job queue, cache management, reports, and output browsing.
CLI entry is `DevDocsDownloader.py` / `doc_ingest/cli.py`.

## Current state
The flagship repo: 114 commits, 21 tags, released v1.5.0 on 2026-05-01 with tag-driven releases
(`.github/workflows/release.yml` shipping Setup exe, Portable zip, SHA256SUMS). CI is real
(`ci.yml`: pytest with 27 test files, ruff check + format, mypy, version and release-hygiene
checks) plus a `live-drift.yml` probe for upstream changes. The roadmap
(`documentation/roadmap.md`, 1,316 lines) is exceptional: milestones 1.2.0 through 1.5.0 are all
delivered as specified; remaining are 1.6.0 (Automation), 1.7.0 (Plugins), 1.8.0
(Performance/Scale), 1.9.0 (UX/Polish), and 2.0.0 (signed premium release). No work has landed
since the 1.5.0 README refresh (~10 weeks idle).

Loose ends observed:
- `documentation/development_progress.md` still opens with "Current state summary (v1.2.0)" —
  three milestones out of date.
- Working tree noise: modified `.claude/settings.local.json` and an untracked `.kimi/` directory.
- The app is unsigned, so SmartScreen warnings gate real adoption until 1.9.1/2.0.0 work.

## Definition of "finished"
2.0.0 as defined in `documentation/roadmap.md`: scheduling/notifications/webhooks (1.6.0), a
stable documented plugin API (1.7.0), streaming/incremental performance at scale (1.8.0),
keyboard-complete accessible UX with auto-update (1.9.0), then code signing, regression
benchmarks, complete docs, and a beta program (2.0.0). A pragmatic nearer-term "finished" is
1.6.0 + code signing pulled forward, which makes it a daily-driver tool for others.

## Roadmap

### Phase 1 — Now (next 1-2 weeks)
- Re-enter the project: update `documentation/development_progress.md` to the 1.5.0 reality and
  clean the working tree (`.claude/settings.local.json`, decide whether `.kimi/` is ignored).
- Start milestone 1.6.0 with 1.5.1 Job Scheduler exactly as specced: `ScheduledJobStore`
  persisting to `%LOCALAPPDATA%\DevDocsDownloader\schedules.json`, a scheduler coroutine in the
  backend, and `GET/POST/DELETE /schedules` endpoints wired into `SettingsPage`.
- Ship 1.5.2 Windows toast notifications (`NotificationService` in the C# shell, preference
  toggles) — high perceived value for low effort.

### Phase 2 — Next (2-6 weeks)
- Complete 1.6.0: per-language auto-refresh policies (1.5.3, `LanguageSettings` store), webhook
  triggers with HMAC signing (1.5.4, delivery in `doc_ingest/services.py`), and versioned batch
  profiles with the `BulkPage` redesign (1.5.5). Tag `v1.6.0` through the existing release flow.
- Investigate code signing earlier than the roadmap places it (1.9.1): even an OV certificate or
  Azure Trusted Signing would remove the biggest adoption blocker; track cost/feasibility and, if
  viable, sign the 1.6.x installers in `release.yml`.
- Keep the live-drift workflow honest: review its recent runs and fix any upstream extraction
  drift it has flagged for DevDocs/MDN/Dash.

### Phase 3 — Later (optional/stretch)
- 1.7.0 Extensibility: freeze the source plugin protocol (`doc_ingest/sources/base` contract),
  plugin manager page, conversion profile editor, script hooks, and the three planned docs
  (`plugin_api.md`, `plugin_development_guide.md`, `api_stability.md`).
- 1.8.0 Performance: incremental compilation, fair-share scheduling, tiered cache, benchmark-tuned
  defaults (`scripts/benchmark_concurrency.py`).
- 1.9.0 UX/Polish and the 2.0.0 release train (regression suite, complete docs, beta → RC).
- Consider trimming roadmap scope: 1.8.4 settings workspaces and parts of 1.7.0 are cuttable
  without hurting the 2.0 story for a solo maintainer.

## Effort to "finished"
L (>1 month) part-time solo — four disciplined milestones remain to reach the roadmap's 2.0.0,
though a valuable "1.6.0 + signed installer" checkpoint is reachable in about a month.
