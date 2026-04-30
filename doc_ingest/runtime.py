from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import CacheFreshnessPolicy
from .utils.http import RetryConfig, request_with_retries, stream_to_file_with_retries

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0)"


@dataclass
class SourceRuntimeTelemetry:
    requests: int = 0
    retries: int = 0
    bytes_observed: int = 0
    failures: int = 0
    cache_hits: int = 0
    cache_refreshes: int = 0
    conditional_get_skips: int = 0
    circuit_breaker_rejections: int = 0


@dataclass(frozen=True)
class SourceRuntimePolicy:
    max_concurrency: int = 4
    min_delay_seconds: float = 0.05


class CircuitBreakerOpenError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceCircuitBreaker:
    threshold: int = 3
    window_seconds: float = 60.0
    backoff_seconds: float = 60.0
    state: str = "closed"
    opened_until: float = 0.0
    last_failure_at: float = 0.0
    last_failure_reason: str = ""
    _failures: deque[float] = field(default_factory=deque)
    _probe_in_flight: bool = False

    def allow_request(self) -> None:
        now = time.monotonic()
        self._trim(now)
        if self.state == "open":
            if now < self.opened_until:
                raise CircuitBreakerOpenError(f"Source circuit open for {max(0.0, self.opened_until - now):.1f}s")
            self.state = "half-open"
            self._probe_in_flight = False
        if self.state == "half-open":
            if self._probe_in_flight:
                raise CircuitBreakerOpenError("Source circuit is probing recovery")
            self._probe_in_flight = True

    def record_success(self) -> None:
        self._failures.clear()
        self.state = "closed"
        self._probe_in_flight = False
        self.opened_until = 0.0

    def record_failure(self, *, reason: str = "") -> None:
        now = time.monotonic()
        self._trim(now)
        self._probe_in_flight = False
        self._failures.append(now)
        self.last_failure_at = now
        self.last_failure_reason = reason
        if self.state == "half-open" or len(self._failures) >= self.threshold:
            self.state = "open"
            self.opened_until = now + self.backoff_seconds

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()


class _RuntimeLimiter:
    def __init__(self, policy: SourceRuntimePolicy) -> None:
        self.policy = policy
        self.semaphore = asyncio.Semaphore(max(1, policy.max_concurrency))
        self.lock = asyncio.Lock()
        self.last_start = 0.0

    async def wait_for_slot(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = self.policy.min_delay_seconds - (now - self.last_start)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_start = time.monotonic()


class SourceRuntime:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        retry_config: RetryConfig | None = None,
        policies: dict[str, SourceRuntimePolicy] | None = None,
        cache_policy: CacheFreshnessPolicy = "use-if-present",
        cache_ttl_hours: int | None = None,
        cache_root: Path | None = None,
        max_cache_size_bytes: int | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.retry_config = retry_config or RetryConfig()
        self.cache_policy = cache_policy
        self.cache_ttl_hours = cache_ttl_hours
        self.cache_root = cache_root
        self.max_cache_size_bytes = max_cache_size_bytes
        self.telemetry = SourceRuntimeTelemetry()
        self.policies = policies or _default_policies_from_env()
        self._limiters: dict[str, _RuntimeLimiter] = {}
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._breakers: dict[str, SourceCircuitBreaker] = {}
        self.closed = False

    def client(self, profile: str = "default") -> httpx.AsyncClient:
        if self.closed:
            raise RuntimeError("SourceRuntime is closed")
        existing = self._clients.get(profile)
        if existing is not None:
            return existing

        timeout: float | None = 60.0
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,*/*"}
        if profile == "download":
            timeout = None
            headers = {"User-Agent": self.user_agent}
        elif profile == "dash":
            timeout = 300.0
            headers = {"User-Agent": self.user_agent}

        client = httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True)
        self._clients[profile] = client
        return client

    def limiter(self, profile: str = "default") -> _RuntimeLimiter:
        policy = self.policies.get(profile) or self.policies["default"]
        key = profile if profile in self.policies else "default"
        limiter = self._limiters.get(key)
        if limiter is None:
            limiter = _RuntimeLimiter(policy)
            self._limiters[key] = limiter
        return limiter

    def breaker(self, url: str) -> SourceCircuitBreaker:
        domain = _domain_for_url(url)
        breaker = self._breakers.get(domain)
        if breaker is None:
            breaker = SourceCircuitBreaker()
            self._breakers[domain] = breaker
        return breaker

    def record_cache_decision(self, decision) -> None:
        if decision.should_refresh:
            self.telemetry.cache_refreshes += 1
        else:
            self.telemetry.cache_hits += 1

    async def request(
        self,
        method: str,
        url: str,
        *,
        profile: str = "default",
        retry_config: RetryConfig | None = None,
        conditional: bool = False,
        etag: str = "",
        last_modified: str = "",
        **kwargs: Any,
    ) -> httpx.Response | NotModifiedResponse:
        limiter = self.limiter(profile)
        breaker = self.breaker(url)

        def on_retry() -> None:
            self.telemetry.retries += 1

        try:
            breaker.allow_request()
        except CircuitBreakerOpenError:
            self.telemetry.circuit_breaker_rejections += 1
            raise

        try:
            async with limiter.semaphore:
                await limiter.wait_for_slot()
                self.telemetry.requests += 1
                request_headers = dict(kwargs.pop("headers", {}) or {})
                if conditional:
                    if etag:
                        request_headers.setdefault("If-None-Match", etag)
                    if last_modified:
                        request_headers.setdefault("If-Modified-Since", last_modified)
                response = await request_with_retries(
                    self.client(profile),
                    method,
                    url,
                    retry_config=retry_config or self.retry_config,
                    on_retry=on_retry,
                    headers=request_headers or None,
                    **kwargs,
                )
                if response.status_code == 304:
                    breaker.record_success()
                    self.telemetry.conditional_get_skips += 1
                    return NotModifiedResponse(headers=dict(response.headers))
                response.raise_for_status()
        except Exception as exc:
            self.telemetry.failures += 1
            breaker.record_failure(reason=f"{type(exc).__name__}: {exc}")
            raise
        breaker.record_success()
        self.telemetry.bytes_observed += len(response.content)
        return response

    async def stream_to_file(
        self,
        url: str,
        target: Path,
        *,
        profile: str = "download",
        retry_config: RetryConfig | None = None,
    ) -> None:
        limiter = self.limiter(profile)
        breaker = self.breaker(url)

        def on_retry() -> None:
            self.telemetry.retries += 1

        try:
            breaker.allow_request()
        except CircuitBreakerOpenError:
            self.telemetry.circuit_breaker_rejections += 1
            raise

        try:
            async with limiter.semaphore:
                await limiter.wait_for_slot()
                self.telemetry.requests += 1
                await stream_to_file_with_retries(
                    self.client(profile),
                    url,
                    target,
                    retry_config=retry_config or self.retry_config,
                    on_retry=on_retry,
                )
        except Exception as exc:
            self.telemetry.failures += 1
            breaker.record_failure(reason=f"{type(exc).__name__}: {exc}")
            raise
        breaker.record_success()
        if target.exists():
            self.telemetry.bytes_observed += target.stat().st_size

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self.closed = True

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        out: dict[str, dict[str, Any]] = {}
        for domain, breaker in self._breakers.items():
            open_seconds = max(0.0, breaker.opened_until - now) if breaker.state == "open" else 0.0
            out[domain] = {
                "state": breaker.state,
                "open_seconds_remaining": round(open_seconds, 3),
                "last_failure_reason": breaker.last_failure_reason,
            }
        return out


def _default_policies_from_env() -> dict[str, SourceRuntimePolicy]:
    global_concurrency = _env_int("DEVDOCS_SOURCE_CONCURRENCY")
    global_delay = _env_float("DEVDOCS_SOURCE_MIN_DELAY")
    defaults = {
        "default": SourceRuntimePolicy(max_concurrency=4, min_delay_seconds=0.05),
        "download": SourceRuntimePolicy(max_concurrency=1, min_delay_seconds=0.0),
        "dash": SourceRuntimePolicy(max_concurrency=2, min_delay_seconds=0.15),
    }
    if global_concurrency is not None or global_delay is not None:
        return {
            key: SourceRuntimePolicy(
                max_concurrency=global_concurrency or policy.max_concurrency,
                min_delay_seconds=global_delay if global_delay is not None else policy.min_delay_seconds,
            )
            for key, policy in defaults.items()
        }
    return defaults


def _domain_for_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or "default"


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return max(1, int(value))
    except ValueError:
        return None


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class NotModifiedResponse:
    headers: dict[str, str]
