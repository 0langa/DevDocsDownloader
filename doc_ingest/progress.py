from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

from .models import LanguageEntry, LanguageRunReport


@dataclass
class LanguageProgress:
    language: str
    slug: str
    pages_crawled: int = 0
    links_found: int = 0
    links_added: int = 0
    status_ok: int = 0
    status_moved: int = 0
    status_not_found: int = 0
    queue_size: int = 0
    cache_hits: int = 0
    completed: bool = False


class CrawlProgressTracker:
    def __init__(self, console: Console | None = None, *, single_terminal: bool = False, log_interval_seconds: float = 5.0) -> None:
        self.console = console or Console()
        self.single_terminal = single_terminal
        self.log_interval_seconds = max(1.0, log_interval_seconds)
        self._lock = asyncio.Lock()
        self._live: Live | None = None
        self._languages: dict[str, LanguageProgress] = {}
        self._total_languages = 1
        self._failed_requests = 0
        self._last_single_terminal_log = 0.0
        self._progress = Progress(
            TextColumn("[bold cyan]Overall progress[/bold cyan]"),
            BarColumn(bar_width=None),
            TextColumn("{task.percentage:>5.1f}%"),
            expand=True,
        )
        self._overall_task = self._progress.add_task("overall", total=1, completed=0)

    @contextmanager
    def live(self):
        if self.single_terminal:
            self._emit_single_terminal_snapshot(force=True)
            with nullcontext(self):
                yield self
            self._emit_single_terminal_snapshot(force=True)
            return
        with Live(self._build_renderable(), console=self.console, refresh_per_second=8, transient=False) as live:
            self._live = live
            self._refresh()
            try:
                yield self
            finally:
                self._live = None

    async def set_total_languages(self, total_languages: int) -> None:
        async with self._lock:
            self._total_languages = max(1, total_languages)
            self._refresh()

    async def register_languages(self, entries: list[LanguageEntry]) -> None:
        async with self._lock:
            for entry in entries:
                self._languages.setdefault(entry.slug, LanguageProgress(language=entry.name, slug=entry.slug))
            self._refresh()

    async def on_fetch_complete(self, slug: str, status_code: int, history_status_codes: list[int], fetch_method: str) -> None:
        async with self._lock:
            language = self._languages[slug]
            language.pages_crawled += 1
            language.status_moved += sum(1 for code in history_status_codes if 300 <= code < 400)
            if 200 <= status_code < 300:
                language.status_ok += 1
            elif status_code == 404:
                language.status_not_found += 1
            if fetch_method == "cache":
                language.cache_hits += 1
            self._refresh()

    async def on_links_found(self, slug: str, link_count: int) -> None:
        async with self._lock:
            self._languages[slug].links_found += max(0, link_count)
            self._refresh()

    async def on_links_added(self, slug: str, link_count: int) -> None:
        async with self._lock:
            self._languages[slug].links_added += max(0, link_count)
            self._refresh()

    async def on_queue_size_changed(self, slug: str, queue_size: int) -> None:
        async with self._lock:
            self._languages[slug].queue_size = max(0, queue_size)
            self._refresh()

    async def on_request_failure(self, slug: str) -> None:
        async with self._lock:
            self._languages[slug].pages_crawled += 1
            self._failed_requests += 1
            self._refresh()

    async def on_language_complete(self, slug: str, report: LanguageRunReport) -> None:
        async with self._lock:
            language = self._languages[slug]
            language.completed = True
            language.queue_size = 0
            language.pages_crawled = max(language.pages_crawled, report.pages_processed + len(report.failures))
            self._refresh()

    def _refresh(self) -> None:
        completed_value = self._completed_languages() + self._active_fraction()
        self._progress.update(self._overall_task, total=float(self._total_languages), completed=min(float(self._total_languages), completed_value))
        if self.single_terminal:
            self._emit_single_terminal_snapshot()
        elif self._live is not None:
            self._live.update(self._build_renderable())

    def _emit_single_terminal_snapshot(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_single_terminal_log) < self.log_interval_seconds:
            return
        self._last_single_terminal_log = now
        totals = self._totals()
        active_languages = sorted(
            self._languages.values(),
            key=lambda item: (item.completed, -(item.pages_crawled + item.queue_size), item.language.lower()),
        )[:5]
        active_summary = ", ".join(
            f"{item.language}: crawled={item.pages_crawled}, queue={item.queue_size}, found={item.links_found}, added={item.links_added}, state={'done' if item.completed else 'running' if (item.pages_crawled or item.queue_size) else 'queued'}"
            for item in active_languages
        ) or "waiting for crawl to start"
        self.console.print(
            "[cyan][progress][/cyan] "
            f"complete={totals['languages_complete']}/{self._total_languages} "
            f"pages={totals['pages_crawled']:,} "
            f"found={totals['links_found']:,} "
            f"added={totals['links_added']:,} "
            f"queued={totals['queue_size']:,} "
            f"cache_hits={totals['cache_hits']:,} "
            f"failures={self._failed_requests:,}"
        )
        self.console.print(f"[dim]active:[/dim] {active_summary}")

    def _completed_languages(self) -> int:
        return sum(1 for item in self._languages.values() if item.completed)

    def _active_fraction(self) -> float:
        fraction = 0.0
        for item in self._languages.values():
            if item.completed:
                continue
            workload = item.pages_crawled + item.queue_size
            if workload <= 0:
                continue
            fraction += item.pages_crawled / workload
        return fraction

    def _totals(self) -> dict[str, int]:
        totals = {
            "pages_crawled": 0,
            "links_found": 0,
            "links_added": 0,
            "status_ok": 0,
            "status_moved": 0,
            "status_not_found": 0,
            "languages_complete": 0,
            "queue_size": 0,
            "cache_hits": 0,
        }
        for item in self._languages.values():
            totals["pages_crawled"] += item.pages_crawled
            totals["links_found"] += item.links_found
            totals["links_added"] += item.links_added
            totals["status_ok"] += item.status_ok
            totals["status_moved"] += item.status_moved
            totals["status_not_found"] += item.status_not_found
            totals["queue_size"] += item.queue_size
            totals["cache_hits"] += item.cache_hits
            if item.completed:
                totals["languages_complete"] += 1
        return totals

    def _build_summary_table(self) -> Table:
        totals = self._totals()
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold white")
        table.add_column(style="bold green", justify="right")
        table.add_row("Pages Crawled:", f"{totals['pages_crawled']:,}")
        table.add_row("Links Found:", f"{totals['links_found']:,}")
        table.add_row("Links Added:", f"{totals['links_added']:,}")
        table.add_row("Status OK:", f"{totals['status_ok']:,}")
        table.add_row("Status Moved:", f"{totals['status_moved']:,}")
        table.add_row("Status Not Found:", f"{totals['status_not_found']:,}")
        table.add_row("Languages Complete:", f"{totals['languages_complete']:,}/{self._total_languages:,}")
        return table

    def _build_active_languages_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("Language", style="bold cyan")
        table.add_column("Crawled", justify="right")
        table.add_column("Found", justify="right")
        table.add_column("Added", justify="right")
        table.add_column("Queue", justify="right")
        table.add_column("State", justify="right")

        active_languages = sorted(
            self._languages.values(),
            key=lambda item: (item.completed, -(item.pages_crawled + item.queue_size), item.language.lower()),
        )[:8]
        for item in active_languages:
            if item.completed:
                state = "done"
            elif item.pages_crawled or item.queue_size:
                state = "running"
            else:
                state = "queued"
            table.add_row(
                item.language,
                f"{item.pages_crawled:,}",
                f"{item.links_found:,}",
                f"{item.links_added:,}",
                f"{item.queue_size:,}",
                state,
            )
        if not active_languages:
            table.add_row("Waiting for crawl to start", "0", "0", "0", "0", "queued")
        return table

    def _build_footer_table(self) -> Table:
        totals = self._totals()
        table = Table.grid(expand=True)
        table.add_column(style="dim")
        table.add_column(style="dim", justify="right")
        table.add_row("Cache Hits", f"{totals['cache_hits']:,}")
        table.add_row("Queued URLs", f"{totals['queue_size']:,}")
        table.add_row("Fetch Failures", f"{self._failed_requests:,}")
        table.add_row("Log File", "logs/run.log")
        return table

    def _build_renderable(self):
        return Group(
            Panel(self._progress, title="Overall Progress", border_style="cyan"),
            Panel(self._build_summary_table(), title="Run Totals", border_style="green"),
            Panel(self._build_active_languages_table(), title="Active Languages", border_style="blue"),
            Panel(self._build_footer_table(), title="Runtime", border_style="magenta"),
        )