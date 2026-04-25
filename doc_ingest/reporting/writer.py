from __future__ import annotations

from pathlib import Path

from ..models import RunSummary
from ..utils.filesystem import write_text


def write_reports(summary: RunSummary, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "run_summary.json"
    md_path = reports_dir / "run_summary.md"

    write_text(json_path, summary.model_dump_json(indent=2))

    lines = ["# Documentation Ingestion Report", ""]
    for report in summary.reports:
        lines.extend(
            [
                f"## {report.language}",
                f"- Source: {report.source} ({report.source_slug})",
                f"- Source URL: {report.source_url or 'N/A'}",
                f"- Mode: {report.mode}",
                f"- Output: {report.output_path or 'N/A'}",
                f"- Total documents: {report.total_documents}",
                f"- Duration (s): {report.duration_seconds:.2f}",
            ]
        )
        if report.validation is not None:
            lines.append(f"- Validation score: {report.validation.score}")
            if report.validation.issues:
                lines.append("- Validation issues:")
                for issue in report.validation.issues:
                    lines.append(f"  - [{issue.level}] {issue.code}: {issue.message}")
        if report.source_diagnostics is not None:
            lines.append("- Source diagnostics:")
            lines.append(f"  - Discovered: {report.source_diagnostics.discovered}")
            lines.append(f"  - Emitted by source: {report.source_diagnostics.emitted}")
            if report.source_diagnostics.skipped:
                lines.append("  - Skipped:")
                for reason, count in sorted(report.source_diagnostics.skipped.items()):
                    lines.append(f"    - {reason}: {count}")
        if report.warnings:
            lines.append("- Warnings:")
            for warning in report.warnings:
                lines.append(f"  - {warning}")
        if report.topics:
            lines.append("- Topics:")
            for stat in report.topics:
                lines.append(f"  - {stat.topic}: {stat.document_count}")
        if report.failures:
            lines.append("- Failures:")
            for failure in report.failures:
                lines.append(f"  - {failure}")
        lines.append("")

    write_text(md_path, "\n".join(lines))
    return json_path, md_path
