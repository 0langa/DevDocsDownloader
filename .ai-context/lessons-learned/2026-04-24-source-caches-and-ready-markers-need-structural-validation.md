## Lesson

- Date: 2026-04-24
- Agent: GitHub Copilot (gpt-5.4)
- Topic: source caches and ready markers need structural validation
- Category: reliability

## Insight

- What was learned: Cached source artifacts and readiness markers are not trustworthy unless the code verifies their structure before reuse.
- Why it matters: This downloader depends on large third-party snapshots; a stale marker, corrupt JSON payload, or HTML error page saved as an archive can silently turn into 0-document language runs.

## Evidence

- Trigger/task: Full run showed many 0-document languages, including MDN area-missing failures and Dash gzip errors.
- Files or components: `doc_ingest/pipeline.py`; `doc_ingest/sources/devdocs.py`; `doc_ingest/sources/mdn.py`; `doc_ingest/sources/dash.py`
- Concrete example: MDN had a `.ready` marker but expected `files/en-us/web/html` was missing under the assumed root; validating the extracted tree and locating the real content root restored HTML downloads.

## Reuse

- Apply when: Reusing downloaded catalogs, archives, extracted snapshots, or any `.ready`/sentinel marker.
- Avoid: Assuming existence of a cache file or marker means the contents are valid.
- Related context: `2026-04-24-160000-fix-bulk-source-cache-and-layout-failures.md`
- Tags: cache,markers,mdn,dash,devdocs,bulk-run
