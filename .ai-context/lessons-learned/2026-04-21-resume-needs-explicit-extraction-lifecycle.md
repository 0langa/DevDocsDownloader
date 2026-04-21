# Lesson Template

## Lesson

- Date: 2026-04-21
- Agent: GPT-5.3-Codex
- Topic: resumable crawls need an extraction lifecycle flag
- Category: reliability

## Insight

- What was learned: URL status (`pending/processed/failed`) is not enough for reliable resume when extraction runs asynchronously in background tasks.
- Why it matters: A process can crash between fetch and extraction persistence, causing duplicate work or inconsistent state unless extraction progress is tracked explicitly.

## Evidence

- Trigger/task: Deep audit remediation for pipeline resume correctness.
- Files or components: `doc_ingest/models.py`; `doc_ingest/pipeline.py`.
- Concrete example: Adding `extraction_status` and gating resume/skip decisions on `complete` prevents workers from prematurely skipping pages that were fetched but not fully persisted.

## Reuse

- Apply when: A queue worker spawns background tasks but state is persisted independently.
- Avoid: Treating a page as done based only on fetch success or a single status enum.
- Related context: `2026-04-21-190500-audit-remediation-batch-1.md`
- Tags: resume,state,async,pipeline
