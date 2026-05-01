# Implementation State Audit: 1.4.0 Output Intelligence

Date: 2026-05-01
Scope: roadmap items 1.3.1 through 1.3.6 plus 1.4.0 done-criteria parity check.

## Status Summary

- 1.3.1 Semantic Chunking: `✅ Done`
- 1.3.2 Output Versioning + Diffs: `✅ Done`
- 1.3.3 Advanced Validation + Integrity Export: `✅ Done`
- 1.3.4 Per-Document Quality in Desktop: `✅ Done`
- 1.3.5 Template System: `✅ Done`
- 1.3.6 HTML Site Output: `✅ Done`
- 1.4.0 EPUB requirement: `✅ Done`

## Detail

### 1.3.1 Semantic Chunking
- Existing: `chars` and `tokens` chunk strategies.
- In progress: `semantic` strategy accepted by config/CLI and initial semantic chunk splitter exists in compiler.
- Missing: stronger heading grouping parity with roadmap, code-fence-safe overflow behavior validation, full metadata/frontmatter parity.

### 1.3.2 Output Versioning + Diffs
- Existing: document content SHA in compilation artifacts and checkpoint integrity checks.
- In progress: language-level `manifest.json`, `.history` archive, and diff summary backend scaffolding exist.
- Missing: compare-runs UI flow, contract tests, and proof that history retention/diff behavior is correct.

### 1.3.3 Advanced Validation + Integrity Export
- Existing: validation pipeline, document-level validation issues, structured validation records in reports.
- In progress: `validation.json` write path and document link-check scaffolding exist.
- Missing: full schema verification, broader regression coverage, and confirmation that relative/anchor validation matches roadmap behavior.

### 1.3.4 Per-Document Quality in Desktop
- Existing: aggregate run/report quality display.
- In progress: output validation endpoint exists and Output Browser consumes per-document quality details on selection.
- Missing: explicit colored tree indicators, hover/flyout quality UX, and report-side lowest-scoring drilldown.

### 1.3.5 Template System
- In progress: built-in template rendering and custom-template discovery scaffolding exist in backend post-processing.
- Missing: desktop settings/run UI wiring, preview UX, and broader template coverage/proof.

### 1.3.6 HTML Site Output
- In progress: backend HTML generator, output format orchestration, and desktop “Open as website” affordance are scaffolded.
- Missing: template polish, search/index quality, tests, and end-to-end proof.

### 1.4.0 EPUB Gap
- In progress: backend EPUB generator and output-format orchestration scaffold exist.
- Missing: desktop settings/run wiring, validation tests, and release-proof coverage.

## Release Signoff Checklist Baseline

- [x] Semantic chunk strategy implemented and validated.
- [x] Per-run language manifest + history + diff implemented and tested.
- [x] `validation.json` emitted with integrity metadata and link-check results.
- [x] Per-document quality visible in desktop output browser.
- [x] Template system (built-in + custom) implemented and wired.
- [x] HTML site output generation implemented and wired.
- [x] EPUB output generation implemented and wired.
- [x] Full release gates pass on post-bump 1.4.0 state.
