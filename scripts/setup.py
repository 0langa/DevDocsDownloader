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
DEFAULT_PROFILE = "full"
KNOWN_EXTRAS = {"dev", "analysis", "browser", "benchmark", "tokenizer"}
PROFILE_EXTRAS = {
    "minimal": [],
    "full": ["browser", "benchmark", "tokenizer"],
    "dev": ["browser", "benchmark", "tokenizer", "dev"],
}


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
    return extras


def extras_for_profile(profile: str) -> list[str]:
    try:
        return list(PROFILE_EXTRAS[profile])
    except KeyError as exc:
        allowed = ", ".join(sorted(PROFILE_EXTRAS))
        raise SystemExit(f"Unknown profile '{profile}'. Allowed profiles: {allowed}") from exc


def merge_extras(*groups: list[str]) -> list[str]:
    ordered: list[str] = []
    for group in groups:
        for extra in group:
            if extra not in ordered:
                ordered.append(extra)
    return ordered


def install_project(python_path: Path, extras: list[str]) -> None:
    run_command([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    extras_suffix = f"[{','.join(extras)}]" if extras else ""
    run_command([str(python_path), "-m", "pip", "install", "-e", f".{extras_suffix}"])


def install_playwright_browser(python_path: Path) -> None:
    run_command([str(python_path), "-m", "playwright", "install", "chromium"])


def print_next_steps(python_path: Path, extras: list[str], *, profile: str, playwright_browser: bool) -> None:
    print("[setup] Setup complete.")
    print(f"[setup] Interpreter: {python_path}")
    print(f"[setup] Setup profile: {profile}")
    print(f"[setup] Installed extras: {', '.join(extras)}")
    if "browser" in extras and not playwright_browser:
        print("[setup] Browser extra installed; Chromium was not installed. Browser fallback will remain unavailable.")
    print("[setup] Common commands:")
    print(f"  {python_path} DevDocsDownloader.py --help")
    print(f"  {python_path} DevDocsDownloader.py run python")
    print(f"  {python_path} DevDocsDownloader.py validate python")
    print(f"  {python_path} DevDocsDownloader.py audit-presets")
    print(f"  {python_path} -m pytest -q")
    print(f"  {python_path} -m ruff check .")
    print(f"  {python_path} -m ruff format --check .")
    print(f"  {python_path} -m mypy doc_ingest")
    print("  PowerShell live probe: $env:DEVDOCS_LIVE_TESTS='1'; python -m pytest -m live -q")
    print(
        "  PowerShell extraction probe: "
        "$env:DEVDOCS_LIVE_EXTRACTION_TESTS='1'; python -m pytest -m live tests\\test_live_extraction_sanity.py -q"
    )
    print("[setup] Full runtime note:")
    print("  Browser fallback requires the browser extra plus Playwright Chromium.")
    print("  Token-based chunking requires the tokenizer extra.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap DevDocsDownloader into a ready-to-run local environment. By default this installs the full "
            "runtime capability set: Playwright browser package, Chromium browser runtime, tokenizer chunking, "
            "and adaptive benchmark support."
        )
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=sorted(PROFILE_EXTRAS),
        help="Setup profile. 'full' installs all runtime capabilities, 'dev' adds developer tools, 'minimal' keeps only base runtime.",
    )
    parser.add_argument(
        "--extras",
        default="",
        help="Comma-separated extras to add on top of the selected profile.",
    )
    parser.add_argument(
        "--with-playwright-browser",
        action="store_true",
        help="Legacy alias. Forces Playwright Chromium installation after installing the project.",
    )
    parser.add_argument(
        "--skip-playwright-browser",
        action="store_true",
        help="Skip Playwright Chromium installation even when the selected profile includes browser support.",
    )
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    profile_extras = extras_for_profile(args.profile)
    explicit_extras = parse_extras(args.extras) if args.extras else []
    extras = merge_extras(profile_extras, explicit_extras)
    playwright_browser = ("browser" in extras and not args.skip_playwright_browser) or args.with_playwright_browser
    if args.with_playwright_browser and "browser" not in extras:
        extras.append("browser")

    ensure_directories()
    python_path = ensure_venv()
    install_project(python_path, extras)
    if playwright_browser:
        install_playwright_browser(python_path)
    print_next_steps(python_path, extras, profile=args.profile, playwright_browser=playwright_browser)


if __name__ == "__main__":
    main()
