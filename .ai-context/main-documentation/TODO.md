Based on everything I've seen in the codebase, in rough priority order:

1. Verify the pipeline actually runs end-to-end
Nothing has been tested since the session-1 fixes and today's changes. Run python documentation_downloader.py run --language python --mode important and watch it complete. Many of the bugs fixed were silent — a real run is the only way to confirm the combined-mode extraction, the adaptive tune loop, and the wizard flow all work together without a new regression. Do this before building anything else.

2. Playwright page pool
browser.py creates and destroys a new Playwright page for every URL that hits the browser path. Page creation in Playwright is expensive (~50–200ms overhead). A pool of 3–4 reused pages (matching _page_semaphore) would cut that cost to near zero for the second and subsequent requests. This matters most for JavaScript-heavy doc sites like React, Vue, and Angular.

3. Persist wizard settings to a config file
Right now every python documentation_downloader.py invocation asks the same questions from scratch. Saving answers to a crawl_config.json (or .env) in the project root — and pre-filling the wizard prompts from it — would make repeated runs feel instant. Add a --reset-config flag to re-run the wizard from scratch.

4. Make failed extractions retryable
URLs where content extraction silently failed get written to state["processed"] with hash: "discovered-only". On the next run they're in processed_state_urls and permanently skipped — you can only recover them with --force-refresh (which re-crawls everything). Instead, write them to state["failed"] so they're retried normally on the next run without touching successfully-processed URLs.

5. Stream extracted documents to disk instead of holding them all in RAM
processed_docs is a dict of every ExtractedDocument (full markdown text) kept in memory until compile_language_markdown is called at the very end. For a 2000-page language at ~5KB markdown per page, that's ~10MB per language × 3 parallel languages = ~30MB just for content. Fine now, but a full 50-language run with --mode full could hold gigabytes. Writing each document to a temp file as it's extracted and reading them back during compilation would make memory usage flat regardless of crawl size.