from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticAvailability:
    available: bool
    reason: str


def detect_semantic_availability() -> SemanticAvailability:
    try:
        __import__("sentence_transformers")
    except Exception:
        return SemanticAvailability(available=False, reason="sentence_transformers not installed")
    return SemanticAvailability(available=True, reason="semantic dependency available")
