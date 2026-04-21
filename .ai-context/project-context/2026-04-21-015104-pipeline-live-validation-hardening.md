# Project Context Template

## Summary

- Date/time: 2026-04-21-015104
- Agent: GitHub Copilot (GPT-5.4)
- Task: Validate the new dataset-grade compiler/validator pipeline, fix live-run blockers, and confirm bounded real-world runs for Python and TypeScript.

## Changed

- Files: doc_ingest/state.py; doc_ingest/cli.py; doc_ingest/pipeline.py; doc_ingest/adapters.py; doc_ingest/mergers/compiler.py; doc_ingest/extractors/html_docling.py; tests/test_compiler_and_validator.py; tests/test_pipeline_resume.py
- Behavior: Added legacy state migration, fixed CLI `--force-refresh`, enforced `--max-pages` in enqueueing, filtered adapter-specific noisy headings during reconstruction, fixed Docling helper indentation, and refreshed test coverage plus live validation outputs.

## Why

- Problem/request: The quality-layer changes needed real validation, but live runs failed on old state files, ignored force-refresh, and did not honor page caps.
- Reason this approach was chosen: Fixing persisted-state compatibility and crawl-budget enforcement at the source restored reliable scripted runs without broad architecture changes.

## Risk

- Side effects: `max-pages` now acts as a hard scheduling cap on discovered pages, which is stricter than the prior de facto behavior.
- Follow-up: TypeScript output still shows some homepage-heavy navigation content; additional adapter tuning or block-level filtering may still improve AI-readiness.

## Validation

- Tests run: `python -m pytest -q tests/test_compiler_and_validator.py tests/test_pipeline_resume.py tests/test_extraction_and_normalization.py` -> 11 passed; bounded live runs for Python and TypeScript with `--max-pages 5`.
- Not run: Larger uncapped end-to-end crawls; broader multi-language regression sweep.

## Links

- Related context: 2026-04-21-160000-fix-main-documentation-layout.md
- Related lesson: 2026-04-21-state-migration-and-bounded-runs.md
