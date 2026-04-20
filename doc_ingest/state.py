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
        pages = {key: PageState.model_validate(value) for key, value in payload.get("pages", {}).items()}
        payload["pages"] = pages
        return CrawlState.model_validate(payload)

    def save(self, state: CrawlState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, state.model_dump(mode="json"))

