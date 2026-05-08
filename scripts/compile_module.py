#!/usr/bin/env python3
"""Compile logic-language module text to final module_AST JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from check_final_AST import FinalAstChecker
from compile_pipeline.errors import CompileError

if __name__ == "__main__":
    sys.modules.setdefault("compile_module", sys.modules[__name__])


class FinalAstValidationCompileError(CompileError):
    """Raised when final module_AST validation fails after compilation."""

    def __init__(
        self,
        message: str,
        stage_summaries: list[str],
        diagnostics: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage_summaries = stage_summaries
        self.diagnostics = diagnostics or []


class Stage2DiagnosticsCompileError(CompileError):
    """Raised when stage 2 emits fatal diagnostics before section parsing."""

    def __init__(self, diagnostics: list[dict[str, object]], stage_summaries: list[str]) -> None:
        super().__init__(format_stage2_diagnostics_error(diagnostics))
        self.diagnostics = diagnostics
        self.stage_summaries = stage_summaries


@dataclass(frozen=True)
class CompilePipelineResult:
    ast: dict[str, Any]
    stage_summaries: list[str]


def format_final_ast_validation_error(diagnostics: list[dict[str, object]]) -> str:
    lines = ["final AST validation failed:"]
    for entry in diagnostics:
        file = str(entry.get("file", "<ast>"))
        line = int(entry.get("lineno", 0) or 0) + 1
        column = int(entry.get("col_start_no", 0) or 0) + 1
        code = str(entry.get("code", "final_ast_invalid"))
        reason = str(entry.get("reason", "final AST validation failed"))
        lines.append(f"{file}:{line}:{column}: {code}: {reason}")
    return "\n".join(lines)


def format_stage2_diagnostics_error(diagnostics: list[dict[str, object]]) -> str:
    lines = ["stage2 diagnostics failed:"]
    for entry in diagnostics:
        file = str(entry.get("file", "<ast>"))
        line = int(entry.get("lineno", 0) or 0) + 1
        column = int(entry.get("col_start_no", 0) or 0) + 1
        code = str(entry.get("code", "stage2_error"))
        reason = str(entry.get("reason", "stage2 diagnostic failed"))
        lines.append(f"{file}:{line}:{column}: {code}: {reason}")
    return "\n".join(lines)


def run_compile_pipeline(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> CompilePipelineResult:
    from compile_pipeline.stage1_front_end import run as run_front_end
    from compile_pipeline.stage2_back_end import run as run_back_end

    front_end = run_front_end(text, base_dir, source=source, allow_imports=allow_imports)
    back_end = run_back_end(front_end)
    ast_json = back_end.to_json()
    stage_summaries = [
        front_end.summary(),
        back_end.summary(),
    ]
    diagnostics = FinalAstChecker().check(ast_json)
    if diagnostics:
        raise FinalAstValidationCompileError(
            format_final_ast_validation_error(diagnostics),
            stage_summaries,
            diagnostics,
        )
    return CompilePipelineResult(ast=ast_json, stage_summaries=stage_summaries)


def compile_module(text: str, base_dir: Path | str = ".") -> dict[str, Any]:
    return run_compile_pipeline(text, base_dir).ast


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile logic-language module text to module_AST JSON.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text to compile; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    parser.add_argument("--debug-stages", action="store_true", help="emit summaries for every compile stage")
    args = parser.parse_args()

    if args.text is not None:
        source = args.text
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    elif args.file is not None:
        source = args.file.read_text(encoding="utf-8")
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
        allow_imports = True
    else:
        source = sys.stdin.read()
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    try:
        result = run_compile_pipeline(source, base_dir, source=source_name, allow_imports=allow_imports)
    except FinalAstValidationCompileError as error:
        if args.debug_stages:
            sys.stdout.write("\n\n".join(error.stage_summaries))
            sys.stdout.write("\n")
        print(error, file=sys.stderr)
        return 1
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.debug_stages:
        sys.stdout.write("\n\n".join(result.stage_summaries))
        sys.stdout.write("\n")
        return 0
    json.dump(result.ast, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
