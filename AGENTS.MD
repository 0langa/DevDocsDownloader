# DevDocsDownloader Agent Bootstrap

Non-optional. Follow this before planning, searching, editing, or answering repo questions.

## Initialization Order

1. Open `.ai-context/`.
2. Read every file in `.ai-context/main-documentation/`.
3. Read the newest 3 non-template files in `.ai-context/project-context/`.
4. Read the newest 3 non-template files in `.ai-context/lessons-learned/`.
5. If a folder has fewer than 3 non-template files, read all of them.

Sort recent files by filename descending. Ignore files whose names start with `_TEMPLATE`.

## Update Rules

- After any code, config, test, doc, or workflow change, add one file to `.ai-context/project-context/` using `.ai-context/project-context/_TEMPLATE_CONTEXT.md`.
- When you learn a reusable lesson, add or update a file in `.ai-context/lessons-learned/` using `.ai-context/lessons-learned/_TEMPLATE_LESSONS.md`.
- If you are unsure where a non-core AI-facing note belongs, place it in `.ai-context/other-documentation/`.
- Keep `AGENTS.md`, `devdocsdownloader.agent.md`, and the `.ai-context` docs aligned.
- Keep all `.ai-context` loading and routing rules in `AGENTS.md` only.
- Do not duplicate bootstrap/context-loading instructions in repo-specific agent files.

## Style Rules

- `.ai-context/main-documentation/` is the primary knowledge base and may be detailed.
- `.ai-context/main-documentation/` contains `TODO.md`, `project_state.md`, and `project_architecture.md`.
- All other AI-facing docs must stay terse, factual, and low-token.
- Replace stale facts; do not append duplicate guidance.
