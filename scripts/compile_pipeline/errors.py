"""Shared compiler exceptions."""

from __future__ import annotations

from typing import Any


class CompileError(Exception):
    """Raised when module text cannot be compiled."""

    def __init__(self, message: str, *, source_loc: Any | None = None, width: int | None = None) -> None:
        super().__init__(message)
        self.source_loc = source_loc
        self.width = max(width, 1) if width is not None else None
