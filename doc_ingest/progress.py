from __future__ import annotations

import asyncio
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

from .models import LanguageRunReport


@dataclass
class LanguageProgress:
    slug: str
    display_name: str
    documents: int = 0
    completed: bool = False
    failed: bool = False


class CrawlProgressTracker:
    def __init__(self, console: Console | None = None, *, single_terminal: bool = False) -> None:
        self.console = console or Console()
        self.single_terminal = single_terminal
        self._live: Live | None = None
        self._lock = asyncio.Lock()
        self._languages: dict[str, LanguageProgress] = {}
        self._progress = Progress(
            TextColumn("[bold cyan]Documentation download[/bold cyan]"),
            BarColumn(bar_width=None),
            TextColumn("{task.fields[status]}"),
            expand=True,
        )
        self._task_id = self._progress.add_task("docs", total=None, status="starting")

    def emit_log(self, level: str, message: str) -> None:
        text = f"[{level}] {message}"
        if self._live is not None:
            self._live.console.print(text, markup=False, highlight=False)
        else:
            self.console.print(text, markup=False, highlight=False)

    @contextmanager
    def live(self):
        if self.single_terminal:
            with nullcontext(self):
                yield self
            return
        with Live(self._renderable(), console=self.console, refresh_per_second=6, transient=False) as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    async def register_language(self, slug: str, display_name: str) -> None:
        async with self._lock:
            self._languages.setdefault(slug, LanguageProgress(slug=slug, display_name=display_name))
            self._refresh()

    async def on_document_completed(self, slug: str) -> None:
        async with self._lock:
            lang = self._languages.setdefault(slug, LanguageProgress(slug=slug, display_name=slug))
            lang.documents += 1
            if lang.documents % 20 == 0:
                self._refresh()

    async def on_language_complete(self, slug: str, report: LanguageRunReport) -> None:
        async with self._lock:
            lang = self._languages.setdefault(slug, LanguageProgress(slug=slug, display_name=report.language))
            lang.documents = report.total_documents
            lang.failed = bool(report.failures)
            lang.completed = True
            self._refresh()

    def _refresh(self) -> None:
        totals = sum(language.documents for language in self._languages.values())
        status = f"documents: {totals:,}"
        self._progress.update(self._task_id, status=status, advance=0)
        if self._live is not None:
            self._live.update(self._renderable())

    def _renderable(self):
        table = Table(expand=True)
        table.add_column("Language", style="bold cyan")
        table.add_column("Documents", justify="right")
        table.add_column("Status", justify="right")
        for lang in self._languages.values():
            state = "done" if lang.completed else ("failed" if lang.failed else "downloading")
            table.add_row(lang.display_name, f"{lang.documents:,}", state)
        return Group(
            Panel(self._progress, title="Progress", border_style="cyan"),
            Panel(table, title="Languages", border_style="blue"),
        )
