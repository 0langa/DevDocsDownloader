from __future__ import annotations

from pathlib import Path

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
    language_concurrency: int = 3


def load_config(root: Path | None = None, *, output_dir: Path | None = None) -> AppConfig:
    resolved_root = (root or Path(__file__).resolve().parent.parent).resolve()
    config = AppConfig(paths=PathsConfig.from_root(resolved_root))
    if output_dir is not None:
        config.paths.output_dir = output_dir.resolve()
        config.paths.markdown_dir = config.paths.output_dir / "markdown"
        config.paths.reports_dir = config.paths.output_dir / "reports"
    config.paths.ensure()
    return config
