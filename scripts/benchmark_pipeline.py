from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from doc_ingest.utils.filesystem import write_json, write_text


@dataclass
class TrialResult:
    trial_id: int
    cache_mode: str
    duration_seconds: float
    documents_processed: int
    documents_per_second: float
    output_bytes: int
    output_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "cache_mode": self.cache_mode,
            "duration_seconds": round(self.duration_seconds, 4),
            "documents_processed": self.documents_processed,
            "documents_per_second": round(self.documents_per_second, 6),
            "output_bytes": self.output_bytes,
            "output_dir": str(self.output_dir),
        }


def _load_corpus(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_languages = payload.get("languages", []) if isinstance(payload, dict) else payload
    languages: list[str] = []
    for item in raw_languages:
        if isinstance(item, str):
            languages.append(item)
        elif isinstance(item, dict) and item.get("name"):
            languages.append(str(item["name"]))
    return languages


def _clear_cache_state() -> None:
    for directory in (ROOT / "cache", ROOT / "state"):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _run_trial(
    *,
    trial_id: int,
    cache_mode: str,
    languages: list[str],
    output_dir: Path,
    mode: str,
    source: str | None,
) -> TrialResult:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    for language in languages:
        cmd = [
            sys.executable,
            str(ROOT / "DevDocsDownloader.py"),
            "run",
            language,
            "--mode",
            mode,
            "--output-dir",
            str(output_dir),
            "--silent",
        ]
        if source:
            cmd.extend(["--source", source])
        subprocess.run(cmd, cwd=ROOT, check=True)

    duration = time.perf_counter() - started
    run_summary_path = output_dir / "reports" / "run_summary.json"
    summary = json.loads(run_summary_path.read_text(encoding="utf-8")) if run_summary_path.exists() else {"reports": []}
    documents = sum(int(item.get("total_documents", 0)) for item in summary.get("reports", []))
    output_bytes = _directory_size(output_dir / "markdown")

    return TrialResult(
        trial_id=trial_id,
        cache_mode=cache_mode,
        duration_seconds=duration,
        documents_processed=documents,
        documents_per_second=(documents / duration) if duration > 0 else 0.0,
        output_bytes=output_bytes,
        output_dir=output_dir,
    )


def _summarize(trials: list[TrialResult]) -> dict[str, Any]:
    grouped: dict[str, list[TrialResult]] = {}
    for trial in trials:
        grouped.setdefault(trial.cache_mode, []).append(trial)

    summary: dict[str, Any] = {"modes": {}}
    for mode, values in grouped.items():
        rates = [item.documents_per_second for item in values]
        mean_rate = statistics.fmean(rates) if rates else 0.0
        cv_pct = (statistics.pstdev(rates) / mean_rate * 100.0) if len(rates) > 1 and mean_rate > 0 else 0.0
        summary["modes"][mode] = {
            "trials": len(values),
            "mean_documents_per_second": round(mean_rate, 6),
            "cv_pct": round(cv_pct, 4),
            "mean_duration_seconds": round(statistics.fmean(item.duration_seconds for item in values), 4),
            "mean_documents_processed": round(statistics.fmean(item.documents_processed for item in values), 2),
            "mean_output_bytes": round(statistics.fmean(item.output_bytes for item in values), 2),
        }

    if "cold" in summary["modes"] and "warm" in summary["modes"]:
        cold = summary["modes"]["cold"]["mean_documents_per_second"]
        warm = summary["modes"]["warm"]["mean_documents_per_second"]
        summary["warm_vs_cold_delta_pct"] = round(((warm - cold) / cold * 100.0), 4) if cold > 0 else 0.0
    return summary


def _write_artifacts(*, benchmark_dir: Path, payload: dict[str, Any], trials: list[TrialResult]) -> None:
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    json_path = benchmark_dir / "benchmark_summary.json"
    md_path = benchmark_dir / "benchmark_summary.md"
    payload["trials"] = [item.to_dict() for item in trials]
    write_json(json_path, payload)

    lines = [
        "# Benchmark Summary",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Corpus: {payload['corpus']}",
        f"- Languages: {', '.join(payload['languages'])}",
        f"- Ingestion mode: {payload['mode']}",
        f"- Trials per cache mode: {payload['trials_per_mode']}",
        "",
        "| Cache Mode | Trials | Mean Docs/s | CV % | Mean Duration (s) | Mean Docs | Mean Output Bytes |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, metrics in payload["summary"]["modes"].items():
        lines.append(
            f"| {mode} | {metrics['trials']} | {metrics['mean_documents_per_second']:.6f} | "
            f"{metrics['cv_pct']:.4f} | {metrics['mean_duration_seconds']:.4f} | "
            f"{metrics['mean_documents_processed']:.2f} | {metrics['mean_output_bytes']:.2f} |"
        )
    if "warm_vs_cold_delta_pct" in payload["summary"]:
        lines.extend(["", f"- Warm vs Cold Delta (%): {payload['summary']['warm_vs_cold_delta_pct']:.4f}"])
    write_text(md_path, "\n".join(lines) + "\n")

    latest_path = ROOT / "output" / "reports" / "benchmarks" / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(latest_path, json_path.read_text(encoding="utf-8"))


def run_benchmark(args: argparse.Namespace) -> None:
    corpus_path = Path(args.corpus).resolve()
    languages = _load_corpus(corpus_path)
    if not languages:
        raise RuntimeError(f"No languages found in corpus file: {corpus_path}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    benchmark_dir = ROOT / "output" / "reports" / "benchmarks" / stamp
    modes = [args.cache_mode] if args.cache_mode in {"cold", "warm"} else ["cold", "warm"]
    trials: list[TrialResult] = []

    for cache_mode in modes:
        for trial_id in range(1, args.trials + 1):
            if cache_mode == "cold":
                _clear_cache_state()
            output_dir = benchmark_dir / "trials" / f"{cache_mode}-{trial_id}"
            trials.append(
                _run_trial(
                    trial_id=trial_id,
                    cache_mode=cache_mode,
                    languages=languages,
                    output_dir=output_dir,
                    mode=args.mode,
                    source=args.source,
                )
            )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": str(corpus_path),
        "languages": languages,
        "trials_per_mode": args.trials,
        "cache_mode": args.cache_mode,
        "mode": args.mode,
        "source": args.source,
        "summary": _summarize(trials),
    }
    _write_artifacts(benchmark_dir=benchmark_dir, payload=payload, trials=trials)
    print(f"Benchmark artifacts written to: {benchmark_dir}")


def compare_benchmark(args: argparse.Namespace) -> None:
    latest = json.loads(Path(args.latest).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    latest_rate = float(
        latest.get("summary", {}).get("modes", {}).get(args.mode, {}).get("mean_documents_per_second", 0.0)
    )
    baseline_rate = float(
        baseline.get("summary", {}).get("modes", {}).get(args.mode, {}).get("mean_documents_per_second", 0.0)
    )
    if baseline_rate <= 0:
        raise RuntimeError("Baseline mode rate is zero or missing.")
    delta_pct = ((latest_rate - baseline_rate) / baseline_rate) * 100.0
    print(f"Mode={args.mode} latest={latest_rate:.6f} baseline={baseline_rate:.6f} delta={delta_pct:.4f}%")
    if delta_pct < (-abs(args.fail_on_regression)):
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark harness for the active source-adapter pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run benchmark trials.")
    run_parser.add_argument("--corpus", required=True, help="Path to corpus JSON file.")
    run_parser.add_argument("--trials", type=int, default=3)
    run_parser.add_argument("--cache-mode", choices=["cold", "warm", "both"], default="both")
    run_parser.add_argument("--mode", choices=["important", "full"], default="important")
    run_parser.add_argument("--source", choices=["devdocs", "mdn", "dash"], default=None)
    run_parser.set_defaults(func=run_benchmark)

    compare_parser = sub.add_parser("compare", help="Compare benchmark outputs.")
    compare_parser.add_argument("--latest", required=True)
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--mode", choices=["cold", "warm"], default="cold")
    compare_parser.add_argument(
        "--fail-on-regression", type=float, default=8.0, help="Fail if throughput regression exceeds this percent."
    )
    compare_parser.set_defaults(func=compare_benchmark)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
