## Summary

- Date/time: 2026-04-24-171500
- Agent: GitHub Copilot (gpt-5.4)
- Task: Verify current bulk concurrency behavior and expose `language_concurrency` in the active CLI.

## Changed

- Files: `doc_ingest/pipeline.py`; `doc_ingest/cli.py`; `tests/test_source_resilience.py`
- Behavior: `run_many()` now actually processes languages concurrently with a bounded semaphore. `bulk` now exposes `--language-concurrency` and passes it through, while still honoring `--force-refresh` during bulk runs.

## Why

- Problem/request: User needed to know whether current concurrency was real and wanted to control it from the checked-in CLI.
- Reason this approach was chosen: Wiring the option at the bulk command and enforcing it in `run_many()` is the smallest active-code change that makes concurrency both real and user-configurable.

## Risk

- Side effects: Higher concurrency can increase network, disk, and memory pressure during full runs.
- Follow-up: Consider exposing the same option on more commands if single-run orchestration evolves into grouped runs elsewhere.

## Validation

- Tests run: `get_errors` on changed files.
- Not run: full pytest or live bulk download.

## Links

- Related context: `2026-04-24-160000-fix-bulk-source-cache-and-layout-failures.md`
- Related lesson: `2026-04-24-bulk-concurrency-settings-must-be-wired-end-to-end.md`
