# DevDocsDownloader Output Contract

This document defines the stable generated-output contract for downstream tools and tests. Changes to these files are compatibility changes and must be covered by contract tests.

## Directory Layout

For a language with normalized slug `<language>`, generated Markdown is written under:

```text
output/markdown/<language>/
  _meta.json
  index.md
  <language>.md
  assets/
    manifest.json
    <checksum>-<asset-name>
  chunks/
    manifest.jsonl
    <chunk>.md
  <topic>/
    _section.md
    <document>.md
```

Runtime state and reports are written separately:

```text
state/<language>.json
state/checkpoints/<language>.json
output/reports/run_summary.json
output/reports/run_summary.md
output/reports/validation_documents.jsonl
output/reports/history/<timestamp>-run_summary.json
output/reports/trends.json
output/reports/trends.md
```

All generated file and directory names are slug-normalized and Windows-safe. Duplicate document slugs within the same topic receive numeric suffixes, for example `std-vector.md` and `std-vector-2.md`.

## Markdown Files

### Language Index

`index.md` is a navigation file for the language. It must contain:

- `# <Language> Documentation - Index`
- a `## Metadata` section with source name, source slug, source URL, mode, generation timestamp, and total document count
- a `## Consolidated file` section linking to `<language>.md`
- a `## Topics` section linking to every `<topic>/_section.md` file in emitted topic order

### Consolidated File

`<language>.md` is the primary downstream manual. It must contain:

- `# <Language> Documentation`
- `## Metadata`
- `## Table of Contents`
- `## Documentation`
- one `### <Topic>` section per emitted topic
- one `#### <Document title>` section per emitted document
- source links for documents that provide `source_url`

Input document headings are shifted down by two levels and repeated blank lines are collapsed, so source `#` headings become `###` inside per-document files and consolidated document bodies.

### Topic Sections

Each `<topic>/_section.md` file must contain:

- `# <Topic>`
- a source summary line
- `## Contents`
- one relative link per document in that topic

### Per-Document Files

Each `<topic>/<document>.md` file must contain:

- `# <Document title>`
- an italic language/topic metadata line
- an italic source link when `source_url` is available
- the normalized document Markdown body

## JSON Metadata

`_meta.json` must include:

- `language`
- `slug`
- `source`
- `source_slug`
- `source_url`
- `mode`
- `total_documents`
- `topics`, as objects with `topic` and `document_count`
- `generated_at`, as an ISO timestamp

`state/<language>.json` is the stable completed-run summary. It must include language/source identity, mode, topics, total document count, source diagnostics when available, `output_path`, `completed`, warnings, failures, and timestamps.

`state/checkpoints/<language>.json` is only for active or failed runs. Successful runs remove it after the stable state file is saved. Failed checkpoints must retain phase, document inventory position, emitted document count, last document metadata, emitted artifact metadata, and structured failure records.

When a checkpoint has a valid emitted artifact manifest, each `emitted_documents` entry includes:

- `topic`
- `slug`
- `title`
- `source_url`
- `order_hint`
- `path`, pointing to the emitted per-document Markdown file
- `fragment_path`, pointing to the temporary consolidated fragment used for resume when it still exists

On the next matching run, the pipeline may automatically resume after `document_inventory_position` if language, source, source slug, mode, output path, and all manifest artifact paths are still valid. Missing or stale artifacts must cause a full replay rather than a partial final output.

## Reports and Diagnostics

`output/reports/run_summary.json` serializes the run summary model. `output/reports/run_summary.md` is the human-readable equivalent.

When available, `SourceRunDiagnostics` must report:

- `discovered`: source inventory count
- `emitted`: documents yielded by the source before pipeline filters
- `skipped`: reason-count map

Standard skip reasons currently include `filtered_mode`, `filtered_topic_include`, `filtered_topic_exclude`, `checkpoint_resume_skip`, `malformed_frontmatter`, `duplicate_or_empty_path`, `missing_content`, `empty_markdown`, `missing_path_or_type`, `duplicate_path`, and `missing_file`.

Resume is conservative but no longer all-or-nothing on temporary fragments. If a checkpoint identity matches and the durable per-document artifact files still exist, the compiler may rebuild missing temporary consolidated fragments from those durable documents during resume. Missing durable document artifacts still force a replay from the start.

Validation results must include `score`, `quality_score`, `issues`, language, and output path. Validation checks structural output shape and basic quality signals; it does not certify source-document correctness.

Current validation issue codes include structural issues such as `missing_output`, `no_documents`, `tiny_output`, `code_fence`, `missing_section`, and `no_topics`; navigation and structure warnings such as `missing_internal_anchor`, `duplicate_topic_section`, `document_heading_count_mismatch`, `malformed_heading_hierarchy`, and `duplicate_document_heading`; source reconciliation warnings such as `topic_total_mismatch`, `source_inventory_mismatch`, and `emitted_less_than_compiled`; plus conversion-quality warnings such as `relative_link`, `relative_image`, `empty_link_target`, `html_leftover`, `malformed_table`, and `definition_list_artifact`.

`validation_documents.jsonl` is an additive per-document validation report. Each line includes language/source identity, topic, slug, title, document path, source URL, issue list, and a short context string for generated documents that have document-local validation issues.

Reports include additive structured fields when available:

- `document_warnings`: source warning records with code, message, optional document identity, source URL, topic, slug/title, and order hint
- `runtime_telemetry`: request count, retry count, bytes observed, source failures, cache hits, and cache refreshes
- `adaptive_telemetry`: bulk scheduling policy, min/max/current concurrency, adjustment count, adjustment reasons, observed windows, failed language count, and retry-pressure windows

`output/reports/history/` stores timestamped copies of run summaries. `trends.json` and `trends.md` summarize historical document counts, validation scores, issue counts, duration, runtime telemetry, and failures. Existing `run_summary.json` and `run_summary.md` remain the latest-report contract.

## Phase 7 Optional Outputs

Consolidated manuals emit explicit HTML anchors before each topic and document heading. Table-of-contents links must use the exact same generated anchor IDs. Duplicate heading text receives deterministic numeric suffixes such as `repeat` and `repeat-2`.

Per-document YAML frontmatter is optional and disabled by default. When enabled, each `<topic>/<document>.md` starts with YAML fields for language, language slug, source, source slug, source URL, topic, slug, title, order hint, mode, and generation timestamp. The existing human-readable metadata lines remain present for compatibility.

Chunk export is optional and disabled by default. When enabled, generated chunks live under `chunks/` and `chunks/manifest.jsonl` contains one JSON object per chunk with stable chunk ID, language/source identity, topic, document slug/title, source URL, order hint, chunk index, text path, and character offsets. Chunks are character-bounded Markdown derived from per-document files, not the consolidated manual.

Character-bounded chunks remain the default. Token-bounded chunks are optional and require the `tokenizer` extra. Token chunk manifests preserve the existing fields and add `chunk_strategy`, `token_start`, `token_end`, and `token_count`.

Known same-language links may be rewritten to local generated Markdown files when the compiler has an exact match from a document source URL, normalized source URL without fragment, source slug/path, or generated path. Unknown targets keep the existing source-absolute or unchanged link policy. Links inside fenced code blocks are not rewritten.

Asset inventory is optional and event-driven. When adapters emit `AssetEvent` records, the compiler writes `assets/manifest.json`. Manifest records include source URL, media type, original path, optional local output path, checksum, byte count, status, and reason. Assets with bytes or safe local paths are deduplicated by checksum and copied under `assets/`; matching Markdown image/source references are rewritten to local relative paths. Assets without local payload are recorded as references only. The compiler does not fetch arbitrary asset URLs.

When optional outputs are enabled, `_meta.json` may include an `outputs` object describing enabled frontmatter, chunk settings, and asset inventory summary. Consumers must treat `outputs` as optional.

Source cache metadata is written beside source cache artifacts as `*.meta.json` where practical. Metadata records source, cache key, URL, fetched timestamp, source version when known, ETag, Last-Modified, checksum, byte count, cache policy, and whether refresh was forced.

## Desktop Consumption

The desktop backend host does not introduce new generated output artifacts. It reads this contract through `DocumentationService` methods and exposes the same data over the loopback backend API for the WinUI shell. Output/report/checkpoint/cache file reads must remain constrained to configured roots, and checkpoint deletion must remain limited to `state/checkpoints/*.json`.
