# DevDocsDownloader 1.2.5

`1.2.5` completes roadmap steps `1.2.2` through `1.2.5` in one Source Excellence release train.

Highlights:

- Dash catalog now probes docset archive size metadata (`HEAD`) and surfaces size hints.
- Dash conversion now supports per-docset profile registry plus learned selector reuse from prior successful conversions.
- Dash quality telemetry now records indexed entries, emitted docs, and conversion success; catalog entries expose confidence hints.
- New `web_page` source adapter ingests configured single-page/manual style documentation from `web_sources.json`.
- New backend endpoint `GET /sources/health` exposes per-source status, catalog age, and breaker state.
- Desktop shell now consumes source-health data and shows compact source health state in the sidebar.
- Run flow now warns before large Dash downloads and supports per-docset suppression.
- Languages payload now includes `size_hint`, `discovery_metadata`, and confidence fields for richer UI signals.

Included artifacts:

- `DevDocsDownloader-Setup-1.2.5.exe`
- `DevDocsDownloader-Portable-1.2.5.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- Desktop package bundles the Python ingestion backend.
