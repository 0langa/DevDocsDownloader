from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path


def app_version() -> str:
    try:
        return metadata.version("devdocsdownloader")
    except metadata.PackageNotFoundError:
        pass
    for version_file in _version_file_candidates():
        if version_file.is_file():
            payload = json.loads(version_file.read_text(encoding="utf-8"))
            return str(payload["version"])
    searched = ", ".join(str(path) for path in _version_file_candidates())
    raise FileNotFoundError(f"Could not locate version.json. Searched: {searched}")


def _version_file_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = [Path(__file__).resolve().parent.parent / "version.json"]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "version.json")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "version.json")
        candidates.append(exe_dir.parent / "version.json")
    # Keep order stable, drop duplicates.
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)
