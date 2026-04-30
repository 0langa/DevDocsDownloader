from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from doc_ingest.config import load_config
from doc_ingest.desktop_backend import create_app
from doc_ingest.models import RunSummary
from doc_ingest.services import DocumentationService, RunLanguageRequest, ServiceEvent


def test_backend_job_lifecycle_queue_cancel_and_replay(tmp_path: Path, monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_language(self, request: RunLanguageRequest, *, progress_tracker=None, event_sink=None):
        if event_sink is not None:
            await event_sink(ServiceEvent(event_type="activity", language=request.language, message="first"))
            await event_sink(ServiceEvent(event_type="activity", language=request.language, message="second"))
        if request.language == "python":
            started.set()
            await release.wait()
        return RunSummary()

    monkeypatch.setattr(DocumentationService, "run_language", fake_run_language)
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": "Bearer secret"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            first = await client.post("/jobs/run-language", headers=headers, json={"language": "python"})
            assert first.status_code == 202
            await asyncio.wait_for(started.wait(), timeout=1.0)

            second = await client.post("/jobs/run-language", headers=headers, json={"language": "rust"})
            assert second.status_code == 202
            assert second.json()["status"] == "pending"

            queued_cancel = await client.post(f"/jobs/{second.json()['id']}/cancel", headers=headers)
            assert queued_cancel.status_code == 200
            assert queued_cancel.json()["status"] == "cancelled"

            running_cancel = await client.post(f"/jobs/{first.json()['id']}/cancel", headers=headers)
            assert running_cancel.status_code == 200
            assert running_cancel.json()["status"] in {"cancelling", "cancelled"}
            release.set()

            for _ in range(50):
                status = await client.get(f"/jobs/{first.json()['id']}", headers=headers)
                if status.json()["status"] == "cancelled":
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("running job did not cancel")

            replay = await client.get(f"/jobs/{first.json()['id']}/events?from_index=3", headers=headers)
            assert replay.status_code == 200
            assert "second" in replay.text
            assert "cancelled" in replay.text or "cancelling" in replay.text

    asyncio.run(scenario())
