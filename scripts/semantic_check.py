#!/usr/bin/env python3
"""Semantic diagnostics for logic-language module text."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from compile_module_text import INTRINSIC_SYMS, CompileError
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
    line: int
    column: int
    severity: str
    source: str
    message: str

    def to_json(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
            "source": self.source,
            "message": self.message,
        }


@dataclass(frozen=True)
class VisibleDeclaration:
    name: str
    position: SourcePosition
    scope_id: int | None
    intrinsic: bool = False

    def kinds_for_scope(self, current_scope_id: int, ancestors: set[int]) -> set[str]:
        kinds: set[str] = set()
        if self.intrinsic:
            kinds.add("intrinsic")
        if self.position.import_origin:
            kinds.add("import-origin")
        if self.scope_id == current_scope_id:
            kinds.add("same-scope")
        elif self.scope_id in ancestors:
            kinds.add("ancestor")
        return kinds or {"same-scope"}


@dataclass
class ScopeContext:
    scope_id: int
    ancestors: tuple[int, ...]


class SemanticChecker:
    def __init__(self, import_declarations: list[Declaration]) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.visible: dict[str, list[VisibleDeclaration]] = {}
        self.next_scope_id = 0
        for sym in sorted(INTRINSIC_SYMS):
            self.add_visible(VisibleDeclaration(sym, SourcePosition("<intrinsic>", 1, 1), None, intrinsic=True))
        for declaration in import_declarations:
            self.add_visible(VisibleDeclaration(declaration.name, declaration.position, None))

    def check(self, module: CheckModule) -> list[Diagnostic]:
        self.visit_module(module, ScopeContext(self.allocate_scope(), tuple()))
        return sorted(self.diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.column, diagnostic.message))

    def allocate_scope(self) -> int:
        scope_id = self.next_scope_id
        self.next_scope_id += 1
        return scope_id

    def visit_module(self, module: CheckModule, context: ScopeContext) -> None:
        current_declarations: list[VisibleDeclaration] = []
        ancestor_set = set(context.ancestors)
        for binder in module.binders:
            self.check_binder(binder, context.scope_id, ancestor_set)
            declaration = VisibleDeclaration(binder.text, binder.position, context.scope_id)
            current_declarations.append(declaration)
            self.add_visible(declaration)
        child_context = ScopeContext(self.allocate_scope(), (*context.ancestors, context.scope_id))
        for statement in [*module.predicate_statements, *module.target_statements]:
            for submodule in statement.sub_modules:
                self.visit_module(submodule, child_context)
        for declaration in current_declarations:
            self.visible[declaration.name].remove(declaration)

    def check_binder(self, binder: Binder, current_scope_id: int, ancestors: set[int]) -> None:
        conflicts = self.visible.get(binder.text, [])
        if not conflicts:
            return
        kinds: set[str] = set()
        prior_locations: list[str] = []
        for conflict in conflicts:
            kinds.update(conflict.kinds_for_scope(current_scope_id, ancestors))
            prior_locations.append(format_prior_location(conflict.position))
        message = (
            f"declare-sym '{binder.text}' has name collision "
            f"({', '.join(sorted(kinds))}); previous declaration at {dedupe_join(prior_locations)}"
        )
        self.diagnostics.append(
            Diagnostic(
                file=binder.position.file,
                line=binder.position.line,
                column=binder.position.column,
                severity="warning",
                source="semantic",
                message=message,
            )
        )

    def add_visible(self, declaration: VisibleDeclaration) -> None:
        self.visible.setdefault(declaration.name, []).append(declaration)


def format_prior_location(position: SourcePosition) -> str:
    if position.file == "<intrinsic>":
        return "<intrinsic>"
    return f"{position.file}:{position.line}"


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
    diagnostics = SemanticChecker(result.import_declarations).check(result.ast)
    return [diagnostic.to_json() for diagnostic in diagnostics]


def collect_semantic_diagnostics_from_file(file_path: Path) -> list[dict[str, object]]:
    result = analyze_module_file(file_path)
    diagnostics = SemanticChecker(result.import_declarations).check(result.ast)
    return [diagnostic.to_json() for diagnostic in diagnostics]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic checks for logic-language module text.")
    parser.add_argument("file", nargs="?", help="module file path; stdin is used when omitted")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    try:
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

