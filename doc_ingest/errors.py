from __future__ import annotations


class OptionalDependencyError(RuntimeError):
    """Raised when an optional dependency is needed for a requested format."""

    def __init__(self, dependency: str, feature: str, *, install_hint: str | None = None) -> None:
        message = f"Optional dependency '{dependency}' is required for {feature}."
        if install_hint:
            message = f"{message} Install it with: {install_hint}"
        super().__init__(message)
        self.dependency = dependency
        self.feature = feature
        self.install_hint = install_hint

