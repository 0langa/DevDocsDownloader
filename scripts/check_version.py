from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    desktop_project = (ROOT / "desktop" / "DevDocsDownloader.Desktop" / "DevDocsDownloader.Desktop.csproj").read_text(
        encoding="utf-8"
    )

    pyproject_version = _match(pyproject, r'^version = "([^"]+)"$')
    desktop_version = _match(desktop_project, r"<Version>([^<]+)</Version>")

    mismatches: list[str] = []
    if pyproject_version != version:
        mismatches.append(f"pyproject.toml={pyproject_version}")
    if desktop_version != version:
        mismatches.append(f"desktop csproj={desktop_version}")
    if mismatches:
        joined = ", ".join(mismatches)
        raise SystemExit(f"Version mismatch for {version}: {joined}")

    print(f"[version] OK: {version}")


def _match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"Pattern not found: {pattern}")
    return match.group(1)


if __name__ == "__main__":
    main()
