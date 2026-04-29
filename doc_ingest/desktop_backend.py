from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import AppConfig, load_config
from .desktop_settings import DesktopSettings, DesktopSettingsStore, settings_from_config
from .services import BulkRunRequest, DocumentationService, RunLanguageRequest, ServiceEvent
from .version import app_version

LOGGER = logging.getLogger("doc_ingest.desktop_backend")
BACKEND_API_VERSION = app_version()


class BackendJobSummary(BaseModel):
    id: str
    kind: Literal["run_language", "run_bulk", "validate"]
    status: Literal["pending", "running", "cancelling", "completed", "failed", "cancelled"]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    language: str = ""
    detail: str = ""
    error: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)


class BackendJob:
    def __init__(self, *, job_id: str, kind: str, language: str, detail: str) -> None:
        self.id = job_id
        self.kind = kind
        self.language = language
        self.detail = detail
        self.status: Literal["pending", "running", "cancelling", "completed", "failed", "cancelled"] = "pending"
        self.created_at = datetime.now(UTC)
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error = ""
        self.summary: dict[str, Any] = {}
        self.events: list[ServiceEvent] = []
        self._event_queue: asyncio.Queue[ServiceEvent | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None

    def snapshot(self) -> BackendJobSummary:
        return BackendJobSummary(
            id=self.id,
            kind=self.kind,  # type: ignore[arg-type]
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            language=self.language,
            detail=self.detail,
            error=self.error,
            summary=self.summary,
        )

    async def publish(self, event: ServiceEvent) -> None:
        self.events.append(event)
        await self._event_queue.put(event)

    async def close_stream(self) -> None:
        await self._event_queue.put(None)

    async def stream(self, *, from_index: int = 0) -> AsyncIterator[bytes]:
        heartbeat = 15.0
        next_index = from_index
        while next_index < len(self.events):
            history_event = self.events[next_index]
            next_index += 1
            yield _encode_sse("event", history_event.model_dump(mode="json"))
        while True:
            try:
                async with asyncio.timeout(heartbeat):
                    queued_event: ServiceEvent | None = await self._next_event()
            except TimeoutError:
                yield b": keep-alive\n\n"
                continue
            if queued_event is None:
                break
            next_index += 1
            yield _encode_sse("event", queued_event.model_dump(mode="json"))
        yield _encode_sse("complete", {"job_id": self.id, "status": self.status})

    async def _next_event(self) -> ServiceEvent | None:
        return await self._event_queue.get()


class BackendJobManager:
    def __init__(self, service: DocumentationService, *, history_path: Path | None = None) -> None:
        self.service = service
        self.jobs: dict[str, BackendJob] = {}
        self.active_job_id: str | None = None
        self._lock = asyncio.Lock()
        self._history_path = history_path
        self._historical_summaries: list[BackendJobSummary] = []
        if history_path is not None:
            self._load_history()

    def _load_history(self) -> None:
        if self._history_path is None or not self._history_path.exists():
            return
        try:
            for line in self._history_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._historical_summaries.append(BackendJobSummary.model_validate(json.loads(line)))
                except Exception as exc:
                    LOGGER.warning("Skipping malformed job history entry: %s", exc)
        except Exception as exc:
            LOGGER.warning("Failed to load job history from %s: %s", self._history_path, exc)
        self._historical_summaries = self._historical_summaries[-50:]

    def _persist_summary(self, summary: BackendJobSummary) -> None:
        if self._history_path is None:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            with self._history_path.open("a", encoding="utf-8") as f:
                f.write(summary.model_dump_json() + "\n")
            self._historical_summaries.append(summary)
            self._historical_summaries = self._historical_summaries[-50:]
        except Exception as exc:
            LOGGER.warning("Failed to persist job summary: %s", exc)

    async def submit_run_language(self, request: RunLanguageRequest) -> BackendJobSummary:
        kind = "validate" if request.validate_only else "run_language"
        detail = request.language if request.validate_only else f"{request.language}:{request.mode}"
        return await self._submit(
            kind=kind,
            language=request.language,
            detail=detail,
            runner=lambda event_sink: self.service.run_language(request, event_sink=event_sink),
        )

    async def submit_run_bulk(self, request: BulkRunRequest) -> BackendJobSummary:
        detail = f"{len(request.languages)} language(s)"
        return await self._submit(
            kind="run_bulk",
            language="bulk",
            detail=detail,
            runner=lambda event_sink: self.service.run_bulk(request, event_sink=event_sink),
        )

    def list_jobs(self) -> list[BackendJobSummary]:
        active = [job.snapshot() for job in sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)]
        active_ids = {s.id for s in active}
        historical = [s for s in reversed(self._historical_summaries) if s.id not in active_ids]
        return (active + historical)[:100]

    def get(self, job_id: str) -> BackendJob:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}") from exc

    async def cancel(self, job_id: str) -> BackendJobSummary:
        job = self.get(job_id)
        if job.status in {"completed", "failed", "cancelled"}:
            return job.snapshot()
        if job.task is None:
            raise HTTPException(status_code=409, detail="Job is not running")
        if job.status == "pending":
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC)
            job.error = "Cancelled"
            if self.active_job_id == job.id:
                self.active_job_id = None
            job.task.cancel()
            await job.publish(ServiceEvent(event_type="phase_change", language=job.language, phase="cancelled"))
            await job.close_stream()
            return job.snapshot()
        job.status = "cancelling"
        await job.publish(ServiceEvent(event_type="phase_change", language=job.language, phase="cancelling"))
        job.task.cancel()
        return job.snapshot()

    async def _submit(self, *, kind: str, language: str, detail: str, runner) -> BackendJobSummary:
        async with self._lock:
            active = self._active_job()
            if active is not None:
                raise HTTPException(status_code=409, detail=f"Job already running: {active.id}")
            job = BackendJob(job_id=uuid4().hex, kind=kind, language=language, detail=detail)
            self.jobs[job.id] = job
            self.active_job_id = job.id
            job.task = asyncio.create_task(self._run_job(job, runner))
            return job.snapshot()

    async def _run_job(self, job: BackendJob, runner) -> None:
        job.status = "running"
        job.started_at = datetime.now(UTC)

        async def event_sink(event: ServiceEvent) -> None:
            await job.publish(event)
            # Yield to the event loop between events so asyncio.CancelledError can
            # propagate through the pipeline when task.cancel() is called.
            await asyncio.sleep(0)

        try:
            result = await runner(event_sink)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC)
            job.error = "Cancelled"
            await job.publish(ServiceEvent(event_type="failure", language=job.language, message=job.error))
            raise
        except Exception as exc:
            job.status = "failed"
            job.completed_at = datetime.now(UTC)
            job.error = f"{type(exc).__name__}: {exc}"
            await job.publish(ServiceEvent(event_type="failure", language=job.language, message=job.error))
        else:
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            if isinstance(result, BaseModel):
                job.summary = result.model_dump(mode="json")
            else:
                job.summary = {"result": result}
        finally:
            self.active_job_id = None
            await job.close_stream()
            self._persist_summary(job.snapshot())

    def _active_job(self) -> BackendJob | None:
        if self.active_job_id is None:
            return None
        job = self.jobs.get(self.active_job_id)
        if job is None or job.status in {"completed", "failed", "cancelled"}:
            self.active_job_id = None
            return None
        return job


def create_app(
    config: AppConfig,
    *,
    token: str,
    settings_store: DesktopSettingsStore | None = None,
) -> FastAPI:
    app = FastAPI(title="DevDocsDownloader Desktop Backend", version=BACKEND_API_VERSION)
    settings_store = settings_store or DesktopSettingsStore(config.paths.settings_path)
    service = DocumentationService(config)
    jobs = BackendJobManager(service, history_path=config.paths.logs_dir / "job_history.jsonl")

    async def require_auth(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    @app.get("/health", dependencies=[Depends(require_auth)])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": BACKEND_API_VERSION,
            "active_job_id": jobs.active_job_id,
            "runtime_mode": config.runtime_mode,
        }

    @app.get("/version", dependencies=[Depends(require_auth)])
    async def version() -> dict[str, str]:
        return {"api_version": BACKEND_API_VERSION, "app_version": BACKEND_API_VERSION}

    @app.post("/shutdown", dependencies=[Depends(require_auth)])
    async def shutdown_endpoint() -> dict[str, str]:
        server = getattr(app.state, "server", None)
        if server is not None:
            server.should_exit = True
        return {"status": "shutting_down"}

    @app.get("/languages", dependencies=[Depends(require_auth)])
    async def languages(source: str | None = None, force_refresh: bool = False) -> list[dict[str, Any]]:
        rows = await service.list_languages(source=source, force_refresh=force_refresh)
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/presets", dependencies=[Depends(require_auth)])
    async def presets() -> dict[str, list[str]]:
        return service.list_presets()

    @app.post("/audit-presets", dependencies=[Depends(require_auth)])
    async def audit_presets(body: dict[str, Any]) -> list[dict[str, Any]]:
        results = await service.audit_presets(
            presets=body.get("presets"),
            source=body.get("source"),
            force_refresh=bool(body.get("force_refresh", False)),
        )
        return [item.model_dump(mode="json") for item in results]

    @app.post("/refresh-catalogs", dependencies=[Depends(require_auth)])
    async def refresh_catalogs() -> dict[str, int]:
        return await service.refresh_catalogs()

    @app.get("/settings", dependencies=[Depends(require_auth)])
    async def get_settings() -> dict[str, Any]:
        settings = settings_store.load(default=settings_from_config(config))
        return settings.model_dump(mode="json")

    @app.put("/settings", dependencies=[Depends(require_auth)])
    async def save_settings(payload: DesktopSettings) -> dict[str, Any]:
        settings_store.save(payload)
        return payload.model_dump(mode="json")

    @app.post("/jobs/run-language", dependencies=[Depends(require_auth)], status_code=202)
    async def run_language(request: RunLanguageRequest) -> dict[str, Any]:
        summary = await jobs.submit_run_language(request)
        return summary.model_dump(mode="json")

    @app.post("/jobs/run-bulk", dependencies=[Depends(require_auth)], status_code=202)
    async def run_bulk(request: BulkRunRequest) -> dict[str, Any]:
        summary = await jobs.submit_run_bulk(request)
        return summary.model_dump(mode="json")

    @app.post("/jobs/validate", dependencies=[Depends(require_auth)], status_code=202)
    async def validate(request: RunLanguageRequest) -> dict[str, Any]:
        validated = request.model_copy(update={"validate_only": True})
        summary = await jobs.submit_run_language(validated)
        return summary.model_dump(mode="json")

    @app.get("/jobs", dependencies=[Depends(require_auth)])
    async def list_jobs() -> list[dict[str, Any]]:
        return [job.model_dump(mode="json") for job in jobs.list_jobs()]

    @app.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
    async def job_status(job_id: str) -> dict[str, Any]:
        return jobs.get(job_id).snapshot().model_dump(mode="json")

    @app.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_auth)])
    async def cancel_job(job_id: str) -> dict[str, Any]:
        snapshot = await jobs.cancel(job_id)
        return snapshot.model_dump(mode="json")

    @app.get("/jobs/{job_id}/events", dependencies=[Depends(require_auth)])
    async def job_events(job_id: str, from_index: int = Query(default=0, ge=0)) -> StreamingResponse:
        job = jobs.get(job_id)
        return StreamingResponse(job.stream(from_index=from_index), media_type="text/event-stream")

    @app.get("/runtime/snapshot", dependencies=[Depends(require_auth)])
    async def runtime_snapshot() -> dict[str, Any]:
        return service.inspect_runtime().model_dump(mode="json")

    @app.get("/output/bundles", dependencies=[Depends(require_auth)])
    async def output_bundles() -> list[dict[str, Any]]:
        return [bundle.model_dump(mode="json") for bundle in service.list_output_bundles()]

    @app.get("/output/{language_slug}/tree", dependencies=[Depends(require_auth)])
    async def output_tree(language_slug: str) -> dict[str, Any]:
        return service.output_tree(language_slug).model_dump(mode="json")

    @app.get("/output/{language_slug}/meta", dependencies=[Depends(require_auth)])
    async def output_meta(language_slug: str) -> dict[str, Any]:
        return service.read_meta(language_slug)

    @app.get("/output/{language_slug}/file", dependencies=[Depends(require_auth)])
    async def output_file(language_slug: str, path: str) -> dict[str, Any]:
        return service.read_output_file(language_slug, path).model_dump(mode="json")

    @app.get("/reports", dependencies=[Depends(require_auth)])
    async def reports() -> dict[str, Any]:
        return service.read_reports().model_dump(mode="json")

    @app.get("/reports/file", dependencies=[Depends(require_auth)])
    async def report_file(path: str) -> dict[str, Any]:
        return service.read_report_file(path).model_dump(mode="json")

    @app.get("/checkpoints", dependencies=[Depends(require_auth)])
    async def checkpoints() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_checkpoints()]

    @app.get("/checkpoints/{slug}", dependencies=[Depends(require_auth)])
    async def checkpoint(slug: str) -> dict[str, Any]:
        return service.read_checkpoint(slug)

    @app.delete("/checkpoints/{slug}", dependencies=[Depends(require_auth)])
    async def delete_checkpoint(slug: str) -> dict[str, bool]:
        return {"deleted": service.delete_checkpoint(slug)}

    @app.get("/cache/metadata", dependencies=[Depends(require_auth)])
    async def cache_metadata() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_cache_metadata()]

    @app.exception_handler(FileNotFoundError)
    async def handle_missing(_request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(IsADirectoryError)
    async def handle_directory(_request, exc: IsADirectoryError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_value_error(_request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


def run_backend_server(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str,
    output_dir: Path | None = None,
) -> None:
    config = load_config(output_dir=output_dir, runtime_mode="desktop")
    config.paths.ensure()
    app = create_app(config, token=token)
    logging.basicConfig(
        level=logging.INFO,
        filename=config.paths.logs_dir / "desktop-backend.log",
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            server_header=False,
            date_header=False,
        )
    )
    app.state.server = server
    server.run()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the DevDocsDownloader desktop backend worker.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=os.environ.get("DEVDOCS_BACKEND_TOKEN", ""))
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.token:
        raise SystemExit("--token or DEVDOCS_BACKEND_TOKEN is required")
    run_backend_server(host=args.host, port=args.port, token=args.token, output_dir=args.output_dir)


def _encode_sse(event_name: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=True)
    return f"event: {event_name}\ndata: {body}\n\n".encode()


if __name__ == "__main__":
    main()
