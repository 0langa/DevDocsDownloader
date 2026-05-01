from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from .models import (
    DocumentValidationResult,
    SourceRunDiagnostics,
    TopicStats,
    ValidationIssue,
    ValidationResult,
    ValidationScoreComponents,
)

_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)]*)\)")
_HTML_LEFTOVER_RE = re.compile(r"</?(?:div|span|section|article|nav|aside|table|tr|td|th|p|ul|ol|li)\b", re.I)
_SAFE_LINK_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "dash://", "#")
_ANCHOR_RE = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_COMPONENT_WEIGHTS = {
    "completeness": 0.35,
    "structure": 0.25,
    "conversion": 0.15,
    "consistency": 0.15,
    "document_quality": 0.10,
}
_ISSUE_BASE_WEIGHTS = {
    "missing_output": 1.0,
    "no_documents": 1.0,
    "tiny_output": 0.8,
    "missing_section": 0.45,
    "no_topics": 0.35,
    "code_fence": 0.35,
    "missing_internal_anchor": 0.3,
    "duplicate_topic_section": 0.3,
    "document_heading_count_mismatch": 0.45,
    "malformed_heading_hierarchy": 0.5,
    "duplicate_document_heading": 0.25,
    "topic_total_mismatch": 0.45,
    "source_inventory_mismatch": 0.4,
    "emitted_less_than_compiled": 0.55,
    "relative_link": 0.35,
    "relative_image": 0.2,
    "empty_link_target": 0.2,
    "html_artifact": 0.35,
    "malformed_table": 0.3,
    "definition_list_artifact": 0.2,
    "duplicate_section_link": 0.2,
}
_COMPONENT_CODES = {
    "completeness": {"missing_output", "no_documents", "tiny_output", "missing_section", "no_topics"},
    "structure": {
        "code_fence",
        "missing_internal_anchor",
        "duplicate_topic_section",
        "document_heading_count_mismatch",
        "malformed_heading_hierarchy",
        "duplicate_document_heading",
    },
    "conversion": {
        "relative_link",
        "relative_image",
        "empty_link_target",
        "html_artifact",
        "malformed_table",
        "definition_list_artifact",
    },
    "consistency": {"topic_total_mismatch", "source_inventory_mismatch", "emitted_less_than_compiled"},
}
_ISSUE_SUGGESTIONS = {
    "relative_link": "Rerun with a newer cache; source HTML may have changed.",
    "html_artifact": "Conversion profile may need tuning for this source.",
    "missing_output": "Run failed before compilation; check the run log.",
}


def validate_output(
    *,
    language: str,
    output_path: Path,
    total_documents: int,
    topics: list[TopicStats],
    source: str = "",
    source_slug: str = "",
    source_diagnostics: SourceRunDiagnostics | None = None,
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not output_path.exists():
        issues.append(
            ValidationIssue(
                level="error",
                code="missing_output",
                message="Consolidated markdown file is missing.",
                suggestion=_ISSUE_SUGGESTIONS["missing_output"],
            )
        )
        zero_scores = ValidationScoreComponents()
        return ValidationResult(
            language=language,
            output_path=output_path,
            score=0.0,
            quality_score=0.0,
            component_scores=zero_scores,
            issues=issues,
        )

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
    issues.extend(_validate_internal_anchors(text))
    issues.extend(_validate_document_structure(text, topics=topics, total_documents=total_documents))
    issues.extend(
        _validate_source_inventory(
            total_documents=total_documents,
            topics=topics,
            source_diagnostics=source_diagnostics,
        )
    )
    issues.extend(_validate_conversion_quality(text))
    document_results = validate_documents(
        language=language,
        language_dir=output_path.parent,
        source=source,
        source_slug=source_slug,
    )
    component_scores = _score_validation(
        issues=issues,
        document_results=document_results,
        total_documents=total_documents,
        topics=topics,
    )
    score = _composite_score(component_scores)

    return ValidationResult(
        language=language,
        output_path=output_path,
        score=round(score, 2),
        quality_score=round(score, 2),
        component_scores=component_scores,
        issues=issues,
        document_results=document_results,
    )


def _score_validation(
    *,
    issues: list[ValidationIssue],
    document_results: list[DocumentValidationResult],
    total_documents: int,
    topics: list[TopicStats],
) -> ValidationScoreComponents:
    topic_count = len(topics)
    bundle_scale = _bundle_scale(total_documents=total_documents, topic_count=topic_count)
    document_scale = _document_scale(total_documents=total_documents)
    component_issues: dict[str, list[ValidationIssue]] = {name: [] for name in _COMPONENT_CODES}
    for issue in issues:
        for component, codes in _COMPONENT_CODES.items():
            if issue.code in codes:
                component_issues[component].append(issue)
                break
    document_issues = [issue for result in document_results for issue in result.issues]
    return ValidationScoreComponents(
        completeness=round(_component_score(component_issues["completeness"], scale=bundle_scale), 2),
        structure=round(
            _component_score(component_issues["structure"], scale=max(1.0, bundle_scale * 0.95)),
            2,
        ),
        conversion=round(
            _component_score(component_issues["conversion"], scale=max(1.0, bundle_scale * 1.1)),
            2,
        ),
        consistency=round(
            _component_score(component_issues["consistency"], scale=max(1.0, bundle_scale)),
            2,
        ),
        document_quality=round(_component_score(document_issues, scale=document_scale), 2),
    )


def _bundle_scale(*, total_documents: int, topic_count: int) -> float:
    document_factor = math.sqrt(max(total_documents - 1, 0)) * 0.18
    topic_factor = math.sqrt(max(topic_count - 1, 0)) * 0.08
    return 1.0 + min(1.6, document_factor + topic_factor)


def _document_scale(*, total_documents: int) -> float:
    return 1.0 + min(1.8, math.sqrt(max(total_documents - 1, 0)) * 0.22)


def _component_score(issues: list[ValidationIssue], *, scale: float) -> float:
    if not issues:
        return 1.0
    penalty = sum(_issue_penalty(issue) for issue in issues)
    score = 1.0 - (penalty / max(scale, 1.0))
    return max(0.0, min(1.0, score))


def _issue_penalty(issue: ValidationIssue) -> float:
    base = _ISSUE_BASE_WEIGHTS.get(issue.code)
    if base is not None:
        return base
    return 0.7 if issue.level == "error" else 0.25 if issue.level == "warning" else 0.1


def _composite_score(component_scores: ValidationScoreComponents) -> float:
    return sum(getattr(component_scores, name) * weight for name, weight in _COMPONENT_WEIGHTS.items())


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
                suggestion=_ISSUE_SUGGESTIONS["relative_link"],
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


def _validate_internal_anchors(text: str) -> list[ValidationIssue]:
    anchors = set(_ANCHOR_RE.findall(text))
    missing: list[str] = []
    for marker, _label, target in _iter_links_outside_code(text):
        if marker:
            continue
        stripped = target.strip()
        if not stripped.startswith("#") or stripped == "#":
            continue
        anchor = stripped[1:]
        if anchor not in anchors:
            missing.append(anchor)
    if not missing:
        return []
    sample = ", ".join(sorted(set(missing))[:5])
    return [
        ValidationIssue(
            level="warning",
            code="missing_internal_anchor",
            message=f"{len(missing)} internal Markdown link(s) point to missing anchors: {sample}.",
        )
    ]


def _validate_document_structure(
    text: str,
    *,
    topics: list[TopicStats],
    total_documents: int,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    documentation_start = text.find("## Documentation")
    if documentation_start < 0:
        return issues
    body = text[documentation_start:]
    topic_names = [stats.topic for stats in topics]
    for topic in topic_names:
        count = len(re.findall(rf"(?m)^###\s+{re.escape(topic)}\s*$", body))
        if count > 1:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="duplicate_topic_section",
                    message=f"Topic {topic!r} appears {count} times in consolidated output.",
                )
            )
    document_heading_count = len(re.findall(r"(?m)^####\s+.+$", body))
    has_structured_documentation = bool(re.search(r"(?m)^###\s+.+$", body) or document_heading_count)
    if total_documents and has_structured_documentation and document_heading_count != total_documents:
        issues.append(
            ValidationIssue(
                level="warning",
                code="document_heading_count_mismatch",
                message=(
                    f"Expected {total_documents} document heading(s), found {document_heading_count} "
                    "in consolidated output."
                ),
            )
        )
    if _has_document_before_topic(body):
        issues.append(
            ValidationIssue(
                level="warning",
                code="malformed_heading_hierarchy",
                message="A document heading appears before the first topic heading.",
            )
        )
    duplicate_documents = _duplicate_document_headings_by_topic(body)
    if duplicate_documents:
        sample = ", ".join(f"{topic}/{title}" for topic, title in duplicate_documents[:5])
        issues.append(
            ValidationIssue(
                level="warning",
                code="duplicate_document_heading",
                message=f"Duplicate document heading(s) detected within topic sections: {sample}.",
            )
        )
    return issues


def _validate_source_inventory(
    *,
    total_documents: int,
    topics: list[TopicStats],
    source_diagnostics: SourceRunDiagnostics | None,
) -> list[ValidationIssue]:
    if source_diagnostics is None:
        return []
    issues: list[ValidationIssue] = []
    topic_total = sum(topic.document_count for topic in topics)
    if topic_total != total_documents:
        issues.append(
            ValidationIssue(
                level="warning",
                code="topic_total_mismatch",
                message=f"Topic document total {topic_total} does not match final document count {total_documents}.",
            )
        )
    skipped = sum(source_diagnostics.skipped.values())
    if source_diagnostics.discovered and source_diagnostics.emitted + skipped < source_diagnostics.discovered:
        issues.append(
            ValidationIssue(
                level="warning",
                code="source_inventory_mismatch",
                message=(
                    "Source diagnostics do not account for all discovered records: "
                    f"discovered={source_diagnostics.discovered}, emitted={source_diagnostics.emitted}, skipped={skipped}."
                ),
            )
        )
    if source_diagnostics.emitted < total_documents:
        issues.append(
            ValidationIssue(
                level="warning",
                code="emitted_less_than_compiled",
                message=f"Source emitted {source_diagnostics.emitted} document(s), but {total_documents} were compiled.",
            )
        )
    return issues


def validate_documents(
    *,
    language: str,
    language_dir: Path,
    source: str = "",
    source_slug: str = "",
) -> list[DocumentValidationResult]:
    results: list[DocumentValidationResult] = []
    if not language_dir.exists():
        return results
    for section_path in sorted(language_dir.glob("*/_section.md")):
        topic = section_path.parent.name
        seen_links: set[str] = set()
        duplicate_links: set[str] = set()
        for link in re.findall(r"\]\(([^)]+\.md)\)", section_path.read_text(encoding="utf-8")):
            if link in seen_links:
                duplicate_links.add(link)
            seen_links.add(link)
        for doc_path in sorted(section_path.parent.glob("*.md")):
            if doc_path.name == "_section.md":
                continue
            text = doc_path.read_text(encoding="utf-8")
            title = _first_heading(text)
            issues = _validate_links(text) + _validate_conversion_quality(text)
            issues.extend(_check_links(text, current_path=doc_path, language_dir=language_dir))
            if doc_path.name in duplicate_links:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        code="duplicate_section_link",
                        message=f"Topic section links to {doc_path.name} more than once.",
                    )
                )
            if issues:
                results.append(
                    DocumentValidationResult(
                        language=language,
                        source=source,
                        source_slug=source_slug,
                        topic=topic,
                        slug=doc_path.stem,
                        title=title,
                        document_path=doc_path,
                        source_url=_source_url(text),
                        issues=issues,
                        context=_first_non_empty_body_line(text),
                        integrity_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        quality_score=round(max(0.0, 1.0 - min(0.95, 0.12 * len(issues))), 2),
                    )
                )
    return results


def _check_links(text: str, *, current_path: Path, language_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for marker, _label, target in _iter_links_outside_code(text):
        if marker:
            continue
        raw = target.strip()
        if not raw or raw.startswith(("http://", "https://", "mailto:", "tel:", "dash://", "data:")):
            continue
        if raw.startswith("#"):
            anchor = raw[1:]
            if anchor and not _has_anchor(text, anchor):
                issues.append(
                    ValidationIssue(
                        level="warning",
                        code="broken_internal_link",
                        message=f"Anchor target #{anchor} not found in current document.",
                    )
                )
            continue
        rel, anchor = (raw.split("#", 1) + [""])[:2]
        target_path = (current_path.parent / rel).resolve()
        try:
            target_path.relative_to(language_dir.resolve())
        except ValueError:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="broken_internal_link",
                    message=f"Relative link escapes language root: {raw}",
                )
            )
            continue
        if not target_path.exists():
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="broken_internal_link",
                    message=f"Relative link target missing: {raw}",
                )
            )
            continue
        if anchor:
            target_text = target_path.read_text(encoding="utf-8")
            if not _has_anchor(target_text, anchor):
                issues.append(
                    ValidationIssue(
                        level="warning",
                        code="broken_internal_link",
                        message=f"Anchor #{anchor} not found in target {rel}.",
                    )
                )
    return issues


def _has_anchor(text: str, anchor: str) -> bool:
    if not anchor:
        return True
    normalized = anchor.strip().lower()
    explicit = {value.strip().lower() for value in _ANCHOR_RE.findall(text)}
    if normalized in explicit:
        return True
    for match in _HEADING_RE.finditer(text):
        heading = match.group(2).strip().lower()
        slug = re.sub(r"[^a-z0-9\\s-]", "", heading)
        slug = re.sub(r"\\s+", "-", slug).strip("-")
        if slug == normalized:
            return True
    return False


def _validate_conversion_quality(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    without_code = "\n".join(_iter_non_code_lines(text))
    if _HTML_LEFTOVER_RE.search(without_code):
        issues.append(
            ValidationIssue(
                level="warning",
                code="html_artifact",
                message="Likely HTML tag leftovers detected in generated Markdown.",
                suggestion=_ISSUE_SUGGESTIONS["html_artifact"],
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


def _has_document_before_topic(text: str) -> bool:
    for match in _HEADING_RE.finditer(text):
        level = len(match.group(1))
        if level == 3:
            return False
        if level == 4:
            return True
    return False


def _duplicate_document_headings_by_topic(text: str) -> list[tuple[str, str]]:
    duplicates: list[tuple[str, str]] = []
    current_topic = ""
    seen: dict[str, set[str]] = {}
    for match in _HEADING_RE.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 3:
            current_topic = title
            seen.setdefault(current_topic, set())
        elif level == 4 and current_topic:
            if title in seen.setdefault(current_topic, set()):
                duplicates.append((current_topic, title))
            seen[current_topic].add(title)
    return duplicates


def _first_heading(text: str) -> str:
    match = _HEADING_RE.search(text)
    return match.group(2).strip() if match else ""


def _source_url(text: str) -> str:
    match = re.search(r"_Source:\s+<([^>]+)>_", text)
    return match.group(1) if match else ""


def _first_non_empty_body_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and not stripped.startswith("_Language:")
            and not stripped.startswith("_Source:")
        ):
            return stripped[:240]
    return ""
