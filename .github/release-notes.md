# DevDocsDownloader 1.4.0

`1.4.0` completes the Output Intelligence milestone (`1.3.1` through `1.3.6`) and closes the EPUB parity gap.

Highlights:

- Added `semantic` chunk strategy with heading-aware chunking, code-fence-safe boundaries, H2/H3 grouping, and chunk context headers.
- Added per-language `manifest.json` generation with `.history` retention and deterministic run diff classification.
- Added machine-readable `validation.json` export flow for language outputs.
- Added report contract support for run manifest indexing and explicit run-to-run compare endpoint.
- Added desktop Reports compare-runs workflow (manifest selection + added/removed/changed preview).
- Added desktop Output Browser per-document quality grading in tree labels plus detail hints.
- Added run and settings wiring for template selection and output format selection (`markdown`, `html`, `epub`).
- Hardened HTML site and EPUB generation integration in output post-processing.

Included artifacts:

- `DevDocsDownloader-Setup-1.4.0.exe`
- `DevDocsDownloader-Portable-1.4.0.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- Desktop package bundles the Python ingestion backend.
