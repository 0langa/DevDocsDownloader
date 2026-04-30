# DevDocsDownloader 1.1.2

Stable `1.1.2` release focused on catalog-driven language selection, bulk UX, and source dropdowns.

Highlights:

- Replaced the plain-text source input on the Run page with a dropdown (`Any (auto)`, `devdocs`, `mdn`, `dash`) — eliminates typo-prone free entry.
- Replaced the comma-separated language text box on the Bulk page with a searchable, catalog-backed multi-select: type to filter, click to add, remove individual languages with ✕.
- Added a **Version filter** dropdown to Bulk (`Latest only` / `All versions`) — controls which version variants appear in autocomplete and in "Download all".
- Added a **Download all** button to Bulk — fetches the full catalog, applies the version filter, and launches a bulk job in one click.
- Added a **Preferred source** dropdown to Bulk (mirrors Run page), passed through to the backend resolver for the entire batch.
- Backend: `BulkRunRequest` now accepts an optional `source` field, forwarded to `pipeline.run_many` as `source_name`.

Included artifacts:

- `DevDocsDownloader-Setup-1.1.2.exe`
- `DevDocsDownloader-Portable-1.1.2.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases.
