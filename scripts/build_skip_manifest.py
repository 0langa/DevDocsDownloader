from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from doc_ingest.config import load_config
from doc_ingest.models import LanguageRunCheckpoint, LanguageRunState
from doc_ingest.utils.filesystem import read_json, write_json


def build_manifest() -> dict[str, dict[str, object]]:
    config = load_config(ROOT)
    manifests: dict[str, dict[str, object]] = {}

    for state_path in sorted(config.paths.state_dir.glob("*.json")):
        payload = read_json(state_path, {})
        try:
            state = LanguageRunState.model_validate(payload)
        except Exception:
            manifests[state_path.stem] = {
                "slug": state_path.stem,
                "state_path": str(state_path),
                "valid": False,
                "error": "State file is not compatible with LanguageRunState.",
            }
            continue

        manifests[state.slug] = {
            "language": state.language,
            "slug": state.slug,
            "source": state.source,
            "source_slug": state.source_slug,
            "source_url": state.source_url,
            "mode": state.mode,
            "completed": state.completed,
            "total_documents": state.total_documents,
            "source_diagnostics": state.source_diagnostics.model_dump(mode="json")
            if state.source_diagnostics
            else None,
            "output_path": state.output_path,
            "topics": [{"topic": topic.topic, "document_count": topic.document_count} for topic in state.topics],
            "warnings": state.warnings,
            "failures": state.failures,
            "updated_at": state.updated_at.isoformat(),
            "valid": True,
        }

    return manifests


def build_checkpoint_manifest() -> dict[str, dict[str, object]]:
    config = load_config(ROOT)
    checkpoints: dict[str, dict[str, object]] = {}

    for checkpoint_path in sorted(config.paths.checkpoints_dir.glob("*.json")):
        payload = read_json(checkpoint_path, {})
        try:
            checkpoint = LanguageRunCheckpoint.model_validate(payload)
        except Exception:
            checkpoints[checkpoint_path.stem] = {
                "slug": checkpoint_path.stem,
                "checkpoint_path": str(checkpoint_path),
                "valid": False,
                "error": "Checkpoint file is not compatible with LanguageRunCheckpoint.",
            }
            continue

        checkpoints[checkpoint.slug] = {
            "language": checkpoint.language,
            "slug": checkpoint.slug,
            "source": checkpoint.source,
            "source_slug": checkpoint.source_slug,
            "mode": checkpoint.mode,
            "phase": checkpoint.phase,
            "document_inventory_position": checkpoint.document_inventory_position,
            "emitted_document_count": checkpoint.emitted_document_count,
            "output_path": checkpoint.output_path,
            "last_document": checkpoint.last_document.model_dump(mode="json") if checkpoint.last_document else None,
            "failures": [failure.model_dump(mode="json") for failure in checkpoint.failures],
            "updated_at": checkpoint.updated_at.isoformat(),
            "valid": True,
        }

    return checkpoints


def main() -> None:
    config = load_config(ROOT)
    manifest = {
        "generated_from": str(config.paths.root),
        "description": "Current compiled-language state and active checkpoint manifest. URL-level crawler skip state is not part of the active source-adapter pipeline.",
        "languages": build_manifest(),
        "checkpoints": build_checkpoint_manifest(),
    }
    output_path = config.paths.cache_dir / "state_manifest.json"
    write_json(output_path, manifest)
    print(f"Wrote state manifest to {output_path}")
    print(json.dumps({slug: data.get("total_documents", 0) for slug, data in manifest["languages"].items()}, indent=2))


if __name__ == "__main__":
    main()
