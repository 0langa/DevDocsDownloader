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
    installer_script = (ROOT / "desktop" / "installer" / "DevDocsDownloader.iss").read_text(encoding="utf-8")
    app_manifest = (ROOT / "desktop" / "DevDocsDownloader.Desktop" / "app.manifest").read_text(encoding="utf-8")

    pyproject_version = _match(pyproject, r'^version = "([^"]+)"$')
    desktop_version = _match(desktop_project, r"<Version>([^<]+)</Version>")
    installer_version = _match(installer_script, r'#define MyAppVersion "([^"]+)"')
    manifest_version = _match(app_manifest, r'<assemblyIdentity version="([^"]+)"')

    mismatches: list[str] = []
    if pyproject_version != version:
        mismatches.append(f"pyproject.toml={pyproject_version}")
    if desktop_version != version:
        mismatches.append(f"desktop csproj={desktop_version}")
    if installer_version != version:
        mismatches.append(f"installer iss={installer_version}")
    if manifest_version != _pad_to_four(version):
        mismatches.append(f"app manifest={manifest_version}")
    if mismatches:
        joined = ", ".join(mismatches)
        raise SystemExit(f"Version mismatch for {version}: {joined}")

    print(f"[version] OK: {version}")


def _pad_to_four(version: str) -> str:
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def _match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"Pattern not found: {pattern}")
    return match.group(1)


if __name__ == "__main__":
    main()
