from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..config import AppConfig
from ..models import CrawlState, QualityMetrics, ValidationIssue, ValidationResult


def validate_markdown(language: str, output_path: Path, config: AppConfig, *, state: CrawlState | None = None) -> ValidationResult:
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

    required_sections = {"Metadata", "Table of Contents", "Documentation", "Appendix"}
    heading_level_two = {line[3:].strip() for line in headings if line.startswith("## ")}
    for section in required_sections:
        if section not in heading_level_two:
            issues.append(ValidationIssue(level="warning", code="missing_section", message=f"Missing expected section: {section}"))

    if re.search(r"(?m)^#{1,6}[^\s#]", text):
        issues.append(ValidationIssue(level="warning", code="heading_spacing", message="One or more headings are missing a space after the hash marks."))

    if re.search(r"(?m)^###\s+", text) is None and re.search(r"(?m)^####\s+", text) is None:
        issues.append(ValidationIssue(level="warning", code="weak_structure", message="Compiled output is missing reconstructed section hierarchy."))

    bad_artifacts = ["\ufffd", "Â", "cookie", "accept all"]
    artifact_hits = [artifact for artifact in bad_artifacts if artifact in text]
    if artifact_hits:
        issues.append(ValidationIssue(level="warning", code="artifacts", message=f"Suspicious artifacts found: {', '.join(artifact_hits)}"))

    if re.search(r"(?m)^\s*<[^>]+>\s*$", text):
        issues.append(ValidationIssue(level="warning", code="inline_html", message="Residual inline HTML was found in the final Markdown."))

    metrics = _quality_metrics(text, state)
    if metrics.duplication_ratio > 0.14:
        issues.append(ValidationIssue(level="warning", code="high_duplication", message="Final output has a high duplication ratio."))
    if metrics.noise_ratio > 0.05:
        issues.append(ValidationIssue(level="warning", code="high_noise", message="Final output contains too much layout or navigation noise."))
    if metrics.structure_quality < 0.7:
        issues.append(ValidationIssue(level="warning", code="low_structure_quality", message="Final output hierarchy is weaker than expected."))
    if metrics.completeness < 0.45:
        issues.append(ValidationIssue(level="warning", code="low_completeness", message="Processed coverage looks low relative to discovered content."))

    score = (
        metrics.structure_quality * 0.30
        + (1.0 - metrics.duplication_ratio) * 0.22
        + (1.0 - metrics.noise_ratio) * 0.16
        + metrics.completeness * 0.18
        + metrics.extraction_confidence * 0.14
    )
    for issue in issues:
        if issue.level == "error":
            score -= 0.3
        elif issue.level == "warning":
            score -= 0.1
    score = max(0.0, round(score, 2))
    return ValidationResult(language=language, output_path=output_path, score=score, quality_score=score, metrics=metrics, issues=issues)


def _quality_metrics(text: str, state: CrawlState | None) -> QualityMetrics:
    lines = [line for line in text.splitlines() if line.strip()]
    headings = [line for line in lines if re.match(r"^#{1,6}\s+", line)]
    heading_levels = [len(re.match(r"^(#{1,6})\s+", line).group(1)) for line in headings]
    heading_jumps = sum(1 for previous, current in zip(heading_levels, heading_levels[1:]) if current - previous > 1)
    required_present = sum(1 for section in ["## Metadata", "## Table of Contents", "## Documentation", "## Appendix"] if section in text)
    section_count = len([line for line in headings if line.startswith("### ")])
    subsection_count = len([line for line in headings if line.startswith("#### ")])
    structure_quality = min(
        1.0,
        0.45 * (required_present / 4)
        + 0.35 * (1.0 - min(1.0, heading_jumps / max(1, len(heading_levels))))
        + 0.20 * min(1.0, subsection_count / max(1, section_count or 1)),
    )

    line_counts = Counter(line.strip().lower() for line in lines if len(line.strip()) > 20)
    repeated_instances = sum(count - 1 for count in line_counts.values() if count > 1)
    duplication_ratio = min(1.0, repeated_instances / max(1, len(lines)))

    noise_terms = ["on this page", "related content", "additional resources", "cookie", "feedback", "skip to main content", "accept all"]
    noise_hits = sum(text.lower().count(term) for term in noise_terms)
    noise_ratio = min(1.0, noise_hits / max(1, len(lines)))

    if state is not None and state.pages:
        processed = sum(1 for page in state.pages.values() if page.status == "processed")
        discovered = len(state.pages)
        completeness = processed / max(1, discovered)
        extraction_scores = [page.extraction_score for page in state.pages.values() if page.status == "processed" and page.extraction_score is not None]
        extraction_confidence = sum(extraction_scores) / len(extraction_scores) if extraction_scores else 0.0
        low_quality_pages = sum(1 for page in state.pages.values() if page.status == "processed" and ((page.extraction_score or 0.0) < 0.35 or page.warning_codes))
    else:
        completeness = 0.65 if section_count else 0.0
        extraction_confidence = 0.5
        low_quality_pages = 0

    return QualityMetrics(
        structure_quality=round(structure_quality, 2),
        duplication_ratio=round(duplication_ratio, 2),
        noise_ratio=round(noise_ratio, 2),
        completeness=round(min(1.0, completeness), 2),
        extraction_confidence=round(min(1.0, extraction_confidence), 2),
        section_count=section_count,
        subsection_count=subsection_count,
        low_quality_pages=low_quality_pages,
    )
