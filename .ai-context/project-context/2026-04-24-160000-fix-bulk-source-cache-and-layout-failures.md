## Summary

- Date/time: 2026-04-24-160000
- Agent: GitHub Copilot (gpt-5.4)
- Task: Investigate bulk run cases that completed with 0 downloaded docs and harden source handling across DevDocs, MDN, and Dash.

## Changed

- Files: `doc_ingest/pipeline.py`; `doc_ingest/sources/devdocs.py`; `doc_ingest/sources/mdn.py`; `doc_ingest/sources/dash.py`; `tests/test_source_resilience.py`
- Behavior: bulk runs now honor `--force-refresh` for every language; DevDocs refreshes corrupt cached JSON datasets; MDN validates extracted tree layout instead of trusting `.ready`; MDN extraction preserves required `files/en-us/...` directories; Dash now reports invalid archives clearly instead of leaking gzip errors.

## Why

- Problem/request: Full bulk runs showed many languages with 0 documents due to stale source caches, MDN extraction layout mismatches, and unreadable Dash downloads.
- Reason this approach was chosen: Fixing the source-specific failure modes and the bulk refresh bug addresses the observed zero-doc cases without changing successful compilation flow.

## Risk

- Side effects: Corrupt cached source payloads are re-downloaded, so first rerun after bad cache detection may take longer.
- Follow-up: Let the full bulk run finish once and inspect any remaining failures for source-side timeouts versus unsupported feeds.

## Validation

- Tests run: `python -m pytest tests/test_source_resilience.py`; `python DevDocsDownloader.py run html --source mdn --mode important --force-refresh --silent`
- Not run: Full `bulk all` completion; an in-progress live verification was started.

## Links

- Related context: `2026-04-21-190500-audit-remediation-batch-1.md`
- Related lesson: `2026-04-24-source-caches-and-ready-markers-need-structural-validation.md`
