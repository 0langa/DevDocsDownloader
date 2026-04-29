from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import doc_ingest.version as version_module


@pytest.fixture(autouse=True)
def restore_sys_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "", raising=False)


def test_app_version_reads_repo_version_file() -> None:
    payload = json.loads((Path(__file__).resolve().parents[1] / "version.json").read_text(encoding="utf-8"))
    original = version_module.metadata.version
    version_module.metadata.version = lambda _name: (_ for _ in ()).throw(
        version_module.metadata.PackageNotFoundError()
    )  # type: ignore[assignment]
    try:
        assert version_module.app_version() == payload["version"]
    finally:
        version_module.metadata.version = original  # type: ignore[assignment]


def test_app_version_prefers_installed_package_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_module.metadata, "version", lambda _name: "7.7.7")
    assert version_module.app_version() == "7.7.7"


def test_app_version_uses_pyinstaller_meipass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    version_file = tmp_path / "version.json"
    version_file.write_text('{"version": "9.9.9"}', encoding="utf-8")

    module_root = tmp_path / "missing_root" / "doc_ingest"
    module_root.mkdir(parents=True)
    fake_module_file = module_root / "version.py"
    fake_module_file.write_text("# synthetic", encoding="utf-8")

    monkeypatch.setattr(version_module, "__file__", str(fake_module_file))
    monkeypatch.setattr(
        version_module.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(version_module.metadata.PackageNotFoundError()),
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert version_module.app_version() == "9.9.9"


def test_app_version_raises_clear_error_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module_root = tmp_path / "missing_root" / "doc_ingest"
    module_root.mkdir(parents=True)
    fake_module_file = module_root / "version.py"
    fake_module_file.write_text("# synthetic", encoding="utf-8")

    monkeypatch.setattr(version_module, "__file__", str(fake_module_file))
    monkeypatch.setattr(
        version_module.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(version_module.metadata.PackageNotFoundError()),
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "missing_meipass"), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "backend" / "DevDocsDownloader.Backend.exe"), raising=False)

    with pytest.raises(FileNotFoundError, match="version.json"):
        version_module.app_version()
