# Lesson Template

## Lesson

- Date: 2026-04-21
- Agent: GitHub Copilot (GPT-5.4)
- Topic: State compatibility and bounded-run validation
- Category: reliability

## Insight

- What was learned: Live validation can fail even when tests pass if persisted state schemas changed, CLI flags are only partially wired, or crawl-budget settings are configured but never enforced in queueing.
- Why it matters: This repo is stateful and long-running; migration and runtime flag semantics must be validated against real saved state and real crawl loops, not only fixture-based pipeline tests.

## Evidence

- Trigger/task: Bounded Python live run failed first on legacy `state/python.json`, then reused old state because `--force-refresh` was masked by `resume`, then exceeded `--max-pages 5` because the queue never enforced the cap.
- Files or components: doc_ingest/state.py; doc_ingest/cli.py; doc_ingest/pipeline.py
- Concrete example: After fixing those three points, Python and TypeScript bounded runs completed with 5 processed pages each and quality scores of 0.91 and 0.86.

## Reuse

- Apply when: Changing `CrawlState`, adding CLI execution flags, or relying on bounded live validation runs.
- Avoid: Assuming config knobs are enforced just because they exist in `AppConfig` or CLI help.
- Related context: 2026-04-21-015104-pipeline-live-validation-hardening.md
- Tags: state,migration,cli,limits,live-validation
