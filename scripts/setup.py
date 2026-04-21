from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
VENV_DIR = REPO_ROOT / ".venv"


def run_command(command: list[str], cwd: Path | None = None) -> None:
    print(f"[setup] Running: {' '.join(command)}")
    subprocess.run(command, cwd=cwd or REPO_ROOT, check=True)


def get_venv_python() -> Path:
    if platform.system().lower() == "windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_directories() -> None:
    for relative in [
        "output",
        "output/markdown",
        "output/reports",
        "output/diagnostics",
        "cache",
        "cache/discovered_links",
        "logs",
        "state",
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


def install_requirements(python_path: Path) -> None:
    run_command([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run_command([str(python_path), "-m", "pip", "install", "-r", str(REPO_ROOT / "source-documents" / "requirements.txt")])


def install_playwright_browser(python_path: Path) -> None:
    run_command([str(python_path), "-m", "playwright", "install", "chromium"])


def main() -> None:
    os.chdir(REPO_ROOT)
    ensure_directories()
    python_path = ensure_venv()
    install_requirements(python_path)
    install_playwright_browser(python_path)
    print("[setup] Setup complete.")
    print(f"[setup] Use interpreter: {python_path}")
    print(f"[setup] Example run: {python_path} DevDocsDownloader.py run --mode important")
    print("[setup] Fresh clone ready: requirements installed, directories created, Playwright Chromium installed.")


if __name__ == "__main__":
    main()