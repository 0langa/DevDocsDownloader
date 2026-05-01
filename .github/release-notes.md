# DevDocsDownloader 1.5.0

`1.5.0` completes the Search & Discovery milestone (`1.4.1` through `1.4.5`).

Highlights:

- Added SQLite-backed search indexing (`output/_search/index.db`) with FTS5 snippets and language filtering.
- Added backend search endpoints: `/search`, `/search/semantic` (semantic-mode detection + FTS5 fallback), and `/xref`.
- Added cross-reference token indexing and related-document retrieval paths.
- Added persistent favorites and recents stores:
  - `output/_search/favorites.json`
  - `output/_search/recents.json`
- Added desktop client support for search/xref/favorites/recents endpoints.
- Added desktop global sidebar search flow with debounced querying and open-in-output-browser routing.
- Added Output Browser favorites panel, star/unstar action, related-documents panel, and recent-open tracking.
- Added Run page quick-launch list using compiled bundle metadata.
- Added search performance regression gate test targeting `<100ms` P95 for FTS lookups.
- Hardened release workflow with stale-asset guard to block mixed-version release artifacts.

Included artifacts:

- `DevDocsDownloader-Setup-1.5.0.exe`
- `DevDocsDownloader-Portable-1.5.0.zip`
- `SHA256SUMS.txt`

Notes:

- Semantic search remains optional and auto-falls back to FTS5 if embedding dependencies are unavailable.
- Release remains unsigned; Windows SmartScreen may warn before first launch.
