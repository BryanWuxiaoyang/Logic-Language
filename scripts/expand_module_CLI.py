#!/usr/bin/env python3
"""CLI for expanding local logic-language module-text rewrite rules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compile_module_text import CompileError
from expand_module import expand_module_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand local logic-language module-text rules.")
    parser.add_argument("--text", help="module text to expand; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="base directory for $import")
    args = parser.parse_args()

    source = args.text if args.text is not None else sys.stdin.read()
    try:
        sys.stdout.write(expand_module_text(source, args.base_dir))
        return 0
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
