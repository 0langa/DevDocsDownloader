from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bad_paths: list[Path] = []
    for path in root.rglob("*"):
        if any(part in {"output", "cache", "logs", "state", "tmp", ".git", ".venv"} for part in path.parts):
            continue
        if path.name == "__pycache__" and path.is_dir():
            bad_paths.append(path)
        elif path.suffix == ".pyc":
            bad_paths.append(path)
    if not bad_paths:
        print("release hygiene ok")
        return 0
    print("release hygiene failed; unexpected local bytecode artifacts found:")
    for path in bad_paths:
        print(path.relative_to(root).as_posix())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
