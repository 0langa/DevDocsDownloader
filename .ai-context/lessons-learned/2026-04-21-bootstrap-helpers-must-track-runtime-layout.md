# Lesson Template

## Lesson

- Date: 2026-04-21
- Agent: GitHub Copilot (GPT-5.4)
- Topic: Bootstrap helpers must track runtime layout
- Category: maintainability

## Insight

- What was learned: A repo-local bootstrap script can drift even when runtime code is correct, especially when it duplicates path layout instead of following the same contract.
- Why it matters: Fresh-clone setup becomes misleading if it omits directories the app writes to later, and that drift is easy to miss without a direct test.

## Evidence

- Trigger/task: Packaging audit for `requirements.txt` and `setup.py`.
- Files or components: `setup.py`; `doc_ingest/config.py`; `tests/test_setup_bootstrap.py`
- Concrete example: `setup.py` still created `output/markdown` and `output/reports`, but it missed `output/diagnostics` and `cache/discovered_links`, both of which are part of the current runtime layout.

## Reuse

- Apply when: Auditing bootstrap/install scripts after config or path-layout changes.
- Avoid: Assuming setup helpers stay current just because runtime code calls `ensure()` elsewhere.
- Related context: `2026-04-21-015559-package-and-bootstrap-audit.md`
- Tags: setup,bootstrap,paths,regression
