from __future__ import annotations

from pathlib import Path

from .models import LanguageEntry
from .utils.text import slugify


def parse_language_file(path: Path) -> list[LanguageEntry]:
    entries: list[LanguageEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        body = line[1:].strip()
        if " - " not in body:
            continue
        name, url = body.split(" - ", 1)
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            continue
        entries.append(LanguageEntry(name=name.strip(), source_url=url, slug=slugify(name.strip())))
    return entries