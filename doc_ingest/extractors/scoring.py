from __future__ import annotations

import re
from collections import Counter

from ..models import ExtractedDocument, ExtractionDecision, ExtractionMetrics


NOISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bcookie\b",
        r"\bprivacy\b",
        r"\bfeedback\b",
        r"\btable of contents\b",
        r"\bskip to main content\b",
        r"\ball rights reserved\b",
    ]
]


def score_extraction(document: ExtractedDocument, extractor_name: str) -> ExtractionDecision:
    lines = [line.strip() for line in document.markdown.splitlines()]
    non_empty = [line for line in lines if line]
    link_lines = [line for line in non_empty if line.count("[") and line.count("](")]
    repeated_lines = [count for count in Counter(non_empty).values() if count > 1]
    heading_count = sum(1 for line in non_empty if re.match(r"^#{1,6}\s", line))
    code_block_count = document.markdown.count("```") // 2
    table_count = sum(1 for line in non_empty if "|" in line and line.count("|") >= 2)
    malformed_chars = sum(document.markdown.count(char) for char in ["\ufffd", "Â", "\x00"])
    boilerplate_hits = sum(1 for line in non_empty for pattern in NOISE_PATTERNS if pattern.search(line))

    metrics = ExtractionMetrics(
        text_length=len(document.markdown),
        word_count=document.word_count,
        heading_count=heading_count,
        code_block_count=code_block_count,
        table_count=table_count,
        link_line_ratio=(len(link_lines) / len(non_empty)) if non_empty else 0.0,
        repeated_line_ratio=(sum(repeated_lines) / len(non_empty)) if non_empty else 0.0,
        boilerplate_ratio=(boilerplate_hits / len(non_empty)) if non_empty else 0.0,
        malformed_ratio=(malformed_chars / max(1, len(document.markdown))),
        blank_line_ratio=(len(lines) - len(non_empty)) / max(1, len(lines)),
    )

    score = 0.0
    signals: list[str] = []
    score += min(0.35, metrics.word_count / 300)
    score += min(0.15, metrics.heading_count * 0.03)
    score += min(0.12, metrics.code_block_count * 0.03)
    score += min(0.08, metrics.table_count * 0.02)
    if metrics.word_count >= 10 and metrics.heading_count >= 1:
        score += 0.05
    if metrics.link_line_ratio < 0.25:
        score += 0.1
        signals.append("low-link-noise")
    else:
        score -= min(0.18, metrics.link_line_ratio * 0.3)
    if metrics.repeated_line_ratio < 0.12:
        score += 0.08
        signals.append("low-duplication")
    else:
        score -= min(0.2, metrics.repeated_line_ratio * 0.4)
    if metrics.boilerplate_ratio < 0.08:
        score += 0.08
        signals.append("low-boilerplate")
    else:
        score -= min(0.15, metrics.boilerplate_ratio * 0.6)
    if metrics.malformed_ratio == 0:
        score += 0.04
    else:
        score -= min(0.15, metrics.malformed_ratio * 10)
    if metrics.word_count < 40:
        score -= 0.08
        signals.append("short-output")
    if heading_count == 0 and metrics.word_count > 300:
        signals.append("weak-structure")
        score -= 0.08

    metrics.score = round(max(0.0, min(1.0, score)), 3)
    metrics.signals = signals
    return ExtractionDecision(
        extractor=extractor_name,
        score=metrics.score,
        won_because=signals.copy(),
        metrics=metrics,
    )
