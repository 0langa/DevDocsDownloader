## Lesson

- Date: 2026-04-24
- Agent: GitHub Copilot (gpt-5.4)
- Topic: bulk concurrency settings must be wired end-to-end
- Category: reliability

## Insight

- What was learned: A concurrency setting in config is meaningless unless the active CLI exposes it and the bulk runner actually enforces it.
- Why it matters: Users can believe a run is multicore/multi-language tuned when the current checked-in orchestration is still sequential.

## Evidence

- Trigger/task: User asked for current `language_concurrency`, then requested exposing it in the active CLI.
- Files or components: `doc_ingest/config.py`; `doc_ingest/cli.py`; `doc_ingest/pipeline.py`; `tests/test_source_resilience.py`
- Concrete example: The repo default was `3`, but `run_many()` still looped sequentially until a semaphore-bounded `asyncio.gather()` path and `--language-concurrency` option were added.

## Reuse

- Apply when: Adding knobs for concurrency, retries, limits, or performance tuning.
- Avoid: Assuming a config field affects runtime because a stale branch or archived worktree already implemented it.
- Related context: `2026-04-24-171500-expose-bulk-language-concurrency.md`
- Tags: concurrency,cli,config,pipeline,bulk
