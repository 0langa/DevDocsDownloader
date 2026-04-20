"""
analyze_doc_paths.py
--------------------
Fetches every documentation root URL in top_50_programming_languages_with_official_docs.txt,
analyses the internal link structure, and writes doc_path_overrides.json with per-language
allowed_path_prefixes and optionally revised start_urls.

Run:
    python analyze_doc_paths.py

Output:
    doc_path_overrides.json  (consumed by the crawler's planner at runtime)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# ── configuration ────────────────────────────────────────────────────────────

INPUT_FILE = Path("top_50_programming_languages_with_official_docs.txt")
OUTPUT_FILE = Path("doc_path_overrides.json")
TIMEOUT = 20.0
CONCURRENCY = 8
USER_AGENT = "DocPathAnalyzer/1.0 (+local documentation analysis)"

# Tokens that make a URL look like junk regardless of domain
NEGATIVE_PATH_TOKENS = {
    "blog", "news", "press", "release", "download", "download", "community",
    "forum", "discuss", "support", "issues", "github", "twitter", "linkedin",
    "facebook", "careers", "jobs", "pricing", "subscribe", "login", "signup",
    "account", "search", "tag", "category", "wp-content", "cdn", "static",
    "assets", "images", "img", "css", "js", "font", "ajax",
}

# Tokens that strongly suggest a page is documentation
DOC_PATH_TOKENS = {
    "doc", "docs", "documentation", "reference", "manual", "guide", "tutorial",
    "language", "lib", "library", "stdlib", "spec", "book", "learn",
    "getting-started", "quickstart", "api", "help", "kb", "knowledge",
    "chapter", "section", "module", "package", "class", "overview", "intro",
}

def _norm_url(url: str) -> str:
    """Canonical key: strip trailing slash."""
    return url.rstrip("/")


# Overrides keyed by normalised source URL (no trailing slash) so slug collisions
# (C / C++ / C#) are impossible.
STATIC_OVERRIDES: dict[str, dict] = {
    # C / C++ / C# ─────────────────────────────────────────────────────────
    "https://www.iso.org/standard/82075.html": {
        "name": "C",
        "start_urls": ["https://www.iso.org/standard/82075.html"],
        "allowed_path_prefixes": ["/standard/82075"],
        "note": "static override – ISO paywall page",
    },
    "https://www.iso.org/standard/83626.html": {
        "name": "C++",
        "start_urls": ["https://www.iso.org/standard/83626.html"],
        "allowed_path_prefixes": ["/standard/83626"],
        "note": "static override – ISO paywall page",
    },
    "https://learn.microsoft.com/en-us/dotnet/csharp/": {
        "name": "C#",
        "start_urls": ["https://learn.microsoft.com/en-us/dotnet/csharp/"],
        "allowed_path_prefixes": ["/en-us/dotnet/csharp/"],
        "note": "static override",
    },
    # PHP ──────────────────────────────────────────────────────────────────
    "https://www.php.net/docs.php": {
        "name": "PHP",
        "start_urls": ["https://www.php.net/manual/en/"],
        "allowed_path_prefixes": ["/manual/en/"],
        "note": "static override",
    },
    # Ruby ─────────────────────────────────────────────────────────────────
    "https://www.ruby-lang.org/en/documentation/": {
        "name": "Ruby",
        "start_urls": ["https://www.ruby-lang.org/en/documentation/"],
        "allowed_path_prefixes": ["/en/documentation/"],
        "note": "static override",
    },
    # Rust ─────────────────────────────────────────────────────────────────
    "https://doc.rust-lang.org/": {
        "name": "Rust",
        "start_urls": ["https://doc.rust-lang.org/book/", "https://doc.rust-lang.org/std/"],
        "allowed_path_prefixes": ["/book/", "/std/", "/reference/", "/nomicon/", "/rustdoc/"],
        "note": "static override",
    },
    # Lua ──────────────────────────────────────────────────────────────────
    "https://www.lua.org/docs.html": {
        "name": "Lua",
        "start_urls": ["https://www.lua.org/manual/5.4/"],
        "allowed_path_prefixes": ["/manual/"],
        "note": "static override",
    },
    # Objective-C ──────────────────────────────────────────────────────────
    "https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Introduction/Introduction.html": {
        "name": "Objective-C",
        "start_urls": ["https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Introduction/Introduction.html"],
        "allowed_path_prefixes": ["/library/archive/documentation/Cocoa/", "/library/archive/documentation/General/"],
        "note": "static override",
    },
    # Assembly / Intel SDM ─────────────────────────────────────────────────
    "https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html": {
        "name": "Assembly",
        "start_urls": ["https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html"],
        "allowed_path_prefixes": ["/content/www/us/en/developer/articles/technical/"],
        "note": "static override",
    },
    # Microsoft Learn languages — specific paths, not just /en-us/ ─────────
    "https://learn.microsoft.com/en-us/dotnet/visual-basic/": {
        "name": "Visual Basic",
        "start_urls": ["https://learn.microsoft.com/en-us/dotnet/visual-basic/"],
        "allowed_path_prefixes": ["/en-us/dotnet/visual-basic/"],
        "note": "static override",
    },
    "https://learn.microsoft.com/en-us/powershell/": {
        "name": "PowerShell",
        "start_urls": ["https://learn.microsoft.com/en-us/powershell/"],
        "allowed_path_prefixes": ["/en-us/powershell/"],
        "note": "static override",
    },
    "https://learn.microsoft.com/en-us/office/vba/api/overview/": {
        "name": "VBA",
        "start_urls": ["https://learn.microsoft.com/en-us/office/vba/api/overview/"],
        "allowed_path_prefixes": ["/en-us/office/vba/"],
        "note": "static override",
    },
    "https://learn.microsoft.com/en-us/dotnet/fsharp/": {
        "name": "F#",
        "start_urls": ["https://learn.microsoft.com/en-us/dotnet/fsharp/"],
        "allowed_path_prefixes": ["/en-us/dotnet/fsharp/"],
        "note": "static override",
    },
    "https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-ref/xpp-language-reference": {
        "name": "X++",
        "start_urls": ["https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-ref/xpp-language-reference"],
        "allowed_path_prefixes": ["/en-us/dynamics365/fin-ops-core/dev-itpro/dev-ref/"],
        "note": "static override",
    },
    "https://learn.microsoft.com/en-us/sql/t-sql/language-reference": {
        "name": "Transact-SQL",
        "start_urls": ["https://learn.microsoft.com/en-us/sql/t-sql/language-reference"],
        "allowed_path_prefixes": ["/en-us/sql/t-sql/"],
        "note": "static override",
    },
    # ISO paywall pages ────────────────────────────────────────────────────
    "https://www.iso.org/standard/76583.html": {
        "name": "SQL",
        "start_urls": ["https://www.iso.org/standard/76583.html"],
        "allowed_path_prefixes": ["/standard/76583"],
        "note": "static override – ISO paywall page",
    },
    "https://www.iso.org/standard/82170.html": {
        "name": "Fortran",
        "start_urls": ["https://www.iso.org/standard/82170.html"],
        "allowed_path_prefixes": ["/standard/82170"],
        "note": "static override – ISO paywall page",
    },
    "https://www.iso.org/standard/21413.html": {
        "name": "Prolog",
        "start_urls": ["https://www.iso.org/standard/21413.html"],
        "allowed_path_prefixes": ["/standard/21413"],
        "note": "static override – ISO paywall page",
    },
    "https://www.iso.org/standard/74527.html": {
        "name": "COBOL",
        "start_urls": ["https://www.iso.org/standard/74527.html"],
        "allowed_path_prefixes": ["/standard/74527"],
        "note": "static override – ISO paywall page",
    },
    # PL/SQL ───────────────────────────────────────────────────────────────
    "https://docs.oracle.com/en/database/oracle/oracle-database/": {
        "name": "PL/SQL",
        "start_urls": ["https://docs.oracle.com/en/database/oracle/oracle-database/"],
        "allowed_path_prefixes": ["/en/database/oracle/oracle-database/"],
        "note": "static override",
    },
    # ABAP ─────────────────────────────────────────────────────────────────
    "https://help.sap.com/doc/abapdocu_latest_index_htm/latest/en-US/index.htm": {
        "name": "ABAP",
        "start_urls": ["https://help.sap.com/doc/abapdocu_latest_index_htm/latest/en-US/index.htm"],
        "allowed_path_prefixes": ["/doc/abapdocu_latest_index_htm/"],
        "note": "static override",
    },
    # ML / Standard ML Basis ───────────────────────────────────────────────
    "https://smlfamily.github.io/Basis/": {
        "name": "ML",
        "start_urls": ["https://smlfamily.github.io/Basis/"],
        "allowed_path_prefixes": ["/Basis/"],
        "note": "static override",
    },
    # Shell / Bash ─────────────────────────────────────────────────────────
    "https://www.gnu.org/software/bash/manual/": {
        "name": "Shell",
        "start_urls": ["https://www.gnu.org/software/bash/manual/"],
        "allowed_path_prefixes": ["/software/bash/manual/"],
        "note": "static override",
    },
    # Scratch ──────────────────────────────────────────────────────────────
    "https://scratch.mit.edu/help/": {
        "name": "Scratch",
        "start_urls": ["https://scratch.mit.edu/help/"],
        "allowed_path_prefixes": ["/help/"],
        "note": "static override",
    },
    # Lisp / HyperSpec ─────────────────────────────────────────────────────
    "https://www.lispworks.com/documentation/HyperSpec/Front/": {
        "name": "Lisp",
        "start_urls": ["https://www.lispworks.com/documentation/HyperSpec/Front/"],
        "allowed_path_prefixes": ["/documentation/HyperSpec/"],
        "note": "static override",
    },
    # Delphi ───────────────────────────────────────────────────────────────
    "https://docwiki.embarcadero.com/RADStudio/en/Delphi": {
        "name": "Delphi/Object Pascal",
        "start_urls": ["https://docwiki.embarcadero.com/RADStudio/en/Delphi"],
        "allowed_path_prefixes": ["/RADStudio/en/"],
        "note": "static override",
    },
    # Perl ─────────────────────────────────────────────────────────────────
    "https://perldoc.perl.org/": {
        "name": "Perl",
        "start_urls": ["https://perldoc.perl.org/"],
        "allowed_path_prefixes": ["/"],
        "note": "static override – entire perldoc.perl.org is documentation",
    },
    # Kotlin ───────────────────────────────────────────────────────────────
    "https://kotlinlang.org/docs/home.html": {
        "name": "Kotlin",
        "start_urls": ["https://kotlinlang.org/docs/home.html"],
        "allowed_path_prefixes": ["/docs/", "/api/"],
        "note": "static override",
    },
    # Groovy ───────────────────────────────────────────────────────────────
    "https://groovy-lang.org/documentation.html": {
        "name": "Groovy",
        "start_urls": ["https://groovy-lang.org/documentation.html"],
        "allowed_path_prefixes": ["/documentation.html", "/single-page-documentation.html", "/apidocs/", "/style-guide.html"],
        "note": "static override",
    },
    # Elixir ───────────────────────────────────────────────────────────────
    "https://elixir-lang.org/docs.html": {
        "name": "Elixir",
        "start_urls": ["https://elixir-lang.org/docs.html"],
        "allowed_path_prefixes": ["/docs.html", "/learning.html"],
        "note": "static override",
    },
    # SAS ──────────────────────────────────────────────────────────────────
    "https://documentation.sas.com/": {
        "name": "SAS",
        "start_urls": ["https://documentation.sas.com/doc/en/pgmsascdc/"],
        "allowed_path_prefixes": ["/doc/en/"],
        "note": "static override",
    },
    # Haskell ──────────────────────────────────────────────────────────────
    "https://www.haskell.org/documentation/": {
        "name": "Haskell",
        "start_urls": ["https://www.haskell.org/documentation/"],
        "allowed_path_prefixes": ["/documentation", "/tutorial"],
        "note": "static override",
    },
    # GDScript ─────────────────────────────────────────────────────────────
    "https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/": {
        "name": "GDScript",
        "start_urls": ["https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/"],
        "allowed_path_prefixes": ["/en/stable/tutorials/scripting/gdscript/", "/en/stable/getting_started/"],
        "note": "static override – narrowed from full /en/ site",
    },
    # Julia ────────────────────────────────────────────────────────────────
    "https://docs.julialang.org/en/v1/": {
        "name": "Julia",
        "start_urls": ["https://docs.julialang.org/en/v1/"],
        "allowed_path_prefixes": ["/en/v1/"],
        "note": "static override",
    },
    # MicroPython ──────────────────────────────────────────────────────────
    "https://docs.micropython.org/": {
        "name": "MicroPython",
        "start_urls": ["https://docs.micropython.org/en/latest/"],
        "allowed_path_prefixes": ["/en/latest/"],
        "note": "static override",
    },
    # JavaScript (ECMAScript spec) ─────────────────────────────────────────
    "https://tc39.es/ecma262": {
        "name": "JavaScript",
        "start_urls": ["https://tc39.es/ecma262/"],
        "allowed_path_prefixes": ["/ecma262/"],
        "note": "static override – tc39 spec only",
    },
    # R ────────────────────────────────────────────────────────────────────
    "https://cran.r-project.org/manuals.html": {
        "name": "R",
        "start_urls": ["https://cran.r-project.org/manuals.html"],
        "allowed_path_prefixes": ["/doc/"],
        "note": "static override",
    },
}

# Normalize all keys so lookup via _norm_url() always hits regardless of whether
# the raw URL in the input file has a trailing slash or not.
STATIC_OVERRIDES = {_norm_url(k): v for k, v in STATIC_OVERRIDES.items()}

# ── helpers ───────────────────────────────────────────────────────────────────

def parse_input_file(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or " - " not in line:
            continue
        name, url = line.split(" - ", 1)
        entries.append((name.strip(), url.strip()))
    return entries


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_internal_links(html: str, base_url: str) -> list[str]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    base_parsed = urlparse(base_url)
    allowed_hosts = {base_parsed.netloc}
    if base_parsed.netloc.startswith("www."):
        allowed_hosts.add(base_parsed.netloc[4:])

    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc not in allowed_hosts:
            continue
        links.append(parsed.path)
    return links


def score_path(path: str) -> float:
    low = path.lower()
    parts = set(p for p in low.split("/") if p)
    neg = sum(1 for t in NEGATIVE_PATH_TOKENS if t in parts or t in low)
    pos = sum(1 for t in DOC_PATH_TOKENS if t in parts or t in low)
    return pos - neg * 2


def derive_path_prefixes(doc_paths: list[str], source_path: str) -> list[str]:
    """
    Given a list of documentation-scored paths and the root URL's own path,
    return a short list of path prefixes that cover the doc tree.
    Strategy:
      1. Start with the source_path itself as a baseline.
      2. Find the depth-1 or depth-2 common prefix shared by the highest-scoring links.
      3. Merge overlapping prefixes and drop redundant ones.
    """
    if not doc_paths:
        return [source_path] if source_path != "/" else []

    # Use source_path stripped to the directory as baseline
    baseline = source_path if source_path.endswith("/") else source_path.rsplit("/", 1)[0] + "/"

    # Score each candidate prefix at depth 1-3 relative to root
    counter: Counter[str] = Counter()
    for path in doc_paths:
        parts = [p for p in path.split("/") if p]
        for depth in (1, 2, 3):
            prefix = "/" + "/".join(parts[:depth]) + ("/" if len(parts) > depth else "")
            if score_path(prefix) >= 0:
                counter[prefix] += 1

    if not counter:
        return [baseline]

    # Keep prefixes accounting for top 80% of doc links
    total = len(doc_paths)
    threshold = max(3, int(total * 0.05))  # prefix must cover ≥5% of all links
    candidates = [p for p, count in counter.most_common(20) if count >= threshold]

    if not candidates:
        candidates = [counter.most_common(1)[0][0]]

    # Drop any candidate that is a strict sub-path of another candidate
    def is_subpath(child: str, parent: str) -> bool:
        return child != parent and child.startswith(parent)

    filtered = [c for c in candidates if not any(is_subpath(c, other) for other in candidates)]
    filtered = sorted(set(filtered))

    # Always include baseline if it's not already covered
    if baseline and not any(baseline.startswith(p) or p.startswith(baseline) for p in filtered):
        filtered.insert(0, baseline)

    return filtered or [baseline]


async def analyze_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    name: str,
    url: str,
) -> tuple[str, dict]:
    # Key is the normalised source URL — unique even when slugs collide (C / C++ / C#)
    url_key = _norm_url(url)

    # Return static override immediately if we have one
    if url_key in STATIC_OVERRIDES:
        result = {
            "name": name,
            "source_url": url,
            **STATIC_OVERRIDES[url_key],
        }
        print(f"  [{name}] static override — prefixes: {result['allowed_path_prefixes']}")
        return url_key, result

    async with semaphore:
        try:
            response = await client.get(url, follow_redirects=True)
            final_url = str(response.url)
            final_parsed = urlparse(final_url)
            html = response.text
        except Exception as exc:
            print(f"  [{name}] FETCH ERROR: {exc}", file=sys.stderr)
            return url_key, {
                "name": name,
                "source_url": url,
                "start_urls": [url],
                "allowed_path_prefixes": [],
                "note": f"fetch error: {exc}",
            }

    raw_paths = extract_internal_links(html, final_url)
    doc_paths = [p for p in raw_paths if score_path(p) > 0]

    prefixes = derive_path_prefixes(doc_paths, final_parsed.path)
    start_url = final_url if final_url != url else url

    print(f"  [{name}] {len(raw_paths)} links, {len(doc_paths)} doc-scored → prefixes: {prefixes}")

    return url_key, {
        "name": name,
        "source_url": url,
        "start_urls": [start_url],
        "allowed_path_prefixes": prefixes,
        "note": "auto-detected",
    }


async def main() -> None:
    entries = parse_input_file(INPUT_FILE)
    if not entries:
        print("No entries found in input file.", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {len(entries)} documentation roots …\n")

    semaphore = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT, connect=10.0),
        headers={"User-Agent": USER_AGENT},
        limits=limits,
    ) as client:
        tasks = [analyze_one(client, semaphore, name, url) for name, url in entries]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    overrides: dict[str, dict] = {}
    for key, data in results:
        overrides[key] = data

    OUTPUT_FILE.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(overrides)} entries to {OUTPUT_FILE}")

    # Print a summary of what was found
    print("\n── Summary ─────────────────────────────────────────────────────────")
    for _key, data in sorted(overrides.items(), key=lambda kv: kv[1].get("name", kv[0]).lower()):
        prefixes = data.get("allowed_path_prefixes", [])
        note = data.get("note", "")
        display_name = data.get("name", _key)
        prefix_str = ", ".join(prefixes) if prefixes else "(none — full domain)"
        print(f"  {display_name:<30} {prefix_str}  [{note}]")


if __name__ == "__main__":
    asyncio.run(main())
