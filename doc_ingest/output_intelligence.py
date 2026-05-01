from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ValidationResult
from .utils.filesystem import read_json, write_json, write_text


def write_validation_json(language_dir: Path, validation: ValidationResult | None) -> Path | None:
    if validation is None:
        return None
    payload = validation.model_dump(mode="json")
    path = language_dir / "validation.json"
    write_json(path, payload)
    return path


def apply_output_template(language_dir: Path, *, template_name: str, language: str, source: str, run_date: str) -> None:
    if template_name == "default":
        return
    docs = _collect_documents(language_dir)
    context_docs = []
    for path in docs:
        text = path.read_text(encoding="utf-8")
        context_docs.append(
            {
                "title": _first_heading(text) or path.stem,
                "slug": path.stem,
                "markdown": text,
                "topic": path.parent.name,
                "source_url": "",
            }
        )
    template = _resolve_template(language_dir, template_name)
    if template is None:
        return
    rendered = _render_template(
        template,
        {
            "language": language,
            "source": source,
            "documents": context_docs,
            "run_date": run_date,
            "mode": "full",
        },
    )
    write_text(language_dir / f"{language_dir.name}.md", rendered.rstrip() + "\n")


def write_language_manifest(
    *,
    language_dir: Path,
    language: str,
    source: str,
    source_slug: str,
    mode: str,
    keep_history: int = 10,
) -> dict[str, Any]:
    docs = _collect_documents(language_dir)
    doc_rows: list[dict[str, Any]] = []
    aggregate_input: list[str] = []
    total_chars = 0
    for path in docs:
        text = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rel = path.relative_to(language_dir).as_posix()
        title = _first_heading(text) or path.stem
        doc_rows.append({"slug": path.stem, "title": title, "path": rel, "sha256": digest})
        aggregate_input.append(f"{rel}:{digest}")
        total_chars += len(text)
    aggregate = hashlib.sha256("\n".join(sorted(aggregate_input)).encode("utf-8")).hexdigest()
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "language": language,
        "source": source,
        "source_slug": source_slug,
        "mode": mode,
        "run_date": now,
        "document_count": len(doc_rows),
        "total_chars": total_chars,
        "content_sha256": aggregate,
        "documents": doc_rows,
    }
    manifest_path = language_dir / "manifest.json"
    _archive_previous_manifest(manifest_path, keep=keep_history)
    write_json(manifest_path, manifest)
    return manifest


def compare_manifests(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {"added": [], "removed": [], "changed": [], "summary": {"added": 0, "removed": 0, "changed": 0}}
    cur = {str(d.get("path") or d.get("slug") or ""): str(d.get("sha256") or "") for d in current.get("documents", [])}
    prv = {str(d.get("path") or d.get("slug") or ""): str(d.get("sha256") or "") for d in previous.get("documents", [])}
    added = sorted(path for path in cur if path not in prv)
    removed = sorted(path for path in prv if path not in cur)
    changed = sorted(path for path in cur if path in prv and cur[path] != prv[path])
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def generate_html_site(language_dir: Path, *, language_slug: str, language_name: str) -> Path:
    site_root = language_dir / "_site" / language_slug
    assets_dir = site_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    docs = _collect_documents(language_dir)
    links: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        title = _first_heading(text) or doc.stem
        html = _markdown_to_html(text)
        page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><link rel="stylesheet" href="assets/site.css"></head><body><main>{html}</main></body></html>"""
        out = site_root / f"{doc.stem}.html"
        write_text(out, page)
        links.append(f'<li><a href="{doc.stem}.html">{title}</a></li>')
    index = f"""<!doctype html><html><head><meta charset="utf-8"><title>{language_name}</title><link rel="stylesheet" href="assets/site.css"></head><body><h1>{language_name}</h1><ul>{"".join(links)}</ul></body></html>"""
    write_text(site_root / "index.html", index)
    write_text(
        assets_dir / "site.css",
        "body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;} pre{overflow:auto;background:#111;color:#eee;padding:0.75rem;} a{color:#0b62d6;}",
    )
    write_json(
        site_root / "search-index.json", {"documents": [{"slug": doc.stem, "path": f"{doc.stem}.html"} for doc in docs]}
    )
    return site_root


def generate_epub(language_dir: Path, *, language_slug: str, language_name: str) -> Path:
    epub_path = language_dir / f"{language_slug}.epub"
    docs = _collect_documents(language_dir)
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        items: list[str] = []
        spine: list[str] = []
        toc: list[str] = []
        for idx, doc in enumerate(docs, start=1):
            text = doc.read_text(encoding="utf-8")
            title = _first_heading(text) or doc.stem
            xhtml_name = f"doc{idx}.xhtml"
            xhtml = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head><body>{_markdown_to_html(text)}</body></html>'
            zf.writestr(f"OEBPS/{xhtml_name}", xhtml)
            items.append(f'<item id="i{idx}" href="{xhtml_name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="i{idx}"/>')
            toc.append(f'<li><a href="{xhtml_name}">{title}</a></li>')
        nav = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>toc</title></head><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>{"".join(toc)}</ol></nav></body></html>'
        zf.writestr("OEBPS/nav.xhtml", nav)
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        opf = f'<?xml version="1.0" encoding="utf-8"?><package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{language_slug}</dc:identifier><dc:title>{language_name}</dc:title><dc:language>en</dc:language></metadata><manifest>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>'
        zf.writestr("OEBPS/content.opf", opf)
    return epub_path


def _archive_previous_manifest(manifest_path: Path, *, keep: int) -> None:
    if not manifest_path.exists():
        return
    history = manifest_path.parent / ".history"
    history.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(history / f"{timestamp}.json", read_json(manifest_path, {}))
    files = sorted(history.glob("*.json"))
    for stale in files[: -max(1, keep)]:
        stale.unlink(missing_ok=True)


def _collect_documents(language_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in language_dir.rglob("*.md")
        if path.name not in {"_section.md", f"{language_dir.name}.md"}
        and "chunks" not in path.parts
        and path.parent.name != "_site"
    )


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _markdown_to_html(markdown_text: str) -> str:
    try:
        import markdown  # type: ignore[import-not-found, import-untyped]

        return markdown.markdown(markdown_text, extensions=["fenced_code", "tables"])
    except Exception:
        escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        return f"<pre>{escaped}</pre>"


def _resolve_template(language_dir: Path, template_name: str) -> str | None:
    custom_dir = language_dir.parent.parent / "templates"
    custom = custom_dir / f"{template_name}.md.j2"
    if custom.exists():
        return custom.read_text(encoding="utf-8")
    templates = {
        "detailed": (
            "---\nlanguage: {{ language }}\nsource: {{ source }}\nrun_date: {{ run_date }}\n---\n\n"
            "{% for document in documents %}{{ document.markdown }}\n\n{% endfor %}"
        ),
        "minimal": "{% for document in documents %}{{ document.markdown }}\n\n{% endfor %}",
        "api-reference": (
            "# {{ language }} API Reference\n\n"
            "{% for document in documents|sort(attribute='title') %}## {{ document.title }}\n\n{{ document.markdown }}\n\n{% endfor %}"
        ),
    }
    return templates.get(template_name)


def _render_template(template_text: str, context: dict[str, Any]) -> str:
    try:
        from jinja2 import Template  # type: ignore[import-not-found, import-untyped]

        return Template(template_text).render(**context)
    except Exception:
        return "\n\n".join(str(item["markdown"]) for item in context.get("documents", []))
