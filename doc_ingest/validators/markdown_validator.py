from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..config import AppConfig
from ..models import ValidationIssue, ValidationResult


def validate_markdown(language: str, output_path: Path, config: AppConfig) -> ValidationResult:
    text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    issues: list[ValidationIssue] = []

    if len(text) < config.crawl.tiny_output_char_threshold:
        issues.append(ValidationIssue(level="error", code="tiny_output", message="Output is unexpectedly small."))

    if text.count("```") % 2 != 0:
        issues.append(ValidationIssue(level="error", code="code_fence", message="Unbalanced code fences detected."))

    headings = [line for line in text.splitlines() if re.match(r"^#{1,6}\s+", line)]
    if not headings or not headings[0].startswith("# "):
        issues.append(ValidationIssue(level="error", code="missing_title", message="Missing top-level title."))

    lines = text.splitlines()
    line_counts = Counter(line for line in lines if line.strip())
    duplicate_lines = [line for line, count in line_counts.items() if count > 15]
    if duplicate_lines:
        issues.append(ValidationIssue(level="warning", code="duplication", message="High repeated-line duplication detected."))

    required_sections = ["## Source Metadata", "## Crawl Summary"]
    for section in required_sections:
        if section not in text:
            issues.append(ValidationIssue(level="warning", code="missing_section", message=f"Missing expected section: {section}"))

    if re.search(r"(?m)^#{1,6}[^\s#]", text):
        issues.append(ValidationIssue(level="warning", code="heading_spacing", message="One or more headings are missing a space after the hash marks."))

    if re.search(r"(?m)^-{3,}\s*$", text) is None:
        issues.append(ValidationIssue(level="info", code="separator_absent", message="No section separators found in merged output."))

    bad_artifacts = ["\ufffd", "Â", "cookie", "accept all"]
    artifact_hits = [artifact for artifact in bad_artifacts if artifact in text]
    if artifact_hits:
        issues.append(ValidationIssue(level="warning", code="artifacts", message=f"Suspicious artifacts found: {', '.join(artifact_hits)}"))

    score = 1.0
    for issue in issues:
        if issue.level == "error":
            score -= 0.3
        elif issue.level == "warning":
            score -= 0.1
    score = max(0.0, round(score, 2))
    return ValidationResult(language=language, output_path=output_path, score=score, issues=issues)
