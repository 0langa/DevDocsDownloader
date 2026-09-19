# DevDocsDownloader Agent Bootstrap

Canonical agent bootstrap for DevDocsDownloader. Read before planning or
editing. It describes the repo as it exists — if a path here is missing on
disk, this file is stale: fix the file, do not build the missing scaffold.

> Corrected 2026-08-27: an earlier version routed everything through an
> `.ai-context/` tree. That tree does not exist in this repository. The real
> documentation lives in `documentation/`.

## Read Order

1. `README.md` — what the project is and how to run it.
2. `documentation/architecture.md` and `documentation/codemap.md` — structure.
3. `documentation/development_progress.md` and `NEXT_STEPS.md` — current state
   and what is planned next.
4. Only the further files under `documentation/` your task actually needs
   (`output_contract.md`, `release_checklist.md`, `implementation_state_*.md`,
   `full-project-documentation.md`).

`documentation/archive/` is historical. Open it only when the task asks for
history or needs a specific file there.

## Repo Shape

Python ingestion pipeline (`doc_ingest/`, `DevDocsDownloader.py`,
`pyproject.toml`, `requirements.txt`) plus a C# desktop shell
(`DevDocsDownloader.Desktop.sln`, `desktop/`). `scripts/` and `benchmarks/` are
supporting tooling; `cache/`, `logs/`, and `output/` are generated — never a
source of truth.

## Update Rules

- Code is source of truth. If a doc and the code disagree, trust the code, then
  correct the doc in the same change.
- After a change to behavior, architecture, the output contract, commands,
  dependencies, or the release process, update the affected file under
  `documentation/` in the same change set.
- Small internal changes (refactors with no behavior change, comments,
  formatting, test-only edits) need no doc update.
- Update `NEXT_STEPS.md` when priorities or known gaps move.
- Replace stale facts in place; do not append a duplicate section beside them.

## Style Rules

- `documentation/` is the primary knowledge base and may be detailed.
- Keep AI-facing notes terse, factual, and low-token.
- Write docs in English.
