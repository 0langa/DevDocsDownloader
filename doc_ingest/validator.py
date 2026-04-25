from __future__ import annotations

import re
from pathlib import Path

from .models import TopicStats, ValidationIssue, ValidationResult

_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)]*)\)")
_HTML_LEFTOVER_RE = re.compile(r"</?(?:div|span|section|article|nav|aside|table|tr|td|th|p|ul|ol|li)\b", re.I)
_SAFE_LINK_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "dash://", "#")


def validate_output(
    *,
    language: str,
    output_path: Path,
    total_documents: int,
    topics: list[TopicStats],
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not output_path.exists():
        issues.append(
            ValidationIssue(level="error", code="missing_output", message="Consolidated markdown file is missing.")
        )
        return ValidationResult(language=language, output_path=output_path, score=0.0, issues=issues)

    text = output_path.read_text(encoding="utf-8")
    size = len(text)

    if total_documents == 0:
        issues.append(ValidationIssue(level="error", code="no_documents", message="No documents were ingested."))

    if size < 2000:
        issues.append(
            ValidationIssue(
                level="error", code="tiny_output", message=f"Consolidated output is very small ({size} bytes)."
            )
        )

    if text.count("```") % 2 != 0:
        issues.append(ValidationIssue(level="warning", code="code_fence", message="Unbalanced code fences detected."))

    for section in ("## Metadata", "## Table of Contents", "## Documentation"):
        if section not in text:
            issues.append(
                ValidationIssue(level="warning", code="missing_section", message=f"Missing section {section!r}.")
            )

    if not topics:
        issues.append(ValidationIssue(level="warning", code="no_topics", message="No topics were produced."))

    issues.extend(_validate_links(text))
    issues.extend(_validate_conversion_quality(text))

    score = 1.0
    for issue in issues:
        score -= 0.3 if issue.level == "error" else 0.1
    score = max(0.0, min(1.0, score))

    return ValidationResult(
        language=language,
        output_path=output_path,
        score=round(score, 2),
        quality_score=round(score, 2),
        issues=issues,
    )


def _validate_links(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    relative_links = 0
    relative_images = 0
    empty_targets = 0
    for marker, _label, target in _iter_links_outside_code(text):
        stripped = target.strip()
        if not stripped:
            empty_targets += 1
            continue
        if stripped.startswith(_SAFE_LINK_PREFIXES) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", stripped):
            continue
        if marker:
            relative_images += 1
        else:
            relative_links += 1

    if relative_links:
        issues.append(
            ValidationIssue(
                level="warning",
                code="relative_link",
                message=f"{relative_links} unresolved relative Markdown link(s) detected.",
            )
        )
    if relative_images:
        issues.append(
            ValidationIssue(
                level="warning",
                code="relative_image",
                message=f"{relative_images} unresolved relative Markdown image target(s) detected.",
            )
        )
    if empty_targets:
        issues.append(
            ValidationIssue(
                level="warning",
                code="empty_link_target",
                message=f"{empty_targets} empty Markdown link target(s) detected.",
            )
        )
    return issues


def _validate_conversion_quality(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    without_code = "\n".join(_iter_non_code_lines(text))
    if _HTML_LEFTOVER_RE.search(without_code):
        issues.append(
            ValidationIssue(
                level="warning",
                code="html_leftover",
                message="Likely HTML tag leftovers detected in generated Markdown.",
            )
        )
    if _has_malformed_table(without_code):
        issues.append(
            ValidationIssue(
                level="warning",
                code="malformed_table",
                message="A Markdown table appears to have inconsistent column counts.",
            )
        )
    if re.search(r"(?m)^\s*:\s+\S", without_code):
        issues.append(
            ValidationIssue(
                level="warning",
                code="definition_list_artifact",
                message="Possible definition-list conversion artifact detected.",
            )
        )
    return issues


def _iter_links_outside_code(text: str):
    for line in _iter_non_code_lines(text):
        segments = line.split("`")
        for index in range(0, len(segments), 2):
            for match in _MARKDOWN_LINK_RE.finditer(segments[index]):
                yield match.groups()


def _iter_non_code_lines(text: str):
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def _has_malformed_table(text: str) -> bool:
    rows: list[str] = []
    for line in text.splitlines() + [""]:
        if "|" in line and not line.lstrip().startswith(">"):
            rows.append(line)
            continue
        if len(rows) >= 2 and _table_rows_inconsistent(rows):
            return True
        rows = []
    return False


def _table_rows_inconsistent(rows: list[str]) -> bool:
    counts = [row.count("|") for row in rows if row.strip()]
    if len(set(counts)) <= 1:
        return False
    return any("---" in row for row in rows)
