from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 5.0


DEFAULT_RETRY_CONFIG = RetryConfig()


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry_config: RetryConfig = DEFAULT_RETRY_CONFIG,
    retryable_status_codes: set[int] = RETRYABLE_STATUS_CODES,
    **kwargs: object,
) -> httpx.Response:
    last_exc: Exception | None = None
    attempts = max(1, retry_config.max_attempts)

    for attempt in range(1, attempts + 1):
        try:
            request = getattr(client, "request", None)
            if request is not None:
                response = await request(method, url, **kwargs)
            elif method.upper() == "GET":
                response = await client.get(url, **kwargs)
            else:
                raise AttributeError("HTTP client must provide request() for non-GET methods")
            status_code = getattr(response, "status_code", None)
            if status_code in retryable_status_codes and attempt < attempts:
                aclose = getattr(response, "aclose", None)
                if aclose is not None:
                    await aclose()
                await _sleep_before_retry(attempt, retry_config)
                continue
            return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            await _sleep_before_retry(attempt, retry_config)

    assert last_exc is not None
    raise last_exc


async def stream_to_file_with_retries(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    *,
    retry_config: RetryConfig = DEFAULT_RETRY_CONFIG,
    chunk_size: int = 1 << 20,
    retryable_status_codes: set[int] = RETRYABLE_STATUS_CODES,
) -> None:
    attempts = max(1, retry_config.max_attempts)

    for attempt in range(1, attempts + 1):
        temp_path = target.with_name(f"{target.name}.tmp")
        try:
            async with client.stream("GET", url) as response:
                if response.status_code in retryable_status_codes and attempt < attempts:
                    await _sleep_before_retry(attempt, retry_config)
                    continue
                response.raise_for_status()
                target.parent.mkdir(parents=True, exist_ok=True)
                with temp_path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                temp_path.replace(target)
                return
        except httpx.HTTPStatusError as exc:
            temp_path.unlink(missing_ok=True)
            if exc.response.status_code not in retryable_status_codes or attempt >= attempts:
                raise
            await _sleep_before_retry(attempt, retry_config)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            temp_path.unlink(missing_ok=True)
            if attempt >= attempts:
                raise
            await _sleep_before_retry(attempt, retry_config)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


async def _sleep_before_retry(attempt: int, retry_config: RetryConfig) -> None:
    delay = min(
        retry_config.max_delay_seconds,
        retry_config.base_delay_seconds * (2 ** max(0, attempt - 1)),
    )
    await asyncio.sleep(delay)
