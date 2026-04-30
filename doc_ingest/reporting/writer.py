from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import FailureDetail, RunSummary
from ..utils.filesystem import read_json, write_text


def write_reports(summary: RunSummary, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "run_summary.json"
    md_path = reports_dir / "run_summary.md"

    write_text(json_path, summary.model_dump_json(indent=2))
    _write_history(summary, reports_dir)
    _write_document_validation(summary, reports_dir)

    lines = ["# Documentation Ingestion Report", ""]
    if summary.adaptive_telemetry is not None:
        telemetry = summary.adaptive_telemetry
        lines.extend(
            [
                "## Bulk Concurrency",
                f"- Policy: {telemetry.policy}",
                f"- Current concurrency: {telemetry.current_concurrency}",
                f"- Min concurrency: {telemetry.min_concurrency}",
                f"- Max concurrency: {telemetry.max_concurrency}",
                f"- Adjustments: {telemetry.adjustment_count}",
            ]
        )
        if telemetry.adjustment_reasons:
            lines.append("- Adjustment reasons:")
            for reason in telemetry.adjustment_reasons:
                lines.append(f"  - {reason}")
        lines.append("")
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
            if report.validation.component_scores is not None:
                components = report.validation.component_scores
                lines.append("- Validation components:")
                lines.append(f"  - Completeness: {components.completeness}")
                lines.append(f"  - Structure: {components.structure}")
                lines.append(f"  - Conversion: {components.conversion}")
                lines.append(f"  - Consistency: {components.consistency}")
                lines.append(f"  - Document quality: {components.document_quality}")
            if report.validation.issues:
                lines.append("- Validation issues:")
                for issue in report.validation.issues:
                    text = f"  - [{issue.level}] {issue.code}: {issue.message}"
                    if issue.suggestion:
                        text += f" Suggestion: {issue.suggestion}"
                    lines.append(text)
            if report.validation.document_results:
                lines.append(f"- Document validation records: {len(report.validation.document_results)}")
        if report.runtime_telemetry is not None:
            lines.append("- Runtime telemetry:")
            lines.append(f"  - Requests: {report.runtime_telemetry.requests}")
            lines.append(f"  - Retries: {report.runtime_telemetry.retries}")
            lines.append(f"  - Bytes observed: {report.runtime_telemetry.bytes_observed}")
            lines.append(f"  - Failures: {report.runtime_telemetry.failures}")
            lines.append(f"  - Cache hits: {report.runtime_telemetry.cache_hits}")
            lines.append(f"  - Cache refreshes: {report.runtime_telemetry.cache_refreshes}")
            lines.append(f"  - Conditional GET skips: {report.runtime_telemetry.conditional_get_skips}")
            lines.append(f"  - Circuit breaker rejections: {report.runtime_telemetry.circuit_breaker_rejections}")
        if report.asset_inventory is not None:
            lines.append("- Asset inventory:")
            lines.append(f"  - Total: {report.asset_inventory.total}")
            lines.append(f"  - Copied: {report.asset_inventory.copied}")
            lines.append(f"  - Referenced: {report.asset_inventory.referenced}")
            lines.append(f"  - Skipped: {report.asset_inventory.skipped}")
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
            for warning_text in report.warnings:
                lines.append(f"  - {warning_text}")
        if report.document_warnings:
            lines.append("- Document warnings:")
            for warning_record in report.document_warnings:
                subject = warning_record.title or warning_record.slug or warning_record.source_url or "document"
                lines.append(f"  - [{warning_record.code}] {subject}: {warning_record.message}")
        if report.topics:
            lines.append("- Topics:")
            for stat in report.topics:
                lines.append(f"  - {stat.topic}: {stat.document_count}")
        if report.failures:
            lines.append("- Failures:")
            for failure in report.failures:
                detail = _coerce_failure_detail(failure)
                lines.append(f"  - [{detail.code}] {detail.message}")
                if detail.hint:
                    lines.append(f"    - Hint: {detail.hint}")
        lines.append("")

    write_text(md_path, "\n".join(lines))
    _write_trends(reports_dir)
    return json_path, md_path


def _write_history(summary: RunSummary, reports_dir: Path) -> None:
    history_dir = reports_dir / "history"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_text(history_dir / f"{timestamp}-run_summary.json", summary.model_dump_json(indent=2))


def _write_document_validation(summary: RunSummary, reports_dir: Path) -> None:
    records: list[str] = []
    for report in summary.reports:
        if report.validation is None:
            continue
        for result in report.validation.document_results:
            records.append(result.model_dump_json())
    write_text(reports_dir / "validation_documents.jsonl", "\n".join(records) + ("\n" if records else ""))


def _write_trends(reports_dir: Path) -> None:
    history_dir = reports_dir / "history"
    trend: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": 0,
        "corrupt_history_files": 0,
        "languages": {},
    }
    per_language: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "latest_generated_at": "",
            "latest_total_documents": 0,
            "latest_validation_score": None,
            "latest_duration_seconds": 0.0,
            "issue_counts": Counter(),
            "failures": 0,
            "runtime": {
                "requests": 0,
                "retries": 0,
                "bytes_observed": 0,
                "failures": 0,
                "cache_hits": 0,
                "cache_refreshes": 0,
                "conditional_get_skips": 0,
                "circuit_breaker_rejections": 0,
            },
        }
    )
    for path in sorted(history_dir.glob("*-run_summary.json")):
        try:
            payload = read_json(path, {})
        except Exception:
            trend["corrupt_history_files"] += 1
            continue
        trend["runs"] += 1
        generated_at = str(payload.get("generated_at") or "")
        for report in payload.get("reports", []):
            if not isinstance(report, dict):
                continue
            language = str(report.get("language") or "unknown")
            item = per_language[language]
            item["runs"] += 1
            item["latest_generated_at"] = generated_at
            item["latest_total_documents"] = int(report.get("total_documents") or 0)
            item["latest_duration_seconds"] = float(report.get("duration_seconds") or 0.0)
            raw_validation = report.get("validation")
            validation: dict[str, Any] = raw_validation if isinstance(raw_validation, dict) else {}
            if validation:
                item["latest_validation_score"] = validation.get("score")
                for issue in validation.get("issues", []):
                    if isinstance(issue, dict):
                        item["issue_counts"][str(issue.get("code") or "unknown")] += 1
            raw_failures = report.get("failures")
            failures: list[Any] = raw_failures if isinstance(raw_failures, list) else []
            item["failures"] += len(failures)
            raw_telemetry = report.get("runtime_telemetry")
            telemetry: dict[str, Any] = raw_telemetry if isinstance(raw_telemetry, dict) else {}
            for key in item["runtime"]:
                item["runtime"][key] += int(telemetry.get(key) or 0)
            raw_assets = report.get("asset_inventory")
            assets: dict[str, Any] = raw_assets if isinstance(raw_assets, dict) else {}
            if assets:
                item.setdefault("assets", {"total": 0, "copied": 0, "referenced": 0, "skipped": 0})
                for key in item["assets"]:
                    item["assets"][key] += int(assets.get(key) or 0)

    trend["languages"] = {
        language: {
            **item,
            "issue_counts": dict(item["issue_counts"]),
        }
        for language, item in sorted(per_language.items())
    }
    write_text(reports_dir / "trends.json", json.dumps(trend, indent=2, ensure_ascii=False))

    lines = ["# Documentation Quality Trends", ""]
    lines.append(f"- Runs: {trend['runs']}")
    lines.append(f"- Corrupt history files: {trend['corrupt_history_files']}")
    lines.append("")
    for language, item in trend["languages"].items():
        lines.append(f"## {language}")
        lines.append(f"- Runs: {item['runs']}")
        lines.append(f"- Latest documents: {item['latest_total_documents']}")
        lines.append(f"- Latest validation score: {item['latest_validation_score']}")
        lines.append(f"- Failures: {item['failures']}")
        lines.append(f"- Runtime requests: {item['runtime']['requests']}")
        lines.append(f"- Runtime retries: {item['runtime']['retries']}")
        if item["issue_counts"]:
            lines.append("- Issue counts:")
            for code, count in sorted(item["issue_counts"].items()):
                lines.append(f"  - {code}: {count}")
        lines.append("")
    write_text(reports_dir / "trends.md", "\n".join(lines))


def _coerce_failure_detail(value: FailureDetail | str) -> FailureDetail:
    if isinstance(value, FailureDetail):
        return value
    return FailureDetail(code="runtime_error", message=value)
