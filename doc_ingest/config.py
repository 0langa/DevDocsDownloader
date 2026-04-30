from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class PathsConfig(BaseModel):
    root: Path
    output_dir: Path
    markdown_dir: Path
    cache_dir: Path
    logs_dir: Path
    state_dir: Path
    checkpoints_dir: Path
    tmp_dir: Path
    reports_dir: Path
    settings_path: Path

    @classmethod
    def from_root(cls, root: Path) -> PathsConfig:
        output_dir = root / "output"
        return cls(
            root=root,
            output_dir=output_dir,
            markdown_dir=output_dir / "markdown",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            state_dir=root / "state",
            checkpoints_dir=root / "state" / "checkpoints",
            tmp_dir=root / "tmp",
            reports_dir=output_dir / "reports",
            settings_path=root / "settings.json",
        )

    @classmethod
    def from_desktop(cls, *, app_name: str, output_dir: Path | None = None) -> PathsConfig:
        local_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / app_name
        documents_root = Path.home() / "Documents" / app_name
        resolved_output = (output_dir or documents_root).resolve()
        return cls(
            root=local_root.resolve(),
            output_dir=resolved_output,
            markdown_dir=resolved_output / "markdown",
            cache_dir=local_root / "cache",
            logs_dir=local_root / "logs",
            state_dir=local_root / "state",
            checkpoints_dir=local_root / "state" / "checkpoints",
            tmp_dir=local_root / "tmp",
            reports_dir=resolved_output / "reports",
            settings_path=local_root / "settings.json",
        )

    def ensure(self) -> None:
        for path in [
            self.output_dir,
            self.markdown_dir,
            self.cache_dir,
            self.logs_dir,
            self.state_dir,
            self.checkpoints_dir,
            self.tmp_dir,
            self.reports_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class AppConfig(BaseModel):
    paths: PathsConfig
    runtime_mode: Literal["repo", "desktop"] = "repo"
    language_concurrency: int = 3
    bulk_concurrency_policy: Literal["static", "adaptive"] = "static"
    adaptive_min_concurrency: int = 1
    adaptive_max_concurrency: int = 6
    generated_markdown_durability: Literal["strict", "balanced"] = "balanced"
    emit_document_frontmatter: bool = False
    emit_chunks: bool = False
    chunk_max_chars: int = 8_000
    chunk_overlap_chars: int = 400
    chunk_strategy: Literal["chars", "tokens"] = "chars"
    chunk_max_tokens: int = 1_000
    chunk_overlap_tokens: int = 100
    cache_policy: Literal["use-if-present", "ttl", "always-refresh", "validate-if-possible"] = "use-if-present"
    cache_ttl_hours: int | None = None
    max_cache_size_mb: int = 2048


def load_config(
    root: Path | None = None,
    *,
    output_dir: Path | None = None,
    runtime_mode: Literal["repo", "desktop"] = "repo",
    app_name: str = "DevDocsDownloader",
) -> AppConfig:
    if runtime_mode == "desktop":
        paths = PathsConfig.from_desktop(app_name=app_name, output_dir=output_dir)
    else:
        resolved_root = (root or Path(__file__).resolve().parent.parent).resolve()
        paths = PathsConfig.from_root(resolved_root)
        if output_dir is not None:
            paths.output_dir = output_dir.resolve()
            paths.markdown_dir = paths.output_dir / "markdown"
            paths.reports_dir = paths.output_dir / "reports"
    config = AppConfig(paths=paths, runtime_mode=runtime_mode)
    config.paths.ensure()
    return config
