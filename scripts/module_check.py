#!/usr/bin/env python3
"""Unified diagnostics for logic-language module text."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from compile_module import FinalAstValidationCompileError, Stage2DiagnosticsCompileError, run_compile_pipeline
from compile_pipeline.errors import CompileError
from compile_pipeline.source_utils import load_tokens
from semantic_check import collect_semantic_diagnostics_from_file, collect_semantic_diagnostics_from_text
from syntax_check import STDIN_FILE, Diagnostic, check_text, make_diagnostic, source_position_for_compile_message
from compile_pipeline.module_parser import CheckError


Entry = dict[str, Any]


def split_input(args: argparse.Namespace) -> tuple[str, str, Path, bool]:
    if args.file is not None and args.text is not None:
        raise ValueError("--file and --text are mutually exclusive")
    if args.file is not None:
        path = args.file.resolve()
        return path.read_text(encoding="utf-8"), str(path), args.base_dir or path.parent, True
    if args.text is not None:
        file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
        base_dir = args.base_dir or (args.filename.resolve().parent if args.filename is not None else Path.cwd())
        return args.text, file_label, base_dir, False
    file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
    base_dir = args.base_dir or (args.filename.resolve().parent if args.filename is not None else Path.cwd())
    return sys.stdin.read(), file_label, base_dir, False


def output_payload(entries: list[Entry]) -> dict[str, Any]:
    return {
        "summary": {
            "error_count": sum(1 for entry in entries if entry.get("type") == "error"),
            "warning_count": sum(1 for entry in entries if entry.get("type") == "warning"),
        },
        "entries": sorted(
            entries,
            key=lambda entry: (
                str(entry.get("file", "")),
                int(entry.get("lineno", 0) or 0),
                int(entry.get("col_start_no", 0) or 0),
                str(entry.get("stage", "")),
                str(entry.get("reason", "")),
            ),
        ),
    }


def has_errors(entries: list[Entry]) -> bool:
    return any(entry.get("type") == "error" for entry in entries)


def with_stage(entry: dict[str, Any], stage: str) -> Entry:
    output = dict(entry)
    output["stage"] = stage
    return output


def diagnostic_with_stage(diagnostic: Diagnostic, stage: str) -> Entry:
    return with_stage(diagnostic.to_json(), stage)


def fallback_entry(file_label: str, stage: str, code: str, reason: str) -> Entry:
    return with_stage(make_diagnostic(file_label, 0, 0, 1, "error", code, reason).to_json(), stage)


def first_source_entry(file_label: str, stage: str, code: str, reason: str, source: str | None) -> Entry:
    if source is None:
        return fallback_entry(file_label, stage, code, reason)
    for line_no, line in enumerate(source.splitlines()):
        stripped = line.lstrip()
        if stripped:
            column = len(line) - len(stripped)
            return with_stage(make_diagnostic(file_label, line_no, column, column + 1, "error", code, reason).to_json(), stage)
    return fallback_entry(file_label, stage, code, reason)


def loc_error_entry(error: CompileError | OSError, file_label: str, stage: str, code: str, reason: str) -> Entry | None:
    loc = getattr(error, "source_loc", None)
    if loc is None:
        return None
    if hasattr(loc, "to_json"):
        loc = loc.to_json()
    if not isinstance(loc, dict):
        return None
    file = str(loc.get("source", loc.get("file_path", file_label)))
    line = int(loc.get("line", loc.get("start_line_id", 1)) or 1)
    column = int(loc.get("column", loc.get("start_col_id", 1)) or 1)
    end_column = int(loc.get("end_column", loc.get("end_col_id", column + int(getattr(error, "width", 1) or 1))) or column + 1)
    width = int(getattr(error, "width", 0) or 0)
    if width > 0:
        end_column = max(column + width, end_column)
    diagnostic = make_diagnostic(file, max(line - 1, 0), max(column - 1, 0), max(end_column - 1, column), "error", code, reason)
    return diagnostic_with_stage(diagnostic, stage)


def positioned_error_entry(error: CheckError, stage: str, code: str) -> Entry | None:
    if error.position is None:
        return None
    position = error.position
    diagnostic = make_diagnostic(
        position.file,
        position.line - 1,
        position.column - 1,
        position.column - 1 + error.width,
        "error",
        code,
        str(error),
    )
    return diagnostic_with_stage(diagnostic, stage)


def compile_error_entry(error: CompileError | OSError, file_label: str, source: str | None = None) -> Entry:
    if isinstance(error, CheckError):
        positioned = positioned_error_entry(error, "compile", "compile_error")
        if positioned is not None:
            return positioned
    message = str(error)
    located = loc_error_entry(error, file_label, "compile", "compile_error", message)
    if located is not None:
        return located
    match = re.match(r"^(?P<line>\d+):(?P<column>\d+):\s*(?P<reason>.+)$", message)
    if match is not None:
        line = max(int(match.group("line")) - 1, 0)
        column = max(int(match.group("column")) - 1, 0)
        reason = match.group("reason")
        diagnostic = make_diagnostic(file_label, line, column, column + 1, "error", "compile_error", reason)
        return diagnostic_with_stage(diagnostic, "compile")
    if source is not None:
        source_position = source_position_for_compile_message(message, source)
        if source_position is not None:
            line, column, width = source_position
            diagnostic = make_diagnostic(file_label, line, column, column + width, "error", "compile_error", message)
            return diagnostic_with_stage(diagnostic, "compile")
    return first_source_entry(file_label, "compile", "compile_error", message, source)


def final_ast_entries(error: FinalAstValidationCompileError, file_label: str, source: str | None = None) -> list[Entry]:
    if not error.diagnostics:
        return [first_source_entry(file_label, "final_ast", "final_ast_error", str(error), source)]
    return [with_stage(dict(entry), "final_ast") for entry in error.diagnostics]


def syntax_entries(source: str, file_label: str, base_dir: Path) -> list[Entry]:
    tokens = load_tokens()
    diagnostics = check_text(source, file_label, base_dir.resolve(), tokens)
    return [diagnostic_with_stage(diagnostic, "syntax") for diagnostic in diagnostics]


def semantic_entries(source: str, file_label: str, base_dir: Path, is_file: bool) -> list[Entry]:
    if is_file:
        entries = collect_semantic_diagnostics_from_file(Path(file_label))
    else:
        file_path = None if file_label == STDIN_FILE else Path(file_label)
        entries = collect_semantic_diagnostics_from_text(source, file_path=file_path, base_dir=base_dir.resolve())
    return [with_stage(dict(entry), "semantic") for entry in entries]


def naming_entries(source: str, file_label: str, base_dir: Path) -> list[Entry]:
    from compile_pipeline.stage1_front_end import run as run_front_end

    try:
        front_end = run_front_end(source, base_dir.resolve(), source=file_label, allow_imports=True)
    except CompileError as error:
        if str(error).startswith("stage1 front-end diagnostics failed:"):
            raise
        return []
    return [with_stage(dict(entry), "naming") for entry in front_end.diagnostics]


def compile_entries(source: str, file_label: str, base_dir: Path) -> list[Entry]:
    try:
        run_compile_pipeline(source, base_dir.resolve(), source=file_label, allow_imports=True)
    except Stage2DiagnosticsCompileError as error:
        return [with_stage(dict(entry), "naming") for entry in error.diagnostics]
    except FinalAstValidationCompileError as error:
        return final_ast_entries(error, file_label, source)
    except (CompileError, OSError) as error:
        return [compile_error_entry(error, file_label, source)]
    return []


def check_module(source: str, file_label: str, base_dir: Path, *, is_file: bool) -> dict[str, Any]:
    entries = syntax_entries(source, file_label, base_dir)
    if has_errors(entries):
        return output_payload(entries)

    try:
        entries.extend(naming_entries(source, file_label, base_dir))
    except (CheckError, CompileError, OSError, ValueError) as error:
        positioned = positioned_error_entry(error, "naming", "naming_error") if isinstance(error, CheckError) else None
        entries.append(positioned or loc_error_entry(error, file_label, "naming", "naming_error", str(error)) or first_source_entry(file_label, "naming", "naming_error", str(error), source))
    if has_errors(entries):
        return output_payload(entries)

    try:
        entries.extend(semantic_entries(source, file_label, base_dir, is_file))
    except (CheckError, CompileError, OSError, ValueError) as error:
        positioned = positioned_error_entry(error, "semantic", "semantic_error") if isinstance(error, CheckError) else None
        entries.append(positioned or loc_error_entry(error, file_label, "semantic", "semantic_error", str(error)) or first_source_entry(file_label, "semantic", "semantic_error", str(error), source))
    if has_errors(entries):
        return output_payload(entries)

    entries.extend(compile_entries(source, file_label, base_dir))
    return output_payload(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check logic-language module text and emit unified JSON diagnostics.")
    parser.add_argument("--file", type=Path, help="module-text file to check")
    parser.add_argument("--text", help="module text to check; defaults to stdin")
    parser.add_argument("--filename", type=Path, help="diagnostic file label for --text or stdin")
    parser.add_argument("--base-dir", type=Path, help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    try:
        source, file_label, base_dir, is_file = split_input(args)
        payload = check_module(source, file_label, base_dir, is_file=is_file)
    except (OSError, ValueError) as error:
        payload = output_payload([fallback_entry(STDIN_FILE, "syntax", "cli_usage_error", str(error))])

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 1 if payload["summary"]["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
