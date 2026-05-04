#!/usr/bin/env python3
"""Compile logic-language module text and print canonical source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compile_module import CompileError, FinalAstValidationCompileError, run_compile_pipeline
from translate_AST_to_source import TranslateError, translate_ast_to_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile and disassemble logic-language module text.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text to compile; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    args = parser.parse_args()

    if args.text is not None:
        source = args.text
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    elif args.file is not None:
        try:
            source = args.file.read_text(encoding="utf-8")
        except OSError as error:
            print(error, file=sys.stderr)
            return 1
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
        allow_imports = True
    else:
        source = sys.stdin.read()
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False

    try:
        ast = run_compile_pipeline(source, base_dir, source=source_name, allow_imports=allow_imports).ast
        sys.stdout.write(translate_ast_to_source(ast))
    except (CompileError, FinalAstValidationCompileError, TranslateError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
