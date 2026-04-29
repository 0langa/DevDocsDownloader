# DevDocsDownloader 1.1.1

Stable `1.1.1` release focused on trust signals, source confidence, and repeat-use desktop operations.

Highlights:

- Hardened language resolution for shorthand aliases, punctuation variants, and version-shaped inputs.
- Replaced flat validation scoring with weighted component scoring while keeping the existing top-level composite score.
- Added a bounded live Dash acceptance probe that downloads one real docset, validates `docSet.dsidx`, and converts one indexed HTML document.
- Added desktop output storage management: bundle sizing, managed-storage summary, safe bundle deletion, and report-history pruning.
- Preserved the previously shipped desktop reliability work around restart-safe history, health monitoring, SSE reconnect, and cancellation feedback.

Included artifacts:

- `DevDocsDownloader-Setup-1.1.1.exe`
- `DevDocsDownloader-Portable-1.1.1.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases.
