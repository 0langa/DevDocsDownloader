from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class SourceRuntimePolicy:
    max_concurrency: int = 4
    min_delay_seconds: float = 0.05


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
    ) -> None:
        self.user_agent = user_agent
        self.retry_config = retry_config or RetryConfig()
        self.cache_policy = cache_policy
        self.cache_ttl_hours = cache_ttl_hours
        self.telemetry = SourceRuntimeTelemetry()
        self.policies = policies or _default_policies_from_env()
        self._limiters: dict[str, _RuntimeLimiter] = {}
        self._clients: dict[str, httpx.AsyncClient] = {}
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

    async def request(
        self,
        method: str,
        url: str,
        *,
        profile: str = "default",
        retry_config: RetryConfig | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        limiter = self.limiter(profile)

        def on_retry() -> None:
            self.telemetry.retries += 1

        try:
            async with limiter.semaphore:
                await limiter.wait_for_slot()
                self.telemetry.requests += 1
                response = await request_with_retries(
                    self.client(profile),
                    method,
                    url,
                    retry_config=retry_config or self.retry_config,
                    on_retry=on_retry,
                    **kwargs,
                )
        except Exception:
            self.telemetry.failures += 1
            raise
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

        def on_retry() -> None:
            self.telemetry.retries += 1

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
        except Exception:
            self.telemetry.failures += 1
            raise
        if target.exists():
            self.telemetry.bytes_observed += target.stat().st_size

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self.closed = True


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
