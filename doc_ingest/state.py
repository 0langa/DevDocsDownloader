from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointFailure,
    CheckpointPhase,
    DocumentArtifactCheckpoint,
    DocumentCheckpoint,
    LanguageRunCheckpoint,
    LanguageRunState,
)
from .utils.filesystem import read_json, write_json

LOGGER = logging.getLogger("doc_ingest")


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
        state.updated_at = datetime.now(UTC)
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
            return load_checkpoint_payload(payload, path=self.path)
        except Exception:
            return None

    def save(self, checkpoint: LanguageRunCheckpoint) -> None:
        checkpoint.updated_at = datetime.now(UTC)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, checkpoint.model_dump(mode="json"), durability="strict")

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

    def record_document_artifact(
        self,
        checkpoint: LanguageRunCheckpoint,
        document: DocumentArtifactCheckpoint,
    ) -> None:
        checkpoint.phase = "compiling"
        checkpoint.emitted_document_count += 1
        checkpoint.document_inventory_position = document.order_hint
        checkpoint.last_document = DocumentCheckpoint(
            topic=document.topic,
            slug=document.slug,
            title=document.title,
            source_url=document.source_url,
            order_hint=document.order_hint,
        )
        checkpoint.emitted_documents.append(document)
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


def load_checkpoint_payload(payload: object, *, path: Path) -> LanguageRunCheckpoint | None:
    if not isinstance(payload, dict):
        return None
    schema_version = payload.get("schema_version")
    if schema_version != CHECKPOINT_SCHEMA_VERSION:
        LOGGER.warning(
            "Discarding checkpoint %s due to schema version mismatch: expected=%s actual=%r",
            path,
            CHECKPOINT_SCHEMA_VERSION,
            schema_version,
        )
        return None
    try:
        return LanguageRunCheckpoint.model_validate(payload)
    except Exception as exc:
        LOGGER.warning("Discarding invalid checkpoint %s: %s", path, exc)
        return None
