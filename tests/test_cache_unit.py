from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from doc_ingest.cache import decide_cache_refresh, read_cache_metadata, write_cache_metadata


@pytest.mark.parametrize(
    ("policy", "metadata_age_hours", "expected_should_refresh", "expected_reason"),
    [
        ("use-if-present", 1, False, "use_present"),
        ("ttl", 1, False, "ttl_fresh"),
        ("ttl", 48, True, "ttl_expired"),
        ("always-refresh", 1, True, "always_refresh"),
        ("validate-if-possible", 1, True, "validate_with_conditional"),
    ],
)
def test_decide_cache_refresh_covers_common_policy_states(
    tmp_path: Path,
    policy: str,
    metadata_age_hours: int,
    expected_should_refresh: bool,
    expected_reason: str,
) -> None:
    path = tmp_path / "entry.json"
    path.write_text("{}", encoding="utf-8")
    write_cache_metadata(path, source="devdocs", cache_key="python/index.json", policy="ttl")

    metadata_path = path.with_name(f"{path.name}.meta.json")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["fetched_at"] = (datetime.now(UTC) - timedelta(hours=metadata_age_hours)).isoformat()
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    decision = decide_cache_refresh(
        path,
        source="devdocs",
        cache_key="python/index.json",
        policy=policy,  # type: ignore[arg-type]
        ttl_hours=24,
    )

    assert decision.should_refresh is expected_should_refresh
    assert decision.reason == expected_reason


def test_decide_cache_refresh_detects_identity_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "entry.json"
    path.write_text("{}", encoding="utf-8")
    write_cache_metadata(path, source="devdocs", cache_key="python/index.json")

    decision = decide_cache_refresh(
        path,
        source="devdocs",
        cache_key="python/db.json",
        policy="use-if-present",
    )

    assert decision.should_refresh is True
    assert decision.reason == "metadata_identity_mismatch"


def test_decide_cache_refresh_respects_cache_budget_for_new_entries(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    filler = cache_root / "filler.bin"
    filler.write_bytes(b"x" * 64)

    decision = decide_cache_refresh(
        cache_root / "missing.json",
        source="devdocs",
        cache_key="python/index.json",
        policy="use-if-present",
        cache_root=cache_root,
        max_cache_size_bytes=32,
    )

    assert decision.should_refresh is False
    assert decision.reason == "cache_budget_exceeded"


def test_read_cache_metadata_detects_checksum_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "entry.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    write_cache_metadata(path, source="devdocs", cache_key="python/index.json")

    path.write_text('{"ok": false}', encoding="utf-8")

    assert read_cache_metadata(path) is None
