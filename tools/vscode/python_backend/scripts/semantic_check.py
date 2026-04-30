#!/usr/bin/env python3
"""Semantic diagnostics for logic-language module text."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compile_module_text import FRESH_PREFIX, CompileError, parse_declaration
from syntax_check_common import (
    STDIN_FILE,
    Binder,
    CheckError,
    CheckModule,
    Declaration,
    SourcePosition,
    analyze_module_file,
    analyze_module_text,
)


@dataclass(frozen=True)
class Diagnostic:
    file: str
    lineno: int
    col_start_no: int
    col_end_no: int
    type: str
    code: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "file": self.file,
            "lineno": self.lineno,
            "col_start_no": self.col_start_no,
            "col_end_no": self.col_end_no,
            "type": self.type,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class VisibleDeclaration:
    name: str
    position: SourcePosition
    scope_id: int | None

    @property
    def is_imported(self) -> bool:
        return self.position.import_origin or self.scope_id is None


@dataclass
class ScopeContext:
    scope_id: int
    ancestors: tuple[int, ...]


class SemanticChecker:
    def __init__(
        self,
        import_declarations: list[Declaration],
        *,
        source_text: str | None = None,
        source_file: str | None = None,
    ) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.visible: dict[str, list[VisibleDeclaration]] = {}
        self.next_scope_id = 0
        self.source_lines_by_file: dict[str, list[str]] = {}
        if source_text is not None and source_file is not None:
            self.source_lines_by_file[source_file] = source_text.splitlines()
        for declaration in import_declarations:
            self.add_visible(VisibleDeclaration(declaration.name, declaration.position, None))

    def check(self, module: CheckModule) -> list[Diagnostic]:
        self.visit_module(module, ScopeContext(self.allocate_scope(), tuple()))
        return sorted(self.diagnostics, key=lambda diagnostic: (diagnostic.file, diagnostic.lineno, diagnostic.col_start_no, diagnostic.reason))

    def allocate_scope(self) -> int:
        scope_id = self.next_scope_id
        self.next_scope_id += 1
        return scope_id

    def visit_module(self, module: CheckModule, context: ScopeContext) -> None:
        current_declarations: list[VisibleDeclaration] = []
        ancestor_set = set(context.ancestors)
        for binder in module.binders:
            self.check_binder(binder, ancestor_set)
            declaration = VisibleDeclaration(binder.text, binder.position, context.scope_id)
            current_declarations.append(declaration)
            self.add_visible(declaration)
        child_context = ScopeContext(self.allocate_scope(), (*context.ancestors, context.scope_id))
        for statement in [*module.predicate_statements, *module.target_statements]:
            for submodule in statement.sub_modules:
                self.visit_module(submodule, child_context)
        for declaration in current_declarations:
            self.visible[declaration.name].remove(declaration)

    def check_binder(self, binder: Binder, ancestors: set[int]) -> None:
        if binder.text.startswith(FRESH_PREFIX):
            return
        conflicts = [
            conflict
            for conflict in self.visible.get(binder.text, [])
            if conflict.is_imported or conflict.scope_id in ancestors
        ]
        if not conflicts:
            return
        is_formal = self.is_function_declaration_formal(binder.position)
        message = format_conflict_message(binder.text, conflicts, formal=is_formal)
        self.diagnostics.append(
            Diagnostic(
                file=binder.position.file,
                lineno=max(binder.position.line - 1, 0),
                col_start_no=max(binder.position.column - 1, 0),
                col_end_no=max(binder.position.column - 1 + len(binder.text), 1),
                type="information" if is_formal else "warning",
                code="formal_name_override" if is_formal else "name_conflict",
                reason=message,
            )
        )

    def add_visible(self, declaration: VisibleDeclaration) -> None:
        self.visible.setdefault(declaration.name, []).append(declaration)

    def is_function_declaration_formal(self, position: SourcePosition) -> bool:
        try:
            line = self.line_text(position)
        except (OSError, IndexError, ValueError):
            return False
        return parse_declaration(line.strip()) is not None

    def line_text(self, position: SourcePosition) -> str:
        if position.file in self.source_lines_by_file:
            return self.source_lines_by_file[position.file][position.line - 1]
        lines = Path(position.file).read_text(encoding="utf-8").splitlines()
        self.source_lines_by_file[position.file] = lines
        return lines[position.line - 1]


def format_prior_location(position: SourcePosition) -> str:
    return f"{position.file}:{position.line}"


def format_conflict_message(name: str, conflicts: list[VisibleDeclaration], *, formal: bool) -> str:
    imported = dedupe_join([format_prior_location(conflict.position) for conflict in conflicts if conflict.is_imported])
    ancestors = dedupe_join([format_prior_location(conflict.position) for conflict in conflicts if not conflict.is_imported])
    locations: list[str] = []
    if imported:
        locations.append(f"imported declaration at {imported}")
    if ancestors:
        locations.append(f"outer declaration at {ancestors}")
    joined = " and ".join(locations)
    if formal:
        return (
            f"formal parameter '{name}' intentionally overrides {joined} "
            "due to the class-name-alias rule"
        )
    return f"declare-sym '{name}' conflicts with {joined}"


def dedupe_join(values: list[str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return ", ".join(output)


def collect_semantic_diagnostics_from_text(text: str) -> list[dict[str, object]]:
    result = analyze_module_text(text, file_path=None)
    diagnostics = SemanticChecker(
        result.import_declarations,
        source_text=result.source_text,
        source_file=result.file,
    ).check(result.ast)
    return [diagnostic.to_json() for diagnostic in diagnostics]


def collect_semantic_diagnostics_from_file(file_path: Path) -> list[dict[str, object]]:
    result = analyze_module_file(file_path)
    diagnostics = SemanticChecker(
        result.import_declarations,
        source_text=result.source_text,
        source_file=result.file,
    ).check(result.ast)
    return [diagnostic.to_json() for diagnostic in diagnostics]


def output_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
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
                str(entry.get("reason", "")),
            ),
        ),
    }


def load_syntax_payload(path: str | None) -> dict[str, Any]:
    if path is None:
        return {"summary": {"error_count": 0, "warning_count": 0}, "entries": []}
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(raw) if raw.strip() else {"summary": {"error_count": 0, "warning_count": 0}, "entries": []}


def merged_payload(file_path: Path, syntax_json: str | None) -> dict[str, Any]:
    syntax_payload = load_syntax_payload(syntax_json)
    syntax_entries = list(syntax_payload.get("entries", []))
    error_count = int(syntax_payload.get("summary", {}).get("error_count", 0) or 0)
    if error_count:
        return output_payload(syntax_entries)
    semantic_entries = collect_semantic_diagnostics_from_file(file_path)
    return output_payload([*syntax_entries, *semantic_entries])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic checks for logic-language module text.")
    parser.add_argument("file", nargs="?", help="module file path; stdin is used when omitted")
    parser.add_argument("--syntax-json", help="syntax_check.py JSON payload path, or '-' for stdin; skips semantic analysis when syntax has errors")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    try:
        if args.syntax_json is not None:
            if not args.file:
                raise ValueError("--syntax-json requires a file argument")
            payload = merged_payload(Path(args.file).resolve(), args.syntax_json)
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            return 1 if payload["summary"]["error_count"] else 0
        if args.file:
            diagnostics = collect_semantic_diagnostics_from_file(Path(args.file).resolve())
        else:
            diagnostics = collect_semantic_diagnostics_from_text(sys.stdin.read())
    except (CheckError, CompileError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    json.dump(diagnostics, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
