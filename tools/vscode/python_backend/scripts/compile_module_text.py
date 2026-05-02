#!/usr/bin/env python3
"""Compatibility shim for the renamed compile_module entrypoint."""

from __future__ import annotations

from compile_module import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
