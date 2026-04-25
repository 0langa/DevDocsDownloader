from __future__ import annotations

import tarfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath


def safe_extract_tar(
    archive: tarfile.TarFile,
    dest: Path,
    *,
    member_filter: Callable[[tarfile.TarInfo], bool] | None = None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()

    for member in archive:
        if member_filter is not None and not member_filter(member):
            continue
        _validate_member(member, dest_root)
        archive.extract(member, dest)


def _validate_member(member: tarfile.TarInfo, dest_root: Path) -> None:
    name = member.name
    posix_path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)

    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise RuntimeError(f"Unsafe tar member path: {name}")
    if any(part == ".." for part in posix_path.parts):
        raise RuntimeError(f"Unsafe tar member path: {name}")
    if member.issym() or member.islnk():
        raise RuntimeError(f"Unsafe tar link member: {name}")

    target = (dest_root / Path(*posix_path.parts)).resolve()
    if target != dest_root and dest_root not in target.parents:
        raise RuntimeError(f"Unsafe tar member path: {name}")
