from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .models import CacheDecision, CacheEntryMetadata, CacheFreshnessPolicy
from .utils.filesystem import read_json, write_json


def cache_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.meta.json")


def decide_cache_refresh(
    path: Path,
    *,
    source: str,
    cache_key: str,
    policy: CacheFreshnessPolicy,
    ttl_hours: int | None = None,
    force_refresh: bool = False,
    now: datetime | None = None,
    cache_root: Path | None = None,
    max_cache_size_bytes: int | None = None,
) -> CacheDecision:
    if force_refresh:
        return CacheDecision(should_refresh=True, reason="force_refresh", policy=policy)
    if not path.exists():
        if max_cache_size_bytes is not None and cache_root is not None:
            current_usage = _directory_usage(cache_root)
            if current_usage >= max_cache_size_bytes:
                return CacheDecision(should_refresh=False, reason="cache_budget_exceeded", policy=policy)
        return CacheDecision(should_refresh=True, reason="missing_cache", policy=policy)
    metadata = read_cache_metadata(path)
    if metadata is None:
        return CacheDecision(should_refresh=policy != "use-if-present", reason="missing_metadata", policy=policy)
    if metadata.source != source or metadata.cache_key != cache_key:
        return CacheDecision(should_refresh=True, reason="metadata_identity_mismatch", policy=policy, metadata=metadata)
    if policy == "always-refresh":
        return CacheDecision(should_refresh=True, reason="always_refresh", policy=policy, metadata=metadata)
    if policy == "ttl":
        hours = ttl_hours if ttl_hours is not None else 24
        reference = now or datetime.now(UTC)
        if metadata.fetched_at.tzinfo is None:
            fetched = metadata.fetched_at.replace(tzinfo=UTC)
        else:
            fetched = metadata.fetched_at
        expired = reference - fetched > timedelta(hours=max(0, hours))
        return CacheDecision(
            should_refresh=expired,
            reason="ttl_expired" if expired else "ttl_fresh",
            policy=policy,
            metadata=metadata,
        )
    if policy == "validate-if-possible":
        return CacheDecision(should_refresh=True, reason="validate_with_conditional", policy=policy, metadata=metadata)
    return CacheDecision(should_refresh=False, reason="use_present", policy=policy, metadata=metadata)


def read_cache_metadata(path: Path) -> CacheEntryMetadata | None:
    try:
        payload = read_json(cache_metadata_path(path), {})
        if not payload:
            return None
        metadata = CacheEntryMetadata.model_validate(payload)
        if path.exists():
            raw = path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest() if raw else ""
            if metadata.checksum and checksum and metadata.checksum != checksum:
                return None
            if metadata.byte_count and metadata.byte_count != len(raw):
                return None
        return metadata
    except Exception:
        return None


def write_cache_metadata(
    path: Path,
    *,
    source: str,
    cache_key: str,
    url: str = "",
    policy: CacheFreshnessPolicy = "use-if-present",
    response: httpx.Response | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    source_version: str = "",
    refreshed_by_force: bool = False,
    mdn_commit_sha: str = "",
) -> CacheEntryMetadata:
    payload = path.read_bytes() if path.exists() else b""
    metadata = CacheEntryMetadata(
        source=source,
        cache_key=cache_key,
        url=url,
        source_version=source_version,
        etag=etag if etag is not None else (response.headers.get("etag", "") if response is not None else ""),
        last_modified=last_modified
        if last_modified is not None
        else (response.headers.get("last-modified", "") if response is not None else ""),
        checksum=hashlib.sha256(payload).hexdigest() if payload else "",
        byte_count=len(payload),
        policy=policy,
        refreshed_by_force=refreshed_by_force,
        mdn_commit_sha=mdn_commit_sha,
    )
    write_json(cache_metadata_path(path), metadata.model_dump(mode="json"))
    return metadata


def write_cache_metadata_for_bytes(
    metadata_target: Path,
    payload: bytes,
    *,
    source: str,
    cache_key: str,
    url: str = "",
    policy: CacheFreshnessPolicy = "use-if-present",
    response: httpx.Response | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    source_version: str = "",
    refreshed_by_force: bool = False,
    mdn_commit_sha: str = "",
) -> CacheEntryMetadata:
    metadata = CacheEntryMetadata(
        source=source,
        cache_key=cache_key,
        url=url,
        source_version=source_version,
        etag=etag if etag is not None else (response.headers.get("etag", "") if response is not None else ""),
        last_modified=last_modified
        if last_modified is not None
        else (response.headers.get("last-modified", "") if response is not None else ""),
        checksum=hashlib.sha256(payload).hexdigest() if payload else "",
        byte_count=len(payload),
        policy=policy,
        refreshed_by_force=refreshed_by_force,
        mdn_commit_sha=mdn_commit_sha,
    )
    write_json(cache_metadata_path(metadata_target), metadata.model_dump(mode="json"))
    return metadata


def _directory_usage(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total
