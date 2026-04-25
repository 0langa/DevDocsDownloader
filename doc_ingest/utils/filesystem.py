from __future__ import annotations

import importlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

try:
    _orjson: Any | None = importlib.import_module("orjson")
except ImportError:  # pragma: no cover
    _orjson = None


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    if _orjson is not None:
        return _orjson.loads(path.read_bytes())
    return json.loads(path.read_text(encoding="utf-8"))


DurabilityMode = Literal["strict", "balanced"]


def _sync_if_strict(handle, durability: DurabilityMode) -> None:
    if durability == "strict":
        os.fsync(handle.fileno())


def write_json(path: Path, data: Any, *, durability: DurabilityMode = "strict") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _orjson is not None:
        payload_bytes = _orjson.dumps(data, option=_orjson.OPT_INDENT_2)
    else:
        payload_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("wb") as handle:
        handle.write(payload_bytes)
        handle.flush()
        _sync_if_strict(handle, durability)
    temp_path.replace(path)


def write_text(path: Path, text: str, *, durability: DurabilityMode = "strict") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("wb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        _sync_if_strict(handle, durability)
    temp_path.replace(path)


def write_text_parts(path: Path, parts: Iterable[str], *, durability: DurabilityMode = "strict") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("wb") as handle:
        for part in parts:
            handle.write(part.encode("utf-8"))
        handle.flush()
        _sync_if_strict(handle, durability)
    temp_path.replace(path)


def write_bytes(path: Path, payload_bytes: bytes, *, durability: DurabilityMode = "strict") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("wb") as handle:
        handle.write(payload_bytes)
        handle.flush()
        _sync_if_strict(handle, durability)
    temp_path.replace(path)
