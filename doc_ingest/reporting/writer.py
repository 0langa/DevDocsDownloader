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
        lines.extend(
            [
                f"## {report.language}",
                f"- Source: {report.source_url}",
                f"- Strategy: {report.strategy}",
                f"- Discovered: {report.pages_discovered}",
                f"- Processed: {report.pages_processed}",
                f"- Output: {report.output_path or 'N/A'}",
                f"- Validation score: {report.validation.score if report.validation else 'N/A'}",
            ]
        )
        if report.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in report.warnings)
        if report.failures:
            lines.append("- Failures:")
            lines.extend(f"  - {failure}" for failure in report.failures)
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path