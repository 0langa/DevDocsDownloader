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
        perf = report.performance
        lines.extend(
            [
                f"## {report.language}",
                f"- Source: {report.source_url}",
                f"- Strategy: {report.strategy}",
                f"- Adapter: {report.adapter}",
                f"- Discovered: {report.pages_discovered}",
                f"- Queued: {report.pages_queued}",
                f"- Fetched: {report.pages_fetched}",
                f"- Processed: {report.pages_processed}",
                f"- Skipped: {report.pages_skipped}",
                f"- Failed: {report.pages_failed}",
                f"- Deduplicated: {report.pages_deduplicated}",
                f"- Output: {report.output_path or 'N/A'}",
                f"- Validation score: {report.validation.score if report.validation else 'N/A'}",
                f"- Quality score: {report.validation.quality_score if report.validation else 'N/A'}",
                f"- CPU Avg (%): {perf.system.cpu_utilization_avg_pct:.2f}",
                f"- RSS Peak (MB): {perf.system.resident_memory_peak_mb:.2f}",
            ]
        )
        lines.extend(
            [
                "",
                "| Stage | Duration (ms) | Items | Failures | Throughput (items/s) |",
                "|---|---:|---:|---:|---:|",
                f"| Fetch | {perf.fetch.duration_ms_total:.2f} | {perf.fetch.items_total} | {perf.fetch.failures_total} | {perf.fetch.throughput_items_per_sec:.2f} |",
                f"| Discover | {perf.discover.duration_ms_total:.2f} | {perf.discover.items_total} | {perf.discover.failures_total} | {perf.discover.throughput_items_per_sec:.2f} |",
                f"| Extract | {perf.extract.duration_ms_total:.2f} | {perf.extract.items_total} | {perf.extract.failures_total} | {perf.extract.throughput_items_per_sec:.2f} |",
                f"| Persist | {perf.persist.duration_ms_total:.2f} | {perf.persist.items_total} | {perf.persist.failures_total} | {perf.persist.throughput_items_per_sec:.2f} |",
                "",
                "| Queue | Current | Avg | High-Water |",
                "|---|---:|---:|---:|",
                f"| Discover | {perf.queue_discover.depth_current} | {perf.queue_discover.depth_avg:.2f} | {perf.queue_discover.depth_hwm} |",
                f"| Extract | {perf.queue_extract.depth_current} | {perf.queue_extract.depth_avg:.2f} | {perf.queue_extract.depth_hwm} |",
                "",
                "| Extraction Latency | Value (ms) |",
                "|---|---:|",
                f"| p50 | {perf.extraction_latency.p50_ms:.2f} |",
                f"| p90 | {perf.extraction_latency.p90_ms:.2f} |",
                f"| p95 | {perf.extraction_latency.p95_ms:.2f} |",
                f"| p99 | {perf.extraction_latency.p99_ms:.2f} |",
                "",
                "| Cache | Value |",
                "|---|---:|",
                f"| Fetch hits | {perf.cache.fetch_hits} |",
                f"| Fetch misses | {perf.cache.fetch_misses} |",
                f"| Fetch hit rate | {perf.cache.fetch_hit_rate:.4f} |",
                f"| Normalized hits | {perf.cache.normalized_hits} |",
                f"| Normalized misses | {perf.cache.normalized_misses} |",
                f"| Normalized hit rate | {perf.cache.normalized_hit_rate:.4f} |",
                f"| Normalized serialize ms | {perf.cache.normalized_serialize_ms_total:.2f} |",
                f"| Normalized deserialize ms | {perf.cache.normalized_deserialize_ms_total:.2f} |",
                f"| Normalized bytes written | {perf.cache.normalized_bytes_written} |",
                "",
                "| Workers | Value |",
                "|---|---:|",
                f"| Discover workers | {perf.workers.discover_workers} |",
                f"| Extraction workers current | {perf.workers.extraction_workers_current} |",
                f"| Extraction workers max | {perf.workers.extraction_workers_max} |",
                f"| Extraction scale events | {perf.workers.extraction_scale_events_total} |",
                f"| Extraction busy ratio | {perf.workers.extraction_busy_ratio:.4f} |",
                "",
                "### Extraction Latency Histogram",
            ]
        )
        lines.extend([f"- {bucket}: {count}" for bucket, count in perf.extraction_latency.histogram.items()])
        if report.validation is not None:
            lines.extend(
                [
                    "- Quality Metrics:",
                    f"  - Structure: {report.validation.metrics.structure_quality}",
                    f"  - Duplication Ratio: {report.validation.metrics.duplication_ratio}",
                    f"  - Noise Ratio: {report.validation.metrics.noise_ratio}",
                    f"  - Completeness: {report.validation.metrics.completeness}",
                    f"  - Extraction Confidence: {report.validation.metrics.extraction_confidence}",
                ]
            )
        if report.coverage_notes:
            lines.append("- Coverage Notes:")
            lines.extend(f"  - {note}" for note in report.coverage_notes)
        if report.extractor_choices:
            lines.append("- Extractor Choices:")
            lines.extend(f"  - {name}: {count}" for name, count in sorted(report.extractor_choices.items()))
        if report.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in report.warnings)
        if report.failures:
            lines.append("- Failures:")
            lines.extend(f"  - {failure}" for failure in report.failures)
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
