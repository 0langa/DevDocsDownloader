from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..models import RunSummary
from ..services import BulkRunRequest, DocumentationService, RunLanguageRequest, ServiceEvent

GuiJobKind = Literal["run", "bulk", "validate", "refresh_catalogs", "audit_presets"]
GuiJobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
GuiJobRunner = Callable[[Callable[[ServiceEvent], None]], Awaitable[Any]]


class GuiJobState(BaseModel):
    id: str
    label: str
    kind: GuiJobKind
    status: GuiJobStatus = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    events: list[ServiceEvent] = Field(default_factory=list)
    error: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)


class GuiJob:
    def __init__(self, state: GuiJobState, runner: GuiJobRunner) -> None:
        self.state = state
        self.runner = runner


class GuiJobQueue:
    def __init__(self) -> None:
        self._jobs: list[GuiJob] = []
        self._active_task: asyncio.Task[None] | None = None

    @property
    def jobs(self) -> list[GuiJobState]:
        return [job.state for job in self._jobs]

    @property
    def active(self) -> GuiJobState | None:
        for job in self._jobs:
            if job.state.status == "running":
                return job.state
        return None

    def submit(self, *, label: str, kind: GuiJobKind, runner: GuiJobRunner) -> GuiJobState:
        state = GuiJobState(id=uuid4().hex, label=label, kind=kind)
        self._jobs.append(GuiJob(state, runner))
        self.start_next()
        return state

    def submit_run(self, service: DocumentationService, request: RunLanguageRequest) -> GuiJobState:
        kind: GuiJobKind = "validate" if request.validate_only else "run"

        async def runner(event_sink: Callable[[ServiceEvent], None]) -> RunSummary:
            return await service.run_language(request, event_sink=event_sink)

        return self.submit(label=f"{kind}: {request.language}", kind=kind, runner=runner)

    def submit_bulk(
        self, service: DocumentationService, request: BulkRunRequest, *, label: str = "bulk"
    ) -> GuiJobState:
        async def runner(event_sink: Callable[[ServiceEvent], None]) -> RunSummary:
            return await service.run_bulk(request, event_sink=event_sink)

        return self.submit(label=label, kind="bulk", runner=runner)

    def submit_refresh_catalogs(self, service: DocumentationService) -> GuiJobState:
        async def runner(_event_sink: Callable[[ServiceEvent], None]) -> dict[str, int]:
            return await service.refresh_catalogs()

        return self.submit(label="refresh catalogs", kind="refresh_catalogs", runner=runner)

    def submit_audit_presets(
        self,
        service: DocumentationService,
        *,
        presets: list[str] | None = None,
        source: str | None = None,
        force_refresh: bool = False,
    ) -> GuiJobState:
        async def runner(_event_sink: Callable[[ServiceEvent], None]) -> Any:
            return await service.audit_presets(presets=presets, source=source, force_refresh=force_refresh)

        label = "audit presets" if not presets else f"audit: {', '.join(presets)}"
        return self.submit(label=label, kind="audit_presets", runner=runner)

    def start_next(self) -> None:
        if self._active_task is not None and not self._active_task.done():
            return
        next_job = next((job for job in self._jobs if job.state.status == "pending"), None)
        if next_job is None:
            return
        self._active_task = asyncio.create_task(self._run_job(next_job))

    def cancel_job(self, job_id: str) -> bool:
        job = self._find(job_id)
        if job is None:
            return False
        if job.state.status == "pending":
            job.state.status = "cancelled"
            job.state.completed_at = datetime.now(UTC)
            return True
        if job.state.status == "running" and self._active_task is not None:
            self._active_task.cancel()
            return True
        return False

    def clear_finished(self) -> None:
        self._jobs = [job for job in self._jobs if job.state.status in {"pending", "running"}]

    async def wait_idle(self) -> None:
        while self._active_task is not None and not self._active_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await self._active_task
        self.start_next()
        if self._active_task is not None and not self._active_task.done():
            await self.wait_idle()

    async def _run_job(self, job: GuiJob) -> None:
        job.state.status = "running"
        job.state.started_at = datetime.now(UTC)

        def event_sink(event: ServiceEvent) -> None:
            job.state.events.append(event)
            if event.event_type == "document_emitted":
                index = int(event.payload.get("index") or 0)
                total = int(event.payload.get("total") or 0)
                if total > 0:
                    job.state.progress = min(0.99, index / total)
            elif event.event_type == "validation_completed":
                job.state.progress = max(job.state.progress, 0.95)
            elif event.event_type == "phase_change" and event.phase in {"completed", "bulk_completed"}:
                job.state.progress = 1.0

        try:
            result = await job.runner(event_sink)
        except asyncio.CancelledError:
            job.state.status = "cancelled"
            job.state.completed_at = datetime.now(UTC)
            job.state.error = "Cancelled"
        except Exception as exc:
            job.state.status = "failed"
            job.state.completed_at = datetime.now(UTC)
            job.state.error = f"{type(exc).__name__}: {exc}"
            job.state.events.append(ServiceEvent(event_type="failure", message=job.state.error))
        else:
            job.state.status = "completed"
            job.state.completed_at = datetime.now(UTC)
            job.state.progress = 1.0
            if isinstance(result, BaseModel):
                job.state.summary = result.model_dump(mode="json")
            else:
                job.state.summary = {"result": result}
        finally:
            asyncio.get_running_loop().call_soon(self.start_next)

    def _find(self, job_id: str) -> GuiJob | None:
        return next((job for job in self._jobs if job.state.id == job_id), None)
