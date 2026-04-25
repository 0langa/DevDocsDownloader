from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .utils.http import RetryConfig, request_with_retries, stream_to_file_with_retries

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; DocIngestBot/1.0)"


@dataclass
class SourceRuntimeTelemetry:
    requests: int = 0
    retries: int = 0
    bytes_observed: int = 0
    failures: int = 0


class SourceRuntime:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.retry_config = retry_config or RetryConfig()
        self.telemetry = SourceRuntimeTelemetry()
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

    async def request(
        self,
        method: str,
        url: str,
        *,
        profile: str = "default",
        retry_config: RetryConfig | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        self.telemetry.requests += 1

        def on_retry() -> None:
            self.telemetry.retries += 1

        try:
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
        self.telemetry.requests += 1

        def on_retry() -> None:
            self.telemetry.retries += 1

        try:
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
