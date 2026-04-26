from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
VENV_DIR = REPO_ROOT / ".venv"
DEFAULT_EXTRA = "dev"
KNOWN_EXTRAS = {"dev", "analysis", "conversion-extended", "browser", "benchmark", "gui"}


def run_command(command: list[str], cwd: Path | None = None) -> None:
    print(f"[setup] Running: {' '.join(command)}")
    subprocess.run(command, cwd=cwd or REPO_ROOT, check=True)


def get_venv_python() -> Path:
    if platform.system().lower() == "windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_directories() -> None:
    for relative in [
        "output/markdown",
        "output/reports",
        "cache",
        "logs",
        "state/checkpoints",
        "tmp",
    ]:
        path = REPO_ROOT / relative
        path.mkdir(parents=True, exist_ok=True)
        print(f"[setup] Ensured directory: {path}")


def ensure_venv() -> Path:
    python_path = get_venv_python()
    if python_path.exists():
        print(f"[setup] Virtual environment already exists: {VENV_DIR}")
        return python_path

    run_command([sys.executable, "-m", "venv", str(VENV_DIR)])
    return python_path


def parse_extras(value: str) -> list[str]:
    extras = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(extras) - KNOWN_EXTRAS)
    if unknown:
        joined = ", ".join(unknown)
        allowed = ", ".join(sorted(KNOWN_EXTRAS))
        raise SystemExit(f"Unknown extra(s): {joined}. Allowed extras: {allowed}")
    if DEFAULT_EXTRA not in extras:
        extras.insert(0, DEFAULT_EXTRA)
    return extras


def install_project(python_path: Path, extras: list[str]) -> None:
    run_command([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    extras_suffix = f"[{','.join(extras)}]" if extras else ""
    run_command([str(python_path), "-m", "pip", "install", "-e", f".{extras_suffix}"])


def install_playwright_browser(python_path: Path) -> None:
    run_command([str(python_path), "-m", "playwright", "install", "chromium"])


def print_next_steps(python_path: Path, extras: list[str], *, playwright_browser: bool) -> None:
    print("[setup] Setup complete.")
    print(f"[setup] Interpreter: {python_path}")
    print(f"[setup] Installed extras: {', '.join(extras)}")
    if "browser" in extras and not playwright_browser:
        print("[setup] Browser extra installed; Chromium was not installed. Use --with-playwright-browser if needed.")
    print("[setup] Common commands:")
    print(f"  {python_path} DevDocsDownloader.py --help")
    print(f"  {python_path} DevDocsDownloader.py run python")
    if "gui" in extras:
        print(f"  {python_path} DevDocsDownloader.py gui")
    print(f"  {python_path} DevDocsDownloader.py validate python")
    print(f"  {python_path} DevDocsDownloader.py audit-presets")
    print(f"  {python_path} -m pytest -q")
    print(f"  {python_path} -m ruff check .")
    print(f"  {python_path} -m ruff format --check .")
    print(f"  {python_path} -m mypy doc_ingest")
    print("  PowerShell live probe: $env:DEVDOCS_LIVE_TESTS='1'; python -m pytest -m live -q")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a DevDocsDownloader development environment.")
    parser.add_argument(
        "--extras",
        default=DEFAULT_EXTRA,
        help="Comma-separated optional extras to install. Default: dev.",
    )
    parser.add_argument(
        "--with-playwright-browser",
        action="store_true",
        help="Install Playwright Chromium after installing the project.",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    extras = parse_extras(args.extras)
    if args.with_playwright_browser and "browser" not in extras:
        extras.append("browser")

    ensure_directories()
    python_path = ensure_venv()
    install_project(python_path, extras)
    if args.with_playwright_browser:
        install_playwright_browser(python_path)
    print_next_steps(python_path, extras, playwright_browser=args.with_playwright_browser)


if __name__ == "__main__":
    main()
