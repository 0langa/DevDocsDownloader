from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import CheckpointFailure, CheckpointPhase, DocumentCheckpoint, LanguageRunCheckpoint, LanguageRunState
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


class RunCheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> LanguageRunCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            payload = read_json(self.path, {})
            return LanguageRunCheckpoint.model_validate(payload)
        except Exception:
            return None

    def save(self, checkpoint: LanguageRunCheckpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, checkpoint.model_dump(mode="json"))

    def update_phase(
        self,
        checkpoint: LanguageRunCheckpoint,
        phase: CheckpointPhase,
        *,
        output_path: str | None = None,
    ) -> None:
        checkpoint.phase = phase
        if output_path is not None:
            checkpoint.output_path = output_path
        self.save(checkpoint)

    def record_document(self, checkpoint: LanguageRunCheckpoint, document: DocumentCheckpoint) -> None:
        checkpoint.phase = "compiling"
        checkpoint.emitted_document_count += 1
        checkpoint.document_inventory_position = document.order_hint
        checkpoint.last_document = document
        self.save(checkpoint)

    def record_failure(
        self,
        checkpoint: LanguageRunCheckpoint,
        *,
        phase: CheckpointPhase,
        error_type: str,
        message: str,
    ) -> None:
        checkpoint.phase = "failed"
        checkpoint.failures.append(
            CheckpointFailure(
                phase=phase,
                error_type=error_type,
                message=message,
                document_inventory_position=checkpoint.document_inventory_position,
                emitted_document_count=checkpoint.emitted_document_count,
            )
        )
        self.save(checkpoint)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
