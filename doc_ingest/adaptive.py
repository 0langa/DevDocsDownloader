from __future__ import annotations

import shutil
from dataclasses import dataclass, field

from .models import AdaptiveBulkTelemetry, LanguageRunReport


@dataclass(slots=True)
class AdaptiveBulkPolicy:
    initial_concurrency: int
    min_concurrency: int = 1
    max_concurrency: int = 6
    success_window: int = 2
    retry_threshold: int = 2
    pressure_memory_percent: float = 85.0
    pressure_disk_free_percent: float = 5.0


@dataclass(slots=True)
class AdaptiveBulkController:
    policy: AdaptiveBulkPolicy
    current_concurrency: int = field(init=False)
    adjustment_reasons: list[str] = field(default_factory=list)
    observed_windows: int = 0
    failed_languages: int = 0
    retry_pressure_windows: int = 0
    _success_streak: int = 0

    def __post_init__(self) -> None:
        lower = max(1, self.policy.min_concurrency)
        upper = max(lower, self.policy.max_concurrency)
        self.policy.min_concurrency = lower
        self.policy.max_concurrency = upper
        self.current_concurrency = min(max(self.policy.initial_concurrency, lower), upper)

    def observe(self, report: LanguageRunReport) -> None:
        self.observed_windows += 1
        reasons = self._pressure_reasons(report)
        if reasons:
            if any(reason.startswith("memory_pressure") for reason in reasons):
                self._emergency_drop("; ".join(reasons))
                self._success_streak = 0
                return
            if report.failures:
                self.failed_languages += 1
            if any(reason.startswith("retry_pressure") for reason in reasons):
                self.retry_pressure_windows += 1
            self._success_streak = 0
            self._decrease("; ".join(reasons))
            return

        self._success_streak += 1
        if self._success_streak >= self.policy.success_window:
            self._success_streak = 0
            self._increase("successful_window")

    def snapshot(self) -> AdaptiveBulkTelemetry:
        return AdaptiveBulkTelemetry(
            policy="adaptive",
            min_concurrency=self.policy.min_concurrency,
            max_concurrency=self.policy.max_concurrency,
            current_concurrency=self.current_concurrency,
            adjustment_count=len(self.adjustment_reasons),
            adjustment_reasons=list(self.adjustment_reasons),
            observed_windows=self.observed_windows,
            failed_languages=self.failed_languages,
            retry_pressure_windows=self.retry_pressure_windows,
        )

    def _pressure_reasons(self, report: LanguageRunReport) -> list[str]:
        reasons: list[str] = []
        if report.failures:
            reasons.append("language_failure")
        telemetry = report.runtime_telemetry
        if telemetry is not None:
            if telemetry.failures > 0:
                reasons.append(f"source_failures:{telemetry.failures}")
            if telemetry.retries >= self.policy.retry_threshold:
                reasons.append(f"retry_pressure:{telemetry.retries}")
        reasons.extend(_system_pressure_reasons(self.policy))
        return reasons

    def _decrease(self, reason: str) -> None:
        next_value = max(self.policy.min_concurrency, self.current_concurrency - 1)
        if next_value != self.current_concurrency:
            self.current_concurrency = next_value
            self.adjustment_reasons.append(f"decrease:{reason}:to:{next_value}")

    def _increase(self, reason: str) -> None:
        next_value = min(self.policy.max_concurrency, self.current_concurrency + 1)
        if next_value != self.current_concurrency:
            self.current_concurrency = next_value
            self.adjustment_reasons.append(f"increase:{reason}:to:{next_value}")

    def _emergency_drop(self, reason: str) -> None:
        if self.current_concurrency != 1:
            self.current_concurrency = 1
            self.adjustment_reasons.append(f"emergency_decrease:{reason}:to:1")


def static_bulk_telemetry(*, concurrency: int) -> AdaptiveBulkTelemetry:
    value = max(1, concurrency)
    return AdaptiveBulkTelemetry(
        policy="static",
        min_concurrency=value,
        max_concurrency=value,
        current_concurrency=value,
    )


def _system_pressure_reasons(policy: AdaptiveBulkPolicy) -> list[str]:
    reasons: list[str] = []
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        try:
            memory = psutil.virtual_memory()
            if float(memory.percent) >= policy.pressure_memory_percent:
                reasons.append(f"memory_pressure:{memory.percent:.1f}")
        except Exception:
            pass

    try:
        usage = shutil.disk_usage(".")
        free_percent = (usage.free / usage.total) * 100 if usage.total else 100.0
        if free_percent <= policy.pressure_disk_free_percent:
            reasons.append(f"disk_pressure:{free_percent:.1f}")
    except Exception:
        pass
    return reasons
