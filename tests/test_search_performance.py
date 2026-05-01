from __future__ import annotations

import statistics
import time
from pathlib import Path

from doc_ingest.indexer import rebuild_language_index, search


def test_search_p95_under_100ms(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    docs_dir = output_dir / "markdown" / "python" / "docs" / "api"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for index in range(250):
        (docs_dir / f"doc-{index}.md").write_text(
            f"# API {index}\n\nasyncio event_loop handler_{index} snake_case_name()\n",
            encoding="utf-8",
        )
    rebuild_language_index(output_dir=output_dir, language_slug="python")

    durations_ms: list[float] = []
    for _ in range(60):
        started = time.perf_counter()
        rows = search(output_dir=output_dir, query="asyncio", limit=25, language="python")
        elapsed = (time.perf_counter() - started) * 1000.0
        durations_ms.append(elapsed)
        assert rows

    p95 = statistics.quantiles(durations_ms, n=100)[94]
    assert p95 < 100.0, f"search p95 too high: {p95:.2f}ms"
