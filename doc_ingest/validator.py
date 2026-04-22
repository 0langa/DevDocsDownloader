from __future__ import annotations

from pathlib import Path

from .models import TopicStats, ValidationIssue, ValidationResult


def validate_output(
    *,
    language: str,
    output_path: Path,
    total_documents: int,
    topics: list[TopicStats],
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not output_path.exists():
        issues.append(ValidationIssue(level="error", code="missing_output", message="Consolidated markdown file is missing."))
        return ValidationResult(language=language, output_path=output_path, score=0.0, issues=issues)

    text = output_path.read_text(encoding="utf-8")
    size = len(text)

    if total_documents == 0:
        issues.append(ValidationIssue(level="error", code="no_documents", message="No documents were ingested."))

    if size < 2000:
        issues.append(ValidationIssue(level="error", code="tiny_output", message=f"Consolidated output is very small ({size} bytes)."))

    if text.count("```") % 2 != 0:
        issues.append(ValidationIssue(level="warning", code="code_fence", message="Unbalanced code fences detected."))

    for section in ("## Metadata", "## Table of Contents", "## Documentation"):
        if section not in text:
            issues.append(ValidationIssue(level="warning", code="missing_section", message=f"Missing section {section!r}."))

    if not topics:
        issues.append(ValidationIssue(level="warning", code="no_topics", message="No topics were produced."))

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
