# Project Context Template

## Summary

- Date/time: 2026-04-21-190500
- Agent: GPT-5.3-Codex
- Task: Implement high-priority repository audit fixes across pipeline, fetching, extraction, validation, persistence, and packaging.

## Changed

- Files: `doc_ingest/pipeline.py`; `doc_ingest/config.py`; `doc_ingest/models.py`; `doc_ingest/state.py`; `doc_ingest/validators/markdown_validator.py`; `doc_ingest/fetchers/http.py`; `doc_ingest/fetchers/browser.py`; `doc_ingest/discovery.py`; `doc_ingest/utils/filesystem.py`; `doc_ingest/extractors/html.py`; `doc_ingest/extractors/html_docling.py`; `doc_ingest/extractors/scoring.py`; `doc_ingest/mergers/compiler.py`; `pyproject.toml`; tests.
- Behavior: queue defaults are bounded; validator heading checks are stricter and weak-structure condition fixed; pipeline now tracks page `extraction_status` and no longer kills workers on stale state; state loading tolerates invalid page records; robots cache uses per-host locks; browser fetch avoids semaphore-blocked startup and prefers `domcontentloaded`; HTTP cache metadata is validated and retries now include jitter and `Retry-After`; atomic write helpers now flush+fsync; HTML extraction falls back when `lxml` is unavailable; compiler near-duplicate check is bounded and uses 4-gram Jaccard.

## Why

- Problem/request: User requested implementation of the deep audit findings with emphasis on correctness, resumability, and performance stability.
- Reason this approach was chosen: Delivered the highest-risk and quickest-value items first while keeping behavior testable and backward-compatible.

## Risk

- Side effects: `PageState` now includes `extraction_status`; old state continues to load but custom tooling may need to ignore the new field.
- Follow-up: Add explicit resume-interruption tests for in-flight extraction and a dedicated Docling-timeout stress test.

## Validation

- Tests run: `python -m pytest`.
- Not run: Full live internet crawl benchmark.

## Links

- Related context: `2026-04-21-015104-pipeline-live-validation-hardening.md`
- Related lesson: `2026-04-21-state-migration-and-bounded-runs.md`
