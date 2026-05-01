from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n+", re.DOTALL)
HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
IDENT_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+|[a-z]+_[a-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*\(\))\b")


@dataclass(frozen=True)
class SearchHit:
    language: str
    slug: str
    title: str
    topic: str
    path: str
    snippet: str
    score: float


def _strip_frontmatter(content: str) -> str:
    return FRONTMATTER_RE.sub("", content, count=1)


def _search_root(output_dir: Path) -> Path:
    root = output_dir / "_search"
    root.mkdir(parents=True, exist_ok=True)
    return root


def index_db_path(output_dir: Path) -> Path:
    return _search_root(output_dir) / "index.db"


def favorites_path(output_dir: Path) -> Path:
    return _search_root(output_dir) / "favorites.json"


def recents_path(output_dir: Path) -> Path:
    return _search_root(output_dir) / "recents.json"


def ensure_index_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                language TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title,
                topic,
                body,
                content='documents',
                content_rowid='id'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, title, topic, body)
                VALUES (new.id, new.title, new.topic, new.body);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, topic, body)
                VALUES('delete', old.id, old.title, old.topic, old.body);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, topic, body)
                VALUES('delete', old.id, old.title, old.topic, old.body);
                INSERT INTO documents_fts(rowid, title, topic, body)
                VALUES (new.id, new.title, new.topic, new.body);
            END
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS xrefs (
                term TEXT NOT NULL,
                language TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_xrefs_term ON xrefs(term)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_xrefs_language ON xrefs(language)")
        conn.commit()


def rebuild_language_index(*, output_dir: Path, language_slug: str) -> None:
    language_dir = output_dir / "markdown" / language_slug
    if not language_dir.exists():
        return
    db_path = index_db_path(output_dir)
    ensure_index_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM documents WHERE slug = ?", (language_slug,))
        conn.execute("DELETE FROM xrefs WHERE slug = ?", (language_slug,))
        docs_root = language_dir / "docs"
        if not docs_root.exists():
            conn.commit()
            return
        rows: list[tuple[str, str, str, str, str, str]] = []
        xrefs_rows: list[tuple[str, str, str, str, str]] = []
        for path in sorted(docs_root.rglob("*.md")):
            rel = path.relative_to(language_dir).as_posix()
            if "/chunks/" in rel or rel.endswith("/consolidated.md"):
                continue
            text = _strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
            title_match = HEADING_RE.search(text)
            title = title_match.group(1).strip() if title_match else path.stem.replace("-", " ")
            topic = path.parent.name if path.parent != docs_root else ""
            rows.append((language_slug, language_slug, title, topic, rel, text))
            for token in set(IDENT_RE.findall(text)):
                if len(token) < 3:
                    continue
                xrefs_rows.append((token, language_slug, language_slug, title, rel))
        conn.executemany(
            "INSERT OR REPLACE INTO documents(language, slug, title, topic, path, body) VALUES(?, ?, ?, ?, ?, ?)",
            rows,
        )
        if xrefs_rows:
            conn.executemany("INSERT INTO xrefs(term, language, slug, title, path) VALUES(?, ?, ?, ?, ?)", xrefs_rows)
        conn.commit()


def search(
    *,
    output_dir: Path,
    query: str,
    limit: int = 25,
    language: str | None = None,
) -> list[SearchHit]:
    db_path = index_db_path(output_dir)
    if not db_path.exists() or not query.strip():
        return []
    sql = """
        SELECT d.language, d.slug, d.title, d.topic, d.path,
               snippet(documents_fts, 2, '[', ']', ' … ', 16) AS snippet,
               bm25(documents_fts) AS score
        FROM documents_fts
        JOIN documents d ON d.id = documents_fts.rowid
        WHERE documents_fts MATCH ?
    """
    params: list[Any] = [query.strip()]
    if language:
        sql += " AND d.language = ?"
        params.append(language.strip())
    sql += " ORDER BY score LIMIT ?"
    params.append(max(1, min(limit, 100)))
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        SearchHit(
            language=str(row[0]),
            slug=str(row[1]),
            title=str(row[2]),
            topic=str(row[3]),
            path=str(row[4]),
            snippet=str(row[5] or ""),
            score=float(row[6] or 0.0),
        )
        for row in rows
    ]


def xref_lookup(*, output_dir: Path, term: str, limit: int = 100) -> dict[str, list[dict[str, str]]]:
    db_path = index_db_path(output_dir)
    if not db_path.exists() or not term.strip():
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT language, slug, title, path
            FROM xrefs
            WHERE term = ?
            ORDER BY language, title
            LIMIT ?
            """,
            (term.strip(), max(1, min(limit, 500))),
        ).fetchall()
    out: dict[str, list[dict[str, str]]] = {}
    for language, slug, title, path in rows:
        out.setdefault(str(language), []).append(
            {"slug": str(slug), "title": str(title), "path": str(path), "term": term.strip()}
        )
    return out


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def write_json_list(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
