from __future__ import annotations

import json
from pathlib import Path


def app_version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "version.json"
    payload = json.loads(version_file.read_text(encoding="utf-8"))
    return str(payload["version"])
