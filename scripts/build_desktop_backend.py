from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
BACKEND_NAME = "DevDocsDownloader.Backend"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the frozen desktop backend with PyInstaller.")
    parser.add_argument("--clean", action="store_true", help="Remove previous build artifacts first.")
    args = parser.parse_args()

    if args.clean:
        shutil.rmtree(DIST, ignore_errors=True)
        shutil.rmtree(BUILD, ignore_errors=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        BACKEND_NAME,
        "--console",
        "--collect-data",
        "doc_ingest.sources",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ROOT / "scripts" / "run_desktop_backend.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    print(f"[backend] Built {DIST / BACKEND_NAME}")


if __name__ == "__main__":
    main()
