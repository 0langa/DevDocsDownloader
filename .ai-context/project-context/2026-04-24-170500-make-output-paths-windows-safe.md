## Summary

- Date/time: 2026-04-24-170500
- Agent: GitHub Copilot (gpt-5.4)
- Task: Make generated language/topic/document output paths always valid on Windows, even when the crawl runs on Linux.

## Changed

- Files: `doc_ingest/utils/text.py`; `tests/test_source_resilience.py`
- Behavior: Slug generation now avoids Windows-reserved path names in addition to normal punctuation cleanup. Regression tests now cover Windows-unsafe examples like `std::`, dots, and reserved names such as `CON` and `AUX` at generated directory/file path level.

## Why

- Problem/request: Linux runs could emit filenames/directories that Windows cannot create or sync.
- Reason this approach was chosen: Centralizing sanitization in shared slug generation fixes language, topic, and document path names consistently without changing source content.

## Risk

- Side effects: Some generated filenames will change relative to previous runs, especially for reserved names and punctuation-heavy symbols.
- Follow-up: Consider documenting path-name stability expectations for downstream consumers that index generated Markdown by filename.

## Validation

- Tests run: `get_errors` on changed files.
- Not run: Full pytest or live ingestion run.

## Links

- Related context: `2026-04-24-160000-fix-bulk-source-cache-and-layout-failures.md`
- Related lesson: `2026-04-24-cross-platform-output-paths-must-target-windows-safe-names.md`
