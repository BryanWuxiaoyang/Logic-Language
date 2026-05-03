"""Shared compiler exceptions."""

from __future__ import annotations


class CompileError(Exception):
    """Raised when module text cannot be compiled."""
