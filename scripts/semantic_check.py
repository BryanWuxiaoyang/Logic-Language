#!/usr/bin/env python3
"""Semantic diagnostics for logic-language module text."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import UNDECLARED_CLASS_MEMBER_OWNER_CODE, undeclared_class_member_owner_reason
from inheritance_sources import selected_inheritance_source
from syntax_check_common import (
    STDIN_FILE,
    Binder,
    CheckError,
    ClassMemberOwner,
    CheckModule,
    Declaration,
    SourcePosition,
    analyze_module_file,
    analyze_module_text,
)


BARE_INDEX_OPERATOR_WARNING_CODE = "bare_index_operator_symbol"
BARE_INDEX_OPERATOR_WARNING_REASON = "bare [] is the index operator symbol; use [,] for the empty tuple literal"
IMPLICIT_INHERITANCE_FALLBACK_CODE = "implicit_inheritance_fallback_symbol"
IMPLICIT_INHERITANCE_FALLBACK_REASON = "implicit inheritance did not find a declared class; symbol falls back to Symbol"


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
    visible_class_names: frozenset[str]


class SemanticChecker:
    def __init__(
        self,
        import_declarations: list[Declaration],
        *,
        import_class_declarations: list[Declaration] | None = None,
        source_text: str | None = None,
        source_file: str | None = None,
        class_member_owners: list[ClassMemberOwner] | None = None,
    ) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.visible: dict[str, list[VisibleDeclaration]] = {}
        self.next_scope_id = 0
        self.source_lines_by_file: dict[str, list[str]] = {}
        self.class_member_owners = class_member_owners or []
        self.fallback_warning_keys: set[tuple[str, int, int, str]] = set()
        self.import_class_names: set[str] = set()
        if source_text is not None and source_file is not None:
            self.source_lines_by_file[source_file] = source_text.splitlines()
        for declaration in import_declarations:
            self.add_visible(VisibleDeclaration(declaration.name, declaration.position, None))
        for declaration in import_class_declarations or []:
            self.import_class_names.add(declaration.name)

    def check(self, module: CheckModule) -> list[Diagnostic]:
        self.check_class_member_owners()
        self.visit_module(module, ScopeContext(self.allocate_scope(), tuple(), frozenset(self.import_class_names)))
        return sorted(self.diagnostics, key=lambda diagnostic: (diagnostic.file, diagnostic.lineno, diagnostic.col_start_no, diagnostic.reason))

    def allocate_scope(self) -> int:
        scope_id = self.next_scope_id
        self.next_scope_id += 1
        return scope_id

    def visit_module(self, module: CheckModule, context: ScopeContext) -> None:
        current_declarations: list[VisibleDeclaration] = []
        ancestor_set = set(context.ancestors)
        current_class_names = set(context.visible_class_names)
        for class_declaration in module.class_declarations:
            current_class_names.add(class_declaration.name)
            declaration = VisibleDeclaration(class_declaration.name, class_declaration.position, context.scope_id)
            current_declarations.append(declaration)
            self.add_visible(declaration)
        inherited_rhs = module_inheritance_rhs_names(module)
        for binder in module.binders:
            self.check_binder(binder, ancestor_set)
            self.check_bare_index_operator_binder(binder)
            self.check_implicit_inheritance_fallback(binder, current_class_names, inherited_rhs)
            declaration = VisibleDeclaration(binder.text, binder.position, context.scope_id)
            current_declarations.append(declaration)
            self.add_visible(declaration)
        self.check_bare_index_operator_statements(module)
        child_context = ScopeContext(self.allocate_scope(), (*context.ancestors, context.scope_id), frozenset(current_class_names))
        for statement in [*module.premise_binding_statements, *module.predicate_statements, *module.target_statements]:
            for submodule in statement.sub_modules:
                self.visit_module(submodule, child_context)
        for declaration in current_declarations:
            self.visible[declaration.name].remove(declaration)

    def check_binder(self, binder: Binder, ancestors: set[int]) -> None:
        if binder.text.startswith("^"):
            return
        conflicts = [
            conflict
            for conflict in self.visible.get(binder.text, [])
            if conflict.is_imported or conflict.scope_id in ancestors
            if not same_source_position(conflict.position, binder.position)
        ]
        if not conflicts:
            return
        message = format_conflict_message(binder.text, conflicts)
        self.diagnostics.append(
            Diagnostic(
                file=binder.position.file,
                lineno=max(binder.position.line - 1, 0),
                col_start_no=max(binder.position.column - 1, 0),
                col_end_no=max(binder.position.column - 1 + len(binder.text), 1),
                type="warning",
                code="name_override",
                reason=message,
            )
        )

    def add_visible(self, declaration: VisibleDeclaration) -> None:
        self.visible.setdefault(declaration.name, []).append(declaration)

    def check_class_member_owners(self) -> None:
        for owner in self.class_member_owners:
            if owner.declared:
                continue
            self.diagnostics.append(
                Diagnostic(
                    file=owner.position.file,
                    lineno=max(owner.position.line - 1, 0),
                    col_start_no=max(owner.position.column - 1, 0),
                    col_end_no=max(owner.position.column - 1 + len(owner.name), 1),
                    type="error",
                    code=UNDECLARED_CLASS_MEMBER_OWNER_CODE,
                    reason=undeclared_class_member_owner_reason(owner.name),
                )
            )

    def check_bare_index_operator_binder(self, binder: Binder) -> None:
        if binder.text != "[]":
            return
        self.emit_bare_index_operator_warning(binder.position, 2)

    def check_implicit_inheritance_fallback(self, binder: Binder, visible_class_names: set[str], inherited_rhs: set[str]) -> None:
        if binder.text.startswith("^") or binder.text in {"[]", "[:]"}:
            return
        if is_bool_implicit_sym(binder.text):
            return
        if selected_inheritance_source(binder.text, visible_class_names) is not None:
            return
        if collection_inheritance_exists(binder.text, visible_class_names):
            return
        if binder.text in inherited_rhs:
            return
        key = (binder.position.file, binder.position.line, binder.position.column, binder.text)
        if key in self.fallback_warning_keys:
            return
        self.fallback_warning_keys.add(key)
        self.diagnostics.append(
            Diagnostic(
                file=binder.position.file,
                lineno=max(binder.position.line - 1, 0),
                col_start_no=max(binder.position.column - 1, 0),
                col_end_no=max(binder.position.column - 1 + len(binder.text), 1),
                type="warning",
                code=IMPLICIT_INHERITANCE_FALLBACK_CODE,
                reason=IMPLICIT_INHERITANCE_FALLBACK_REASON,
            )
        )

    def check_bare_index_operator_statements(self, module: CheckModule) -> None:
        skip_operator_definition_body = module.declaration is not None and module.declaration.name == "[]"
        if skip_operator_definition_body:
            return
        for statement in [*module.premise_binding_statements, *module.predicate_statements, *module.target_statements]:
            if is_bare_index_operator_definition_fact(statement.text):
                continue
            for position, width in find_bare_index_operator_symbol_occurrences(statement):
                self.emit_bare_index_operator_warning(position, width)

    def emit_bare_index_operator_warning(self, position: SourcePosition, width: int) -> None:
        self.diagnostics.append(
            Diagnostic(
                file=position.file,
                lineno=max(position.line - 1, 0),
                col_start_no=max(position.column - 1, 0),
                col_end_no=max(position.column - 1 + width, 1),
                type="warning",
                code=BARE_INDEX_OPERATOR_WARNING_CODE,
                reason=BARE_INDEX_OPERATOR_WARNING_REASON,
            )
        )

    def line_text(self, position: SourcePosition) -> str:
        if position.file in self.source_lines_by_file:
            return self.source_lines_by_file[position.file][position.line - 1]
        lines = Path(position.file).read_text(encoding="utf-8").splitlines()
        self.source_lines_by_file[position.file] = lines
        return lines[position.line - 1]


def format_prior_location(position: SourcePosition) -> str:
    return f"{position.file}:{position.line}"


def same_source_position(left: SourcePosition, right: SourcePosition) -> bool:
    return left.file == right.file and left.line == right.line and left.column == right.column


def format_conflict_message(name: str, conflicts: list[VisibleDeclaration]) -> str:
    imported = dedupe_join([format_prior_location(conflict.position) for conflict in conflicts if conflict.is_imported])
    ancestors = dedupe_join([format_prior_location(conflict.position) for conflict in conflicts if not conflict.is_imported])
    locations: list[str] = []
    if imported:
        locations.append(f"imported declaration at {imported}")
    if ancestors:
        locations.append(f"outer declaration at {ancestors}")
    joined = " and ".join(locations)
    return f"declare-sym '{name}' overrides {joined}"


def dedupe_join(values: list[str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return ", ".join(output)


def module_inheritance_rhs_names(module: CheckModule) -> set[str]:
    names: set[str] = set()
    for statement in [*module.predicate_statements, *module.target_statements]:
        match = re.match(r"^\s*(?P<source>.+?)\s*~\s*(?P<target>[^\s,{}()]+)\s*$", statement.text)
        if match is not None:
            names.add(match.group("target"))
    return names


def is_bool_implicit_sym(sym: str) -> bool:
    if sym.startswith("^"):
        return False
    normalized = sym.lstrip("_").rstrip("'")
    normalized = re.sub(r"\d+$", "", normalized)
    return normalized.startswith("is_")


def collection_inheritance_exists(sym: str, visible_class_names: set[str]) -> bool:
    if sym.endswith("_list"):
        return selected_inheritance_source(sym[: -len("_list")], visible_class_names) is not None
    if sym.endswith("s") and len(sym) > 1:
        return selected_inheritance_source(sym[:-1], visible_class_names) is not None
    return False


def find_symbol_occurrence(statement: Any, symbol: str) -> tuple[SourcePosition, int] | None:
    pattern = re.compile(rf"(?<![\w^']){re.escape(symbol)}(?![\w'])")
    match = pattern.search(statement.text)
    if match is None:
        return None
    if statement.located is not None and match.start() < len(statement.located.positions):
        return statement.located.positions[match.start()], len(symbol)
    return SourcePosition(STDIN_FILE, 1, 1), len(symbol)


def find_bare_index_operator_symbol_occurrences(statement: Any) -> list[tuple[SourcePosition, int]]:
    occurrences: list[tuple[SourcePosition, int]] = []
    index = 0
    text = statement.text
    while True:
        index = text.find("[]", index)
        if index < 0:
            return occurrences
        if is_prefix_call_head(text, index):
            index += 2
            continue
        if statement.located is not None and index < len(statement.located.positions):
            position = statement.located.positions[index]
        else:
            position = SourcePosition(STDIN_FILE, 1, 1)
        occurrences.append((position, 2))
        index += 2


def is_prefix_call_head(text: str, index: int) -> bool:
    return index + 2 < len(text) and text[index + 2] == "("


def is_bare_index_operator_definition_fact(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return compact == "Function~[]"


def collect_semantic_diagnostics_from_text(
    text: str,
    *,
    file_path: Path | None = None,
    base_dir: Path | None = None,
) -> list[dict[str, object]]:
    result = analyze_module_text(text, file_path=file_path, base_dir=base_dir)
    diagnostics = SemanticChecker(
        result.import_declarations,
        import_class_declarations=result.import_class_declarations,
        source_text=result.source_text,
        source_file=result.file,
        class_member_owners=result.class_member_owners,
    ).check(result.ast)
    return [diagnostic.to_json() for diagnostic in diagnostics]


def collect_semantic_diagnostics_from_file(file_path: Path) -> list[dict[str, object]]:
    result = analyze_module_file(file_path)
    diagnostics = SemanticChecker(
        result.import_declarations,
        import_class_declarations=result.import_class_declarations,
        source_text=result.source_text,
        source_file=result.file,
        class_member_owners=result.class_member_owners,
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
