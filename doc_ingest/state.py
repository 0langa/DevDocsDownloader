from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import LanguageRunState
from .utils.filesystem import read_json, write_json


class RunStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, *, default: LanguageRunState) -> LanguageRunState:
        if not self.path.exists():
            return default
        try:
            payload = read_json(self.path, default.model_dump(mode="json"))
            return LanguageRunState.model_validate(payload)
        except Exception:
            return default

    def save(self, state: LanguageRunState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, state.model_dump(mode="json"))
