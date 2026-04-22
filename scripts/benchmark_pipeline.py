from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TrialResult:
    trial_id: int
    mode: str
    duration_seconds: float
    pages_processed: int
    pages_per_second: float
    cpu_avg_pct: float
    rss_peak_mb: float
    output_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "mode": self.mode,
            "duration_seconds": round(self.duration_seconds, 4),
            "pages_processed": self.pages_processed,
            "pages_per_second": round(self.pages_per_second, 6),
            "cpu_avg_pct": round(self.cpu_avg_pct, 4),
            "rss_peak_mb": round(self.rss_peak_mb, 4),
            "output_dir": str(self.output_dir),
        }


def _load_corpus(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        languages = payload.get("languages", [])
    else:
        languages = payload
    return [item for item in languages if isinstance(item, dict) and item.get("name") and item.get("source_url")]


def _write_input_file(languages: list[dict[str, str]], target: Path) -> None:
    lines = [f"- {item['name']} - {item['source_url']}" for item in languages]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _clear_cache_state() -> None:
    for directory in (ROOT / "cache", ROOT / "state"):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def _run_trial(
    *,
    trial_id: int,
    mode: str,
    input_file: Path,
    output_dir: Path,
    page_concurrency: int,
    extraction_workers: int,
    max_pending_extractions: int,
    no_adaptive: bool,
    max_pages: int,
    max_discovered: int,
    profiler: str,
    profiles_dir: Path,
) -> TrialResult:
    run_args = [
        str(ROOT / "DevDocsDownloader.py"),
        "run",
        "--mode",
        "full",
        "--input-file",
        str(input_file),
        "--output-dir",
        str(output_dir),
        "--page-concurrency",
        str(page_concurrency),
        "--extraction-workers",
        str(extraction_workers),
        "--max-pending-extractions",
        str(max_pending_extractions),
        "--max-pages",
        str(max_pages),
        "--max-discovered",
        str(max_discovered),
        "--normalized-cache-format",
        "json_compact",
        "--compile-streaming",
    ]
    if no_adaptive:
        run_args.append("--no-adaptive-extraction-workers")

    if profiler == "cprofile":
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_path = profiles_dir / f"{mode}-{trial_id}.pstats"
        cmd = [sys.executable, "-m", "cProfile", "-o", str(profile_path), *run_args]
    else:
        cmd = [sys.executable, *run_args]

    started = time.perf_counter()
    subprocess.run(cmd, cwd=ROOT, check=True)
    duration = time.perf_counter() - started

    run_summary_path = output_dir / "reports" / "run_summary.json"
    summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    reports = summary.get("reports", [])
    pages_processed = sum(int(item.get("pages_processed", 0)) for item in reports)
    cpu_avg = 0.0
    rss_peak = 0.0
    if reports:
        cpu_avg = statistics.fmean(float(item.get("performance", {}).get("system", {}).get("cpu_utilization_avg_pct", 0.0)) for item in reports)
        rss_peak = max(float(item.get("performance", {}).get("system", {}).get("resident_memory_peak_mb", 0.0)) for item in reports)

    return TrialResult(
        trial_id=trial_id,
        mode=mode,
        duration_seconds=duration,
        pages_processed=pages_processed,
        pages_per_second=(pages_processed / duration) if duration > 0 else 0.0,
        cpu_avg_pct=cpu_avg,
        rss_peak_mb=rss_peak,
        output_dir=output_dir,
    )


def _summarize(trials: list[TrialResult]) -> dict[str, Any]:
    grouped: dict[str, list[TrialResult]] = {}
    for trial in trials:
        grouped.setdefault(trial.mode, []).append(trial)

    summary: dict[str, Any] = {"modes": {}}
    for mode, values in grouped.items():
        rates = [item.pages_per_second for item in values]
        mean_rate = statistics.fmean(rates) if rates else 0.0
        cv_pct = (statistics.pstdev(rates) / mean_rate * 100.0) if len(rates) > 1 and mean_rate > 0 else 0.0
        summary["modes"][mode] = {
            "trials": len(values),
            "mean_pages_per_second": round(mean_rate, 6),
            "cv_pct": round(cv_pct, 4),
            "mean_duration_seconds": round(statistics.fmean(item.duration_seconds for item in values), 4),
            "mean_cpu_avg_pct": round(statistics.fmean(item.cpu_avg_pct for item in values), 4),
            "mean_rss_peak_mb": round(statistics.fmean(item.rss_peak_mb for item in values), 4),
        }

    if "cold" in summary["modes"] and "warm" in summary["modes"]:
        cold = summary["modes"]["cold"]["mean_pages_per_second"]
        warm = summary["modes"]["warm"]["mean_pages_per_second"]
        summary["warm_vs_cold_delta_pct"] = round(((warm - cold) / cold * 100.0), 4) if cold > 0 else 0.0
    return summary


def _write_artifacts(*, benchmark_dir: Path, payload: dict[str, Any], trials: list[TrialResult]) -> None:
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    json_path = benchmark_dir / "benchmark_summary.json"
    md_path = benchmark_dir / "benchmark_summary.md"
    payload["trials"] = [item.to_dict() for item in trials]
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Benchmark Summary",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Corpus: {payload['corpus']}",
        f"- Trials per mode: {payload['trials_per_mode']}",
        "",
        "| Mode | Trials | Mean Pages/s | CV % | Mean Duration (s) | Mean CPU % | Mean RSS (MB) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, metrics in payload["summary"]["modes"].items():
        lines.append(
            f"| {mode} | {metrics['trials']} | {metrics['mean_pages_per_second']:.6f} | "
            f"{metrics['cv_pct']:.4f} | {metrics['mean_duration_seconds']:.4f} | "
            f"{metrics['mean_cpu_avg_pct']:.4f} | {metrics['mean_rss_peak_mb']:.4f} |"
        )
    if "warm_vs_cold_delta_pct" in payload["summary"]:
        lines.extend(["", f"- Warm vs Cold Delta (%): {payload['summary']['warm_vs_cold_delta_pct']:.4f}"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    latest_path = ROOT / "output" / "reports" / "benchmarks" / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")


def run_benchmark(args: argparse.Namespace) -> None:
    corpus_path = Path(args.corpus).resolve()
    languages = _load_corpus(corpus_path)
    if not languages:
        raise RuntimeError(f"No languages found in corpus file: {corpus_path}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    benchmark_dir = ROOT / "output" / "reports" / "benchmarks" / stamp
    input_file = benchmark_dir / "input.md"
    _write_input_file(languages, input_file)

    modes = [args.cache_mode] if args.cache_mode in {"cold", "warm"} else ["cold", "warm"]
    trials: list[TrialResult] = []

    for mode in modes:
        for trial_id in range(1, args.trials + 1):
            if mode == "cold":
                _clear_cache_state()
            elif mode == "warm":
                if args.prime_warm:
                    _run_trial(
                        trial_id=0,
                        mode="warm-prime",
                        input_file=input_file,
                        output_dir=benchmark_dir / "prime",
                        page_concurrency=args.page_concurrency,
                        extraction_workers=args.extraction_workers,
                        max_pending_extractions=args.max_pending_extractions,
                        no_adaptive=args.no_adaptive,
                        max_pages=args.max_pages,
                        max_discovered=args.max_discovered,
                        profiler=args.profiler,
                        profiles_dir=benchmark_dir / "profiles",
                    )

            output_dir = benchmark_dir / "trials" / f"{mode}-{trial_id}"
            output_dir.mkdir(parents=True, exist_ok=True)
            result = _run_trial(
                trial_id=trial_id,
                mode=mode,
                input_file=input_file,
                output_dir=output_dir,
                page_concurrency=args.page_concurrency,
                extraction_workers=args.extraction_workers,
                max_pending_extractions=args.max_pending_extractions,
                no_adaptive=args.no_adaptive,
                max_pages=args.max_pages,
                max_discovered=args.max_discovered,
                profiler=args.profiler,
                profiles_dir=benchmark_dir / "profiles",
            )
            trials.append(result)

    summary = _summarize(trials)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": str(corpus_path),
        "trials_per_mode": args.trials,
        "cache_mode": args.cache_mode,
        "config": {
            "page_concurrency": args.page_concurrency,
            "extraction_workers": args.extraction_workers,
            "max_pending_extractions": args.max_pending_extractions,
            "max_pages": args.max_pages,
            "max_discovered": args.max_discovered,
            "no_adaptive": args.no_adaptive,
            "profiler": args.profiler,
        },
        "summary": summary,
    }
    _write_artifacts(benchmark_dir=benchmark_dir, payload=payload, trials=trials)
    print(f"Benchmark artifacts written to: {benchmark_dir}")


def compare_benchmark(args: argparse.Namespace) -> None:
    latest = json.loads(Path(args.latest).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    latest_rate = float(latest.get("summary", {}).get("modes", {}).get(args.mode, {}).get("mean_pages_per_second", 0.0))
    baseline_rate = float(baseline.get("summary", {}).get("modes", {}).get(args.mode, {}).get("mean_pages_per_second", 0.0))
    if baseline_rate <= 0:
        raise RuntimeError("Baseline mode rate is zero or missing.")
    delta_pct = ((latest_rate - baseline_rate) / baseline_rate) * 100.0
    print(f"Mode={args.mode} latest={latest_rate:.6f} baseline={baseline_rate:.6f} delta={delta_pct:.4f}%")
    if delta_pct < (-abs(args.fail_on_regression)):
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark harness for DevDocsDownloader pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run benchmark trials.")
    run_parser.add_argument("--corpus", required=True, help="Path to corpus JSON file.")
    run_parser.add_argument("--trials", type=int, default=3)
    run_parser.add_argument("--cache-mode", choices=["cold", "warm", "both"], default="both")
    run_parser.add_argument("--page-concurrency", type=int, default=8)
    run_parser.add_argument("--extraction-workers", type=int, default=4)
    run_parser.add_argument("--max-pending-extractions", type=int, default=64)
    run_parser.add_argument("--max-pages", type=int, default=400)
    run_parser.add_argument("--max-discovered", type=int, default=1200)
    run_parser.add_argument("--profiler", choices=["none", "cprofile"], default="none")
    run_parser.add_argument("--prime-warm", action="store_true", help="Prime warm cache before each warm trial.")
    run_parser.add_argument("--no-adaptive", action="store_true", help="Disable adaptive extraction worker tuning.")
    run_parser.set_defaults(func=run_benchmark)

    compare_parser = sub.add_parser("compare", help="Compare benchmark outputs.")
    compare_parser.add_argument("--latest", required=True)
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--mode", choices=["cold", "warm"], default="cold")
    compare_parser.add_argument("--fail-on-regression", type=float, default=8.0, help="Fail if throughput regression exceeds this percent.")
    compare_parser.set_defaults(func=compare_benchmark)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
