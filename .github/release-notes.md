# DevDocsDownloader 1.0.9.2

Hotfix release — bash and single-page DevDocs manuals now download correctly.

Changes since 1.0.9.1:

- Fixed 0 documents emitted for bash and other single-page DevDocs manuals: DevDocs stores the full content under an empty string key in db.json, but index.json entries use fragment-only paths (e.g. #built-ins) so doc_key split to "". The guard `if not doc_key` skipped every entry before the db lookup. Fix: check only for duplicate keys, not empty keys.

Included artifacts:

- `DevDocsDownloader-Setup-1.0.9.2.exe`
- `DevDocsDownloader-Portable-1.0.9.2.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
