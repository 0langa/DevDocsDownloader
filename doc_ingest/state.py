from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import CrawlState, PageState
from .utils.filesystem import read_json, write_json


class CrawlStateStore:
    def __init__(self, path: Path, *, language: str, slug: str, source_url: str) -> None:
        self.path = path
        self._fallback = CrawlState(language=language, slug=slug, source_url=source_url)

    def load(self) -> CrawlState:
        payload = read_json(self.path, self._fallback.model_dump(mode="json"))
        merged = self._fallback.model_dump(mode="json")
        normalized_payload = self._normalize_payload(payload)
        merged.update({key: value for key, value in normalized_payload.items() if key != "pages"})
        merged["pages"] = {
            key: PageState.model_validate(value)
            for key, value in normalized_payload.get("pages", {}).items()
        }
        return CrawlState.model_validate(merged)

    def save(self, state: CrawlState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, state.model_dump(mode="json"))

    def _normalize_payload(self, payload: dict) -> dict:
        if {"language", "slug", "source_url"}.issubset(payload.keys()) and "processed" not in payload:
            return payload

        migrated = self._fallback.model_dump(mode="json")
        migrated["started_at"] = payload.get("started_at", migrated["started_at"])
        migrated["updated_at"] = payload.get("updated_at", migrated["updated_at"])
        migrated["compiled"] = bool(payload.get("compiled", False))
        migrated["compiled_at"] = payload.get("compiled_at")
        migrated["output_path"] = payload.get("output_path")
        migrated["plan"] = payload.get("plan", {})
        migrated["warnings"] = list(payload.get("warnings", []))
        migrated["failures"] = list(payload.get("failures", []))

        pages: dict[str, dict] = {}
        for normalized_url, value in payload.get("pages", {}).items():
            if isinstance(value, dict):
                pages[normalized_url] = value

        for normalized_url, entry in payload.get("processed", {}).items():
            if normalized_url in pages:
                continue
            page_data = entry if isinstance(entry, dict) else {}
            pages[normalized_url] = {
                "normalized_url": normalized_url,
                "discovered_url": normalized_url,
                "title": page_data.get("title"),
                "status": "processed",
                "asset_type": page_data.get("asset_type"),
                "content_hash": page_data.get("hash"),
            }

        for status_key in ("failed", "pending", "discovered", "skipped"):
            status = "failed" if status_key == "failed" else status_key
            items = payload.get(status_key, {})
            if not isinstance(items, dict):
                continue
            for normalized_url, entry in items.items():
                if normalized_url in pages:
                    continue
                page_data = entry if isinstance(entry, dict) else {}
                message = entry if isinstance(entry, str) else page_data.get("last_error") or page_data.get("message")
                page_payload = {
                    "normalized_url": normalized_url,
                    "discovered_url": page_data.get("discovered_url", normalized_url),
                    "title": page_data.get("title"),
                    "status": status,
                    "asset_type": page_data.get("asset_type"),
                }
                if message:
                    page_payload["last_error"] = message
                pages[normalized_url] = page_payload
                if status == "failed" and message:
                    migrated["failures"].append(f"{normalized_url}: {message}")

        migrated["pages"] = pages
        return migrated

