from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from doc_ingest.config import load_config
from doc_ingest.desktop_backend import create_app
from doc_ingest.desktop_settings import DesktopSettings, DesktopSettingsStore
from doc_ingest.models import RunSummary
from doc_ingest.services import (
    CatalogRefreshResult,
    DocumentationService,
    LanguageEntry,
    RunLanguageRequest,
    ServiceEvent,
)


def test_load_config_desktop_mode_uses_per_user_style_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    config = load_config(runtime_mode="desktop")

    assert config.runtime_mode == "desktop"
    assert config.paths.cache_dir == (tmp_path / "local" / "DevDocsDownloader" / "cache")
    assert config.paths.state_dir == (tmp_path / "local" / "DevDocsDownloader" / "state")
    assert config.paths.settings_path == (tmp_path / "local" / "DevDocsDownloader" / "settings.json")
    assert config.paths.output_dir.name == "DevDocsDownloader"


def test_desktop_settings_store_round_trips(tmp_path: Path) -> None:
    store = DesktopSettingsStore(tmp_path / "settings.json")
    settings = DesktopSettings(
        output_dir=tmp_path / "out",
        cache_policy="ttl",
        cache_ttl_hours=24,
        emit_chunks=True,
        language_tree_mode="category",
        language_search="python",
        last_output_language_slug="python",
        last_output_relative_path="python.md",
        last_selected_preset="webapp",
    )

    store.save(settings)
    loaded = store.load()

    assert loaded.output_dir == tmp_path / "out"
    assert loaded.cache_policy == "ttl"
    assert loaded.cache_ttl_hours == 24
    assert loaded.emit_chunks is True
    assert loaded.language_tree_mode == "category"
    assert loaded.language_search == "python"
    assert loaded.last_output_language_slug == "python"
    assert loaded.last_output_relative_path == "python.md"
    assert loaded.last_selected_preset == "webapp"


def test_desktop_backend_requires_bearer_token(tmp_path: Path) -> None:
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            denied = await client.get("/health")
            allowed = await client.get("/health", headers={"Authorization": "Bearer secret"})
        assert denied.status_code == 401
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "ok"

    asyncio.run(scenario())


def test_desktop_backend_run_language_job_and_events(tmp_path: Path, monkeypatch) -> None:
    async def fake_run_language(self, request: RunLanguageRequest, *, progress_tracker=None, event_sink=None):
        if event_sink is not None:
            await event_sink(
                ServiceEvent(
                    event_type="activity",
                    language=request.language,
                    message="Downloading guide index",
                    payload={"step": "fetch_catalog", "completed": 0, "total": 1},
                )
            )
            await event_sink(
                ServiceEvent(
                    event_type="phase_change",
                    language=request.language,
                    phase="fetching",
                    message="Fetching source inventory",
                )
            )
            await event_sink(
                ServiceEvent(
                    event_type="document_emitted",
                    language=request.language,
                    payload={"index": 1, "total": 1, "title": "Intro", "topic": "Guide", "phase": "compiling"},
                )
            )
            await event_sink(
                ServiceEvent(event_type="validation_completed", language=request.language, payload={"score": 1.0})
            )
        return RunSummary()

    monkeypatch.setattr(DocumentationService, "run_language", fake_run_language)
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": "Bearer secret"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            created = await client.post("/jobs/run-language", headers=headers, json={"language": "Python"})
            assert created.status_code == 202
            job_id = created.json()["id"]

            for _ in range(50):
                status = await client.get(f"/jobs/{job_id}", headers=headers)
                assert status.status_code == 200
                if status.json()["status"] == "completed":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("job did not complete")

            stream = await client.get(f"/jobs/{job_id}/events", headers=headers)
            assert stream.status_code == 200
            body = stream.text
            assert "activity" in body
            assert "phase_change" in body
            assert "document_emitted" in body
            assert "validation_completed" in body
            assert "Downloading guide index" in body
            assert '"title": "Intro"' in body
            assert '"topic": "Guide"' in body

    asyncio.run(scenario())


def test_desktop_backend_languages_and_settings_endpoints(tmp_path: Path, monkeypatch) -> None:
    async def fake_list_languages(self, *, source=None, force_refresh=False):
        return [LanguageEntry(language="Python", source="devdocs", slug="python", version="3.13")]

    monkeypatch.setattr(DocumentationService, "list_languages", fake_list_languages)
    settings_store = DesktopSettingsStore(tmp_path / "settings.json")
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret", settings_store=settings_store)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": "Bearer secret"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            languages = await client.get("/languages", headers=headers)
            assert languages.status_code == 200
            assert languages.json()[0]["language"] == "Python"

            updated = await client.put(
                "/settings",
                headers=headers,
                json={
                    "cache_policy": "ttl",
                    "cache_ttl_hours": 8,
                    "emit_chunks": True,
                    "language_tree_mode": "category",
                    "language_search": "rust",
                    "last_output_language_slug": "rust",
                    "last_output_relative_path": "async/streams.md",
                    "last_selected_preset": "backend",
                },
            )
            assert updated.status_code == 200
            payload = settings_store.load().model_dump(mode="json")
            assert payload["cache_policy"] == "ttl"
            assert payload["cache_ttl_hours"] == 8
            assert payload["emit_chunks"] is True
            assert payload["language_tree_mode"] == "category"
            assert payload["language_search"] == "rust"
            assert payload["last_output_language_slug"] == "rust"
            assert payload["last_output_relative_path"] == "async/streams.md"
            assert payload["last_selected_preset"] == "backend"

            fetched = await client.get("/settings", headers=headers)
            assert fetched.status_code == 200
            assert fetched.json()["cache_policy"] == "ttl"
            assert fetched.json()["language_tree_mode"] == "category"

    asyncio.run(scenario())


def test_desktop_backend_refresh_catalogs_returns_structured_status(tmp_path: Path, monkeypatch) -> None:
    async def fake_refresh_catalogs(self):
        return [
            CatalogRefreshResult(source="devdocs", status="refreshed", entry_count=10),
            CatalogRefreshResult(
                source="mdn",
                status="fallback",
                entry_count=6,
                fallback_used=True,
                fallback_reason="cached manifest",
            ),
        ]

    monkeypatch.setattr(DocumentationService, "refresh_catalogs", fake_refresh_catalogs)
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": "Bearer secret"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/refresh-catalogs", headers=headers)
            assert response.status_code == 200
            payload = response.json()
            assert payload[0]["source"] == "devdocs"
            assert payload[0]["status"] == "refreshed"
            assert payload[1]["status"] == "fallback"
            assert payload[1]["fallback_reason"] == "cached manifest"

    asyncio.run(scenario())


def test_desktop_backend_output_storage_management_endpoints(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        config = load_config(root=tmp_path, runtime_mode="repo")
        app = create_app(config, token="secret")
        headers = {"Authorization": "Bearer secret"}

        language_dir = config.paths.markdown_dir / "python"
        language_dir.mkdir(parents=True, exist_ok=True)
        (language_dir / "_meta.json").write_text(
            '{"language":"Python","source":"devdocs","source_slug":"python","total_documents":1,"topics":[]}',
            encoding="utf-8",
        )
        (language_dir / "python.md").write_text("# Python\n", encoding="utf-8")
        history_dir = config.paths.reports_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "20260101T000000Z-run_summary.json").write_text("{}", encoding="utf-8")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            summary = await client.get("/output/storage-summary", headers=headers)
            assert summary.status_code == 200
            assert summary.json()["bundle_count"] == 1

            deleted = await client.delete("/output/python", headers=headers)
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
            assert not language_dir.exists()

            pruned = await client.post("/reports/prune-history?keep_latest=0", headers=headers)
            assert pruned.status_code == 200
            assert pruned.json()["deleted_files"] == 1
            assert not history_dir.exists()

    asyncio.run(scenario())


def test_desktop_backend_cancel_sets_cancelling_then_cancelled(tmp_path: Path, monkeypatch) -> None:
    async def fake_run_language(self, request: RunLanguageRequest, *, progress_tracker=None, event_sink=None):
        if event_sink is not None:
            await event_sink(ServiceEvent(event_type="phase_change", language=request.language, phase="fetching"))
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        return RunSummary()

    monkeypatch.setattr(DocumentationService, "run_language", fake_run_language)
    app = create_app(load_config(root=tmp_path, runtime_mode="repo"), token="secret")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": "Bearer secret"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            created = await client.post("/jobs/run-language", headers=headers, json={"language": "Python"})
            assert created.status_code == 202
            job_id = created.json()["id"]

            cancelled = await client.post(f"/jobs/{job_id}/cancel", headers=headers)
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] in {"cancelling", "cancelled"}

            for _ in range(50):
                status = await client.get(f"/jobs/{job_id}", headers=headers)
                assert status.status_code == 200
                if status.json()["status"] == "cancelled":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("job did not cancel")

            stream = await client.get(f"/jobs/{job_id}/events", headers=headers)
            assert stream.status_code == 200
            assert '"phase": "cancelling"' in stream.text or '"phase": "cancelled"' in stream.text

    asyncio.run(scenario())
