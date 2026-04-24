## Lesson

- Date: 2026-04-24
- Agent: GitHub Copilot (gpt-5.4)
- Topic: cross-platform output paths must target Windows-safe names
- Category: portability

## Insight

- What was learned: Output path sanitization must target the strictest supported filesystem rules, not just the OS that generated the files.
- Why it matters: Linux can create names that later fail on Windows checkouts, copies, archives, or sync workflows.

## Evidence

- Trigger/task: User reported Linux-generated documentation files with names containing patterns like `::` and other Windows-invalid path segments.
- Files or components: `doc_ingest/utils/text.py`; `doc_ingest/compiler.py`; `tests/test_source_resilience.py`
- Concrete example: `std::filesystem::path` now becomes `std-filesystem-path`, and reserved names like `CON`/`AUX` are rewritten with a safe suffix.

## Reuse

- Apply when: Generating filenames, directory names, cache keys-on-disk, or artifact paths intended to move across OSes.
- Avoid: Assuming a Linux-valid path is portable to Windows.
- Related context: `2026-04-24-170500-make-output-paths-windows-safe.md`
- Tags: portability,paths,windows,slugify,artifacts
