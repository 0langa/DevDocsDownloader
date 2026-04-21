from __future__ import annotations

from pathlib import Path
import re

from .models import LanguageEntry
from .utils.text import slugify


def parse_language_file(path: Path) -> list[LanguageEntry]:
    entries: list[LanguageEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[-*+]\s+", "", line)
        if not line or " - " not in line:
            continue
        name, url = line.split(" - ", 1)
        entries.append(LanguageEntry(name=name.strip(), source_url=url.strip(), slug=slugify(name.strip())))
    return entries