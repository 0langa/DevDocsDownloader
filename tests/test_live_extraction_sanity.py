from __future__ import annotations

import asyncio
import os

import pytest

from doc_ingest.live_probe import LiveProbeResult, probe_live_extraction_sanity


@pytest.mark.live
def test_live_source_extraction_sanity() -> None:
    if os.environ.get("DEVDOCS_LIVE_EXTRACTION_TESTS") != "1":
        pytest.skip("Set DEVDOCS_LIVE_EXTRACTION_TESTS=1 to run live extraction sanity probes")

    concurrency = int(os.environ.get("DEVDOCS_LIVE_CONCURRENCY", "3"))
    timeout = float(os.environ.get("DEVDOCS_LIVE_TIMEOUT", "20"))
    limit_value = os.environ.get("DEVDOCS_LIVE_LIMIT")
    limit = int(limit_value) if limit_value else None

    results = asyncio.run(
        probe_live_extraction_sanity(
            concurrency=concurrency,
            timeout_seconds=timeout,
            limit=limit,
        )
    )

    failures = [result for result in results if not result.ok]
    assert not failures, _format_failures(failures)
    if limit is None:
        assert {result.source for result in results} == {"devdocs", "mdn", "dash"}


def _format_failures(failures: list[LiveProbeResult]) -> str:
    if not failures:
        return ""
    lines = [
        "Live extraction sanity failures:",
        "source | language | slug | status | bytes | url | message",
    ]
    for failure in failures:
        lines.append(
            " | ".join(
                [
                    failure.source,
                    failure.language,
                    failure.source_slug,
                    str(failure.status_code or "n/a"),
                    str(failure.downloaded_bytes),
                    failure.probe_url,
                    failure.message,
                ]
            )
        )
    return "\n".join(lines)
