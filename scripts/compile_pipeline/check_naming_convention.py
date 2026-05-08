#!/usr/bin/env python3
"""Naming-convention diagnostics for logic-language source ASTs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import Call_expr, Module, SourceFileAst, SourceLoc, Statement, Sym_expr
from compile_pipeline.source_syntax import is_generated_sym_name, is_plain_sym


SPECIAL_CALLABLE_NAMES = {"-", "+", "*", "/", "=", "~", "!=", "?", "<=", "?", ">=", "?", "<", ">", "?", "?", "?", "?", "?", "?", "?", "?", "[]", "[:]"}
LOWER_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*'*$")


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


class NamingConventionChecker:
    def __init__(self, ast: SourceFileAst) -> None:
        self.ast = ast
        self.diagnostics: list[Diagnostic] = []
        self.diagnostic_keys: set[tuple[str, int, int, str, str]] = set()
        self.roles: dict[str, set[str]] = {}
        self.role_locs: dict[tuple[str, str], tuple[int, int]] = {}

    def check(self) -> list[dict[str, object]]:
        for module in self.ast.modules:
            lowered = getattr(module, "lowered_module", None)
            if isinstance(lowered, Module):
                self.check_module(lowered)
        self.check_role_conflicts()
        return [diagnostic.to_json() for diagnostic in sorted(self.diagnostics, key=diagnostic_key)]

    def check_module(self, module: Module) -> None:
        for class_name in module.declared_classes:
            self.record_role(class_name, "class")
            if not is_class_name(class_name):
                self.emit(class_name, "invalid_class_name", f"class symbol {class_name!r} must be capital-head")

        for bound_sym in module.syms:
            self.record_role(bound_sym, "bound")
            if not is_exempt_bound_sym(bound_sym) and not bound_sym.startswith("_"):
                self.emit(bound_sym, "invalid_bound_sym_name", f"bound-sym {bound_sym!r} must start with '_'")

        local_bound = set(module.syms)
        for statement in [*module.predicate_statements, *module.target_statements]:
            self.check_statement(statement, set(module.declared_classes), local_bound)

    def check_statement(self, statement: Statement, declared_classes: set[str], local_bound: set[str]) -> None:
        for classifier, name, premise in classifier_facts(statement):
            if premise or name in declared_classes or name in local_bound:
                continue
            if classifier in {"Function", "Predicate"}:
                self.record_role(name, "function")
                if not is_exempt_callable_name(name) and not is_lower_snake_name(name):
                    self.emit(name, "invalid_function_name", f"function symbol {name!r} must be lower snake case and must not start with '_'")
        for submodule in statement.sub_modules:
            self.check_module(submodule)

    def record_role(self, name: str, role: str) -> None:
        if not should_track_role_name(name):
            return
        self.roles.setdefault(name, set()).add(role)
        self.role_locs.setdefault((name, role), self.find_name_position(name))

    def check_role_conflicts(self) -> None:
        for name, roles in sorted(self.roles.items()):
            if len(roles) < 2:
                continue
            if roles <= {"function"} or roles <= {"class"} or roles <= {"bound"}:
                continue
            line, column = min(self.role_locs.get((name, role), (0, 0)) for role in roles)
            self.emit_at(
                name,
                line,
                column,
                "symbol_role_conflict",
                f"symbol {name!r} has conflicting roles: {', '.join(sorted(roles))}",
            )

    def emit(self, name: str, code: str, reason: str) -> None:
        line, column = self.find_name_position(name)
        self.emit_at(name, line, column, code, reason)

    def emit_at(self, name: str, line: int, column: int, code: str, reason: str) -> None:
        key = (self.ast.source, line, column, code, reason)
        if key in self.diagnostic_keys:
            return
        self.diagnostic_keys.add(key)
        self.diagnostics.append(
            Diagnostic(
                file=self.ast.source,
                lineno=line,
                col_start_no=column,
                col_end_no=max(column + len(name), column + 1),
                type="error",
                code=code,
                reason=reason,
            )
        )

    def find_name_position(self, name: str) -> tuple[int, int]:
        for module in self.ast.modules:
            lowered = getattr(module, "lowered_module", None)
            if isinstance(lowered, Module):
                loc = find_sym_loc_in_module(lowered, name)
                if loc is not None:
                    return loc_position(loc)
        loc = self.ast.source_loc
        return loc_position(loc)


def check_naming_convention(ast: SourceFileAst) -> list[dict[str, object]]:
    return NamingConventionChecker(ast).check()


def classifier_facts(statement: Statement) -> Iterable[tuple[str, str, bool]]:
    expr = statement.expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None or expr.call_sym.name != "~" or len(expr.args) != 2:
        return []
    lhs, rhs = expr.args
    if isinstance(lhs, Sym_expr) and lhs.sym is not None and isinstance(rhs, Sym_expr) and rhs.sym is not None:
        return [(lhs.sym.name, rhs.sym.name, False)]
    return []


def find_sym_loc_in_module(module: Module, name: str) -> SourceLoc | dict[str, Any] | None:
    for index, sym in enumerate(module.syms):
        if sym == name and index < len(module.bound_sym_locs):
            return module.bound_sym_locs[index]
    for statement in [*module.predicate_statements, *module.target_statements]:
        if name in statement.sym_locs:
            return statement.sym_locs[name]
        for submodule in statement.sub_modules:
            loc = find_sym_loc_in_module(submodule, name)
            if loc is not None:
                return loc
    return None


def is_class_name(name: str) -> bool:
    return bool(name) and name[0].isalpha() and name[0].isupper()


def is_lower_snake_name(name: str) -> bool:
    return bool(LOWER_SNAKE_RE.fullmatch(name)) and not name.startswith("_")


def is_exempt_callable_name(name: str) -> bool:
    return name in SPECIAL_CALLABLE_NAMES or is_generated_sym_name(name) or not is_identifier_like_name(name)


def is_exempt_bound_sym(name: str) -> bool:
    return is_generated_sym_name(name) or name in {"[]", "[:]"}


def should_track_role_name(name: str) -> bool:
    return bool(name) and is_plain_sym(name) and not is_generated_sym_name(name) and name not in SPECIAL_CALLABLE_NAMES


def is_identifier_like_name(name: str) -> bool:
    return re.fullmatch(r"[^\W\d]\w*'*", name, flags=re.UNICODE) is not None


def loc_position(loc: SourceLoc | dict[str, Any] | None) -> tuple[int, int]:
    if loc is None:
        return 0, 0
    if isinstance(loc, SourceLoc):
        return max(loc.line - 1, 0), max(loc.column - 1, 0)
    return max(int(loc.get("line", 1)) - 1, 0), max(int(loc.get("column", 1)) - 1, 0)


def diagnostic_key(diagnostic: Diagnostic) -> tuple[str, int, int, str]:
    return (diagnostic.file, diagnostic.lineno, diagnostic.col_start_no, diagnostic.reason)


def output_payload(entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "summary": {
            "error_count": sum(1 for entry in entries if entry.get("type") == "error"),
            "warning_count": sum(1 for entry in entries if entry.get("type") == "warning"),
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check logic-language naming conventions.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    from compile_pipeline.front_end_source_loader import run as normalize_source
    from compile_pipeline.front_end_desugar import run as desugar_source

    if args.text is not None:
        source = args.text
        source_name = "__stdin__"
        allow_imports = False
    elif args.file is not None:
        source = args.file.read_text(encoding="utf-8")
        source_name = str(args.file.resolve())
        allow_imports = True
    else:
        source = sys.stdin.read()
        source_name = "__stdin__"
        allow_imports = False
    source_ast = normalize_source(source, args.base_dir, source=source_name, allow_imports=allow_imports)
    desugared = desugar_source(source_ast, args.base_dir)
    payload = output_payload(desugared.diagnostics)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 1 if payload["summary"]["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
