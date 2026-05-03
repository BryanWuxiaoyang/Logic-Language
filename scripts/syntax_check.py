#!/usr/bin/env python3
"""Check logic-language module-text syntax and emit JSON diagnostics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import ModuleCompiler, strip_outer_blank_lines
from compile_pipeline.source_utils import (
    IMPORT_RE,
    LATEX_CODE_RE,
    find_quoted_literal_end,
    is_literal_quote_start,
    load_lark_parser,
    load_tokens,
    normalize_latex,
    remove_comments,
    resolve_import_path,
)


STDIN_FILE = "<stdin>"


@dataclass(frozen=True)
class Diagnostic:
    file: str
    lineno: int
    col_start_no: int
    col_end_no: int
    type: str
    code: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "lineno": self.lineno,
            "col_start_no": self.col_start_no,
            "col_end_no": self.col_end_no,
            "type": self.type,
            "code": self.code,
            "reason": self.reason,
        }


def check_text(
    text: str,
    file_label: str,
    base_dir: Path,
    tokens: dict[str, str],
    parser: Any,
    seen: set[Path] | None = None,
) -> list[Diagnostic]:
    seen = set() if seen is None else set(seen)
    diagnostics: list[Diagnostic] = []
    body_lines = split_imports_with_diagnostics(text, file_label, base_dir, diagnostics, seen, tokens, parser)
    body_text = "\n".join(body_lines)

    latex_diagnostics = latex_errors(text, file_label, tokens)
    diagnostics.extend(latex_diagnostics)
    local_brace_diagnostics = brace_errors(body_text, file_label)
    diagnostics.extend(local_brace_diagnostics)
    if latex_diagnostics or local_brace_diagnostics:
        return diagnostics

    try:
        normalized_body = normalize_latex(body_text, tokens)
        cleaned_body = remove_comments(normalized_body)
        body_line_offset = leading_blank_line_count(cleaned_body)
        body = strip_outer_blank_lines(cleaned_body)
        ModuleCompiler(parser).compile(body)
    except CompileError as error:
        diagnostics.append(compile_error_to_diagnostic(str(error), file_label, body_line_offset))

    return diagnostics


def split_imports_with_diagnostics(
    text: str,
    file_label: str,
    base_dir: Path,
    diagnostics: list[Diagnostic],
    seen: set[Path],
    tokens: dict[str, str],
    parser: Any,
) -> list[str]:
    body_lines: list[str] = []
    for line_index, line in enumerate(text.splitlines()):
        if not line.strip().startswith("$import"):
            body_lines.append(line)
            continue
        body_lines.append("")

        match = IMPORT_RE.match(line)
        if match is None:
            diagnostics.append(
                make_diagnostic(
                    file_label,
                    line_index,
                    first_non_space_column(line),
                    max(first_non_space_column(line) + 1, len(line)),
                    "error",
                    "invalid_import",
                    "invalid import syntax",
                )
            )
            continue

        raw_path = match.group("path").strip().strip("\"'")
        path_start = line.find(match.group("path"))
        import_path = resolve_import_path(raw_path, base_dir)
        if import_path in seen:
            diagnostics.append(
                make_diagnostic(
                    file_label,
                    line_index,
                    path_start,
                    path_start + len(match.group("path")),
                    "error",
                    "cyclic_import",
                    f"cyclic import: {import_path}",
                )
            )
            continue
        if not import_path.exists():
            diagnostics.append(
                make_diagnostic(
                    file_label,
                    line_index,
                    path_start,
                    path_start + len(match.group("path")),
                    "error",
                    "missing_import",
                    f"import not found: {import_path}",
                )
            )
            continue
        try:
            imported = import_path.read_text(encoding="utf-8")
        except OSError as error:
            diagnostics.append(
                make_diagnostic(
                    file_label,
                    line_index,
                    path_start,
                    path_start + len(match.group("path")),
                    "error",
                    "import_read_error",
                    str(error),
                )
            )
            continue
        diagnostics.extend(check_text(imported, str(import_path), import_path.parent, tokens, parser, seen | {import_path}))
    return body_lines


def latex_errors(text: str, file_label: str, tokens: dict[str, str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    index = 0
    while index < len(text):
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if text[index] == "#":
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline + 1
            continue
        match = LATEX_CODE_RE.match(text, index)
        if match is not None:
            code = match.group(0)
            if code not in tokens:
                line, column = zero_based_line_column(text, match.start())
                diagnostics.append(
                    make_diagnostic(
                        file_label,
                        line,
                        column,
                        column + len(code),
                        "error",
                        "unknown_latex_code",
                        f"unknown latex code {code}",
                    )
                )
            index = match.end()
            continue
        index += 1
    return diagnostics


def brace_errors(text: str, file_label: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    stack: list[tuple[int, int]] = []
    for line_index, line in enumerate(text.splitlines()):
        code = strip_comment_for_scan(line)
        column = 0
        while column < len(code):
            if is_literal_quote_start(code, column):
                column = find_quoted_literal_end(code, column) + 1
                continue
            char = code[column]
            if char == "{":
                stack.append((line_index, column))
            elif char == "}":
                if stack:
                    stack.pop()
                else:
                    diagnostics.append(
                        make_diagnostic(
                            file_label,
                            line_index,
                            column,
                            column + 1,
                            "error",
                            "unmatched_closing_brace",
                            "unmatched closing brace",
                        )
                    )
            column += 1
    for line_index, column in stack:
        diagnostics.append(
            make_diagnostic(
                file_label,
                line_index,
                column,
                column + 1,
                "error",
                "unclosed_brace",
                "unclosed brace",
            )
        )
    return diagnostics


def strip_comment_for_scan(line: str) -> str:
    index = 0
    while index < len(line):
        if is_literal_quote_start(line, index):
            index = find_quoted_literal_end(line, index) + 1
            continue
        if line[index] == "#":
            return line[:index]
        index += 1
    return line


def compile_error_to_diagnostic(message: str, file_label: str, line_offset: int) -> Diagnostic:
    match = re.match(r"^(?P<line>\d+):(?P<column>\d+):\s*(?P<reason>.+)$", message)
    if match is not None:
        line = max(int(match.group("line")) - 1 + line_offset, 0)
        column = max(int(match.group("column")) - 1, 0)
        reason = match.group("reason")
        return make_diagnostic(file_label, line, column, column + 1, "error", code_for_reason(reason), reason)
    return make_diagnostic(file_label, 0, 0, 1, "error", code_for_reason(message), message)


def code_for_reason(reason: str) -> str:
    if reason == "empty module text":
        return "empty_module"
    if reason in {"module requires target statements", "module requires non-empty target_statements"}:
        return "missing_target"
    if reason == "set module requires non-empty syms":
        return "set_module_missing_syms"
    if reason.startswith("unknown latex code"):
        return "unknown_latex_code"
    if reason.startswith("unclosed"):
        return "unclosed_brace"
    if reason == "parse error":
        return "parse_error"
    return "syntax_error"


def split_input(args: argparse.Namespace) -> tuple[str, str, Path]:
    if args.file is not None and args.text is not None:
        raise ValueError("--file and --text are mutually exclusive")
    if args.file is not None:
        path = args.file.resolve()
        return path.read_text(encoding="utf-8"), str(path), args.base_dir or path.parent
    if args.text is not None:
        file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
        return args.text, file_label, args.base_dir or Path.cwd()
    file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
    return sys.stdin.read(), file_label, args.base_dir or Path.cwd()


def zero_based_line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start


def first_non_space_column(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def leading_blank_line_count(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip():
            break
        count += 1
    return count


def make_diagnostic(
    file_label: str,
    line: int,
    col_start: int,
    col_end: int,
    entry_type: str,
    code: str,
    reason: str,
) -> Diagnostic:
    col_start = max(col_start, 0)
    col_end = max(col_end, col_start + 1)
    return Diagnostic(
        file=file_label,
        lineno=max(line, 0),
        col_start_no=col_start,
        col_end_no=col_end,
        type=entry_type,
        code=code,
        reason=reason,
    )


def output_payload(entries: list[Diagnostic]) -> dict[str, Any]:
    return {
        "summary": {
            "error_count": sum(1 for entry in entries if entry.type == "error"),
            "warning_count": sum(1 for entry in entries if entry.type == "warning"),
        },
        "entries": [entry.to_json() for entry in entries],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check logic-language module-text syntax.")
    parser.add_argument("--file", type=Path, help="module-text file to check")
    parser.add_argument("--text", help="module text to check; defaults to stdin")
    parser.add_argument("--filename", type=Path, help="diagnostic file label for --text or stdin")
    parser.add_argument("--base-dir", type=Path, help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    try:
        source, file_label, base_dir = split_input(args)
        tokens = load_tokens()
        parser_instance = load_lark_parser()
        entries = check_text(source, file_label, base_dir.resolve(), tokens, parser_instance)
    except ValueError as error:
        entries = [make_diagnostic(STDIN_FILE, 0, 0, 1, "error", "cli_usage_error", str(error))]
        payload = output_payload(entries)
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 2
    except (CompileError, OSError) as error:
        entries = [make_diagnostic(STDIN_FILE, 0, 0, 1, "error", "syntax_error", str(error))]

    payload = output_payload(entries)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 1 if payload["summary"]["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
