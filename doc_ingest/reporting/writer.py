from __future__ import annotations

from pathlib import Path

from ..models import RunSummary


def write_reports(summary: RunSummary, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "run_summary.json"
    md_path = reports_dir / "run_summary.md"

    json_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

    lines = ["# Documentation Ingestion Report", ""]
    for report in summary.reports:
        lines.extend([
            f"## {report.language}",
            f"- Source: {report.source} ({report.source_slug})",
            f"- Source URL: {report.source_url or 'N/A'}",
            f"- Mode: {report.mode}",
            f"- Output: {report.output_path or 'N/A'}",
            f"- Total documents: {report.total_documents}",
            f"- Duration (s): {report.duration_seconds:.2f}",
        ])
        if report.validation is not None:
            lines.append(f"- Validation score: {report.validation.score}")
            if report.validation.issues:
                lines.append("- Validation issues:")
                for issue in report.validation.issues:
                    lines.append(f"  - [{issue.level}] {issue.code}: {issue.message}")
        if report.topics:
            lines.append("- Topics:")
            for stat in report.topics:
                lines.append(f"  - {stat.topic}: {stat.document_count}")
        if report.failures:
            lines.append("- Failures:")
            for failure in report.failures:
                lines.append(f"  - {failure}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
