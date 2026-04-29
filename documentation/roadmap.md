# DevDocsDownloader Roadmap

## Audit Baseline

Audit date: `2026-04-29`

Verified current state:
- Package version in `pyproject.toml`: `1.1.0`
- Full test suite: `111 passed, 3 skipped` in about 3 minutes
- Active product path: Python ingestion engine + FastAPI desktop backend + WinUI 3 shell
- Active built-in sources: `devdocs`, `mdn`, `dash`
- Legacy NiceGUI surface removed from runtime, setup, and tests

This roadmap replaces older items that are already fixed on `main`. In particular, these are no longer roadmap bugs:
- cooperative cancel at document boundaries
- persisted desktop job history
- SSE reconnect with `from_index`
- backend health monitoring after startup
- backend startup failure dialog in shell

---

## Current Project Shape

Project is now past "make desktop usable" stage. Core ingestion, reporting, resume, desktop backend, WinUI shell, output contract, and broad regression coverage all exist and are working.

Most valuable next work is not large architecture churn. Most valuable next work is tightening product boundaries:
- remove deprecated surfaces still costing maintenance
- improve trust signals where UI/API still hide partial failure
- harden output quality scoring and language resolution
- add storage/runtime ergonomics for repeated real use
- validate weaker source paths with real acceptance coverage

---

## Main Findings

### 1. Validation score is still too shallow for quality decisions

`doc_ingest/validator.py` still uses flat deductions from `1.0`:
- `-0.3` per error
- `-0.1` per warning

This is easy to compute, but weak for comparing large vs small language bundles. Structural checks are decent; scoring model is not.

### 2. Language normalization still has obvious edge gaps

`doc_ingest/sources/registry.py` normalizes:
- `++ -> pp`
- `# -> sharp`
- `.` removed
- spaces removed

Still missing first-class handling for:
- `&`
- common alias abbreviations (`js`, `ts`, `py`, `node`)
- versioned inputs (`python3.12`, `vue 3`)
- Unicode/punctuation variants

### 3. Output lifecycle still weak for repeat desktop use

Project can create and inspect output well. It still does not manage output lifecycle well.

Gaps:
- no "open folder" action in WinUI output browser
- no storage summary / retention tooling
- no in-app cleanup path for stale bundles/reports/chunks

### 4. Dash path still less proven than DevDocs and MDN

Dash adapter exists, discovery exists, tests exist, but real acceptance confidence still trails other sources. Repository has live probe hooks, not broad end-to-end Dash acceptance coverage.

### 5. Desktop job/event model still favors simplicity over long-run scale

Current behavior is acceptable for single-user desktop use, but limits remain:
- single active backend job
- no queue UX
- job event history retained in memory per backend lifetime

Not urgent, but should stay visible.

---

## Development Direction

Recommended order of work:

1. improve quality signals and resolution accuracy
2. improve repeated-use desktop ergonomics
3. deepen source acceptance coverage
4. address packaging/distribution polish

Reason:
- Step 1 reduces moving parts before more feature work.
- Steps 2-4 improve correctness perception and day-to-day usability.
- Step 5 raises confidence in weakest source.
- Step 6 matters, but after product behavior is cleaner.

---

## Release Plan

### v1.1.0 — Trust And Surface Cleanup

Goal: finish quality-of-life work after desktop cleanup and trust improvements.

#### P1. Small WinUI ergonomics

Scope:
- add "Open output folder" action in Output Browser
- show "settings apply to next run" messaging
- preserve/refresh output root display when settings change

Validation:
- desktop page logic tests where practical
- manual shell smoke test

### v1.2.0 — Trust, Quality, Source Hardening

Goal: make run results more trustworthy and easier to reason about.

#### P2. Replace flat validation score with weighted model

Scope:
- keep existing issue detection
- redesign score around bundle size and document counts
- emit component scores such as completeness/structure/conversion
- keep backward-compatible composite `score`

Validation:
- targeted validator tests
- fixture-based comparisons for small vs large bundles

#### P3. Harden language normalization and alias resolution

Scope:
- expand `_normalise_lang()`
- add explicit alias table
- handle version and punctuation variants
- add regression coverage for ambiguous inputs

Validation:
- registry resolution tests
- preset audit tests
- source discovery fixture cases

#### P4. Raise Dash acceptance confidence

Scope:
- add bounded real acceptance checks for representative Dash docsets
- cover extraction, SQLite traversal, slug/path conversion, encoding edge cases
- document exactly what "supported" means for Dash

Validation:
- opt-in live extraction tests
- at least one stable CI path for bounded Dash verification if runtime budget allows

### v1.3.0 — Repeated-Use Desktop Operations

Goal: improve long-running desktop practicality.

#### P6. Output storage management

Scope:
- bundle size + last-run visibility
- delete selected output bundles safely
- optionally prune report history and stale chunks

Validation:
- service path-safety tests
- backend deletion endpoint tests
- manual desktop smoke test

#### P7. Better single-user job management

Scope:
- explicit queued/pending UX in shell
- clearer 409 handling
- consider bounded event retention for long jobs

Validation:
- backend job tests
- shell interaction smoke tests

#### P8. Deeper cancellation

Current cancel is good at document boundaries. Next step only if user pain justifies it:
- cooperative checks deeper in fetch/extract loops
- source/runtime support for aborting long in-flight work sooner

This is valuable, but after higher-leverage cleanup and trust work.

### Long-Term

#### L1. Distribution polish
- code signing
- release packaging cleanup around PRI handling
- optional update notification

#### L2. Persistent operational history
- if desktop usage grows, move from append-only JSONL summaries toward richer persisted job/run history

#### L3. Semantic/source-aware validation
- source-family-specific validation beyond structural heuristics

---

## What Should Not Be Prioritized Now

Avoid spending next cycle on:
- broad architectural rewrites
- multi-platform GUI strategy
- speculative new source adapters
- deeper browser automation features without adapter demand

Reason: current leverage sits in consolidation and trust, not expansion.

---

## Success Criteria For Next Phase

Roadmap is on track when these are true:
- validation score better reflects bundle quality at scale
- common alias/version inputs resolve predictably
- desktop output management covers open-folder + cleanup basics
- Dash support has clearer acceptance evidence

---

## Maintainer Notes

If only one milestone can ship next, ship `v1.1.0` first. It addresses the remaining operator trust gaps and makes later quality work easier to validate.
