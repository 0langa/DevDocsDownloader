from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_setup_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "setup.py"
    spec = importlib.util.spec_from_file_location("devdocs_setup_script", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_profile_defaults_cover_full_runtime() -> None:
    setup_script = _load_setup_module()

    assert setup_script.DEFAULT_PROFILE == "full"
    assert setup_script.extras_for_profile("full") == ["gui", "browser", "benchmark", "tokenizer"]
    assert setup_script.extras_for_profile("dev") == ["gui", "browser", "benchmark", "tokenizer", "dev"]


def test_setup_merge_extras_preserves_order_and_deduplicates() -> None:
    setup_script = _load_setup_module()

    merged = setup_script.merge_extras(["gui", "browser"], ["browser", "tokenizer"], ["dev"])

    assert merged == ["gui", "browser", "tokenizer", "dev"]


def test_setup_main_installs_full_profile_and_browser_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_script = _load_setup_module()
    calls: list[tuple[str, list[str] | tuple[str, ...]]] = []

    monkeypatch.setattr(setup_script, "ensure_directories", lambda: calls.append(("dirs", [])))
    monkeypatch.setattr(setup_script, "ensure_venv", lambda: Path("/tmp/python"))
    monkeypatch.setattr(
        setup_script,
        "install_project",
        lambda python_path, extras: calls.append(("install", list(extras))),
    )
    monkeypatch.setattr(
        setup_script,
        "install_playwright_browser",
        lambda python_path: calls.append(("browser", [str(python_path)])),
    )
    monkeypatch.setattr(
        setup_script,
        "print_next_steps",
        lambda python_path, extras, *, profile, playwright_browser: calls.append(
            ("summary", [str(python_path), profile, ",".join(extras), str(playwright_browser)])
        ),
    )

    setup_script.main([])

    assert ("dirs", []) in calls
    assert ("install", ["gui", "browser", "benchmark", "tokenizer"]) in calls
    assert any(name == "browser" and payload[0].endswith("python") for name, payload in calls)
    assert any(
        name == "summary"
        and payload[0].endswith("python")
        and payload[1:] == ["full", "gui,browser,benchmark,tokenizer", "True"]
        for name, payload in calls
    )


def test_setup_skip_playwright_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_script = _load_setup_module()
    calls: list[str] = []

    monkeypatch.setattr(setup_script, "ensure_directories", lambda: None)
    monkeypatch.setattr(setup_script, "ensure_venv", lambda: Path("/tmp/python"))
    monkeypatch.setattr(setup_script, "install_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup_script, "install_playwright_browser", lambda *_args, **_kwargs: calls.append("browser"))
    monkeypatch.setattr(setup_script, "print_next_steps", lambda *_args, **_kwargs: None)

    setup_script.main(["--skip-playwright-browser"])

    assert calls == []
