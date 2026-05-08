#!/usr/bin/env python3
"""Validate final module_AST JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from AST import (
    Binding_stmt,
    Func_stmt,
    Literal_stmt,
    Module_stmt,
    Set_literal_stmt,
    Stmt,
    Sym,
    Tuple_literal_stmt,
    object_ast_from_json,
)

AstNode = dict[str, Any]


class AstCheckError(Exception):
    """Raised when AST JSON cannot be loaded or traversed."""


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


class FinalAstChecker:
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    def check(self, ast: AstNode | Stmt) -> list[dict[str, object]]:
        root = object_ast_from_json(ast) if isinstance(ast, dict) else ast
        self.visit_stmt(root, tuple(), binding_allowed=False)
        diagnostics = sorted(
            self.diagnostics,
            key=lambda diagnostic: (
                diagnostic.file,
                diagnostic.lineno,
                diagnostic.col_start_no,
                diagnostic.reason,
            ),
        )
        return [diagnostic.to_json() for diagnostic in diagnostics]

    def visit_stmt(self, node: Stmt, ancestor_names: tuple[str, ...], *, binding_allowed: bool) -> None:
        if isinstance(node, Module_stmt):
            self.visit_module(node, ancestor_names)
            return
        if isinstance(node, Binding_stmt):
            if not binding_allowed:
                self.emit_invalid_binding_location(node)
            self.visit_stmt(node.src_stmt, ancestor_names, binding_allowed=False)
            return
        if isinstance(node, (Func_stmt, Sym)):
            return
        if isinstance(node, Literal_stmt) and not isinstance(node, (Tuple_literal_stmt, Set_literal_stmt)):
            return
        if isinstance(node, (Tuple_literal_stmt, Set_literal_stmt)):
            for item in node.item_stmts:
                self.visit_stmt(item, ancestor_names, binding_allowed=False)
            return
        raise AstCheckError(f"unsupported AST node class: {type(node).__name__}")

    def visit_module(self, node: Module_stmt, ancestor_names: tuple[str, ...]) -> None:
        current_names: set[str] = set()
        raw_names: list[str] = []
        for sym_node in node.bound_syms:
            raw_name = self.check_bound_sym(sym_node, node)
            if raw_name is None:
                continue
            if raw_name in current_names:
                self.emit_conflict(sym_node, node, raw_name, "duplicate in current statement")
            elif raw_name in ancestor_names:
                self.emit_conflict(sym_node, node, raw_name, "conflicts with ancestor statement")
            current_names.add(raw_name)
            raw_names.append(raw_name)

        child_ancestors = (*ancestor_names, *raw_names)
        for stmt in node.premise_binding_stmts:
            self.visit_stmt(stmt, child_ancestors, binding_allowed=True)
        for stmt in node.premise_proposition_stmts:
            self.visit_stmt(stmt, child_ancestors, binding_allowed=False)
        for stmt in node.target_proposition_stmts:
            self.visit_stmt(stmt, child_ancestors, binding_allowed=False)

    def check_bound_sym(self, sym_node: Sym, owner_stmt: Module_stmt) -> str | None:
        name = sym_node.name
        if not name:
            self.emit_invalid_name(sym_node, owner_stmt, name)
            return None
        if is_valid_bound_sym_name(name):
            return name
        self.emit_invalid_name(sym_node, owner_stmt, name)
        return name

    def emit_invalid_name(self, sym_node: Sym, owner_stmt: Module_stmt, name: object) -> None:
        self.diagnostics.append(
            make_diagnostic(
                sym_node,
                owner_stmt,
                code="invalid_bound_sym_name",
                reason=f"bound-sym name {name!r} is invalid",
            )
        )

    def emit_conflict(self, sym_node: Sym, owner_stmt: Module_stmt, name: str, detail: str) -> None:
        self.diagnostics.append(
            make_diagnostic(
                sym_node,
                owner_stmt,
                code="bound_sym_name_conflict",
                reason=f"bound-sym name {name!r} {detail}",
            )
        )

    def emit_invalid_binding_location(self, binding_node: Binding_stmt) -> None:
        self.diagnostics.append(
            make_diagnostic(
                binding_node,
                binding_node,
                code="invalid_binding_stmt_location",
                reason="binding_stmt is only valid in premise_binding_stmts",
            )
        )


def is_valid_bound_sym_name(name: str) -> bool:
    if "^" in name:
        if not name.startswith("^") or name == "^":
            return False
        base = name[1:]
        if not base or "^" in base:
            return False
        return is_valid_ordinary_bound_sym_name(base)
    return is_valid_ordinary_bound_sym_name(name)


def is_valid_ordinary_bound_sym_name(name: str) -> bool:
    if name in {"[:]", "[]"}:
        return True
    if name.isidentifier():
        return True
    base = name.rstrip("'")
    if base and len(base) < len(name) and base.isidentifier():
        return True
    return len(name) == 1 and not name[0].isspace() and not name[0].isdigit() and name not in {"'", '"', "^"}


def make_diagnostic(sym_node: Stmt | Sym, owner_stmt: Stmt | Sym, *, code: str, reason: str) -> Diagnostic:
    loc = choose_loc(sym_node, owner_stmt)
    source = loc.file_path
    line = loc.line
    column = loc.column
    end_column = loc.end_column
    return Diagnostic(
        file=str(source),
        lineno=max(line - 1, 0),
        col_start_no=max(column - 1, 0),
        col_end_no=max(end_column, column) - 1,
        type="error",
        code=code,
        reason=reason,
    )


def choose_loc(sym_node: Stmt | Sym, owner_stmt: Stmt | Sym):
    return getattr(sym_node, "source_loc", None) or getattr(owner_stmt, "source_loc", None)


def require_node(value: Any, label: str) -> AstNode:
    if not isinstance(value, dict):
        raise AstCheckError(f"{label} must be an object")
    return value


def load_ast(path: Path | None) -> AstNode:
    try:
        text = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        return object_ast_from_json(require_node(json.loads(text), "root JSON")).to_json()
    except json.JSONDecodeError as error:
        raise AstCheckError(f"invalid JSON: {error}") from error
    except ValueError as error:
        raise AstCheckError(str(error)) from error
    except OSError as error:
        raise AstCheckError(str(error)) from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Check final module_AST JSON validity.")
    parser.add_argument("file", nargs="?", type=Path, help="AST JSON file; defaults to stdin")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()
    try:
        diagnostics = FinalAstChecker().check(load_ast(args.file))
    except AstCheckError as error:
        print(error, file=sys.stderr)
        return 1
    json.dump(diagnostics, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
