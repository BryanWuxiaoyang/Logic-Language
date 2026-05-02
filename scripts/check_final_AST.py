#!/usr/bin/env python3
"""Validate final module_AST JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

    def check(self, ast: AstNode) -> list[dict[str, object]]:
        self.visit_stmt(require_node(ast, "root"), tuple())
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

    def visit_stmt(self, node: AstNode, ancestor_names: tuple[str, ...]) -> None:
        kind = require_kind(node)
        if kind in {"quantified_stmt", "set_stmt"}:
            self.visit_module(node, ancestor_names)
            return
        if kind == "binding_stmt":
            self.visit_stmt(require_node(node.get("src_stmt"), "binding_stmt.src_stmt"), ancestor_names)
            return
        if kind == "func_stmt" or kind == "sym":
            return
        if kind in {"char_literal_stmt", "str_literal_stmt", "value_literal_stmt"}:
            return
        if kind in {"tuple_literal_stmt", "set_literal_stmt"}:
            for item in require_list(node, "item_stmts"):
                self.visit_stmt(require_node(item, f"{kind}.item_stmts item"), ancestor_names)
            return
        raise AstCheckError(f"unsupported AST node kind: {kind}")

    def visit_module(self, node: AstNode, ancestor_names: tuple[str, ...]) -> None:
        current_names: set[str] = set()
        raw_names: list[str] = []
        for sym in require_list(node, "bound_syms"):
            sym_node = require_node(sym, "bound_syms item")
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
        for field in ("premise_binding_stmts", "premise_PSs", "target_PSs"):
            for stmt in require_list(node, field):
                self.visit_stmt(require_node(stmt, f"{require_kind(node)}.{field} item"), child_ancestors)

    def check_bound_sym(self, sym_node: AstNode, owner_stmt: AstNode) -> str | None:
        if sym_node.get("kind") != "sym":
            raise AstCheckError("bound_syms item must be a sym node")
        name = sym_node.get("name")
        if not isinstance(name, str) or not name:
            self.emit_invalid_name(sym_node, owner_stmt, name)
            return None
        if is_valid_bound_sym_name(name):
            return name
        self.emit_invalid_name(sym_node, owner_stmt, name)
        return name

    def emit_invalid_name(self, sym_node: AstNode, owner_stmt: AstNode, name: object) -> None:
        self.diagnostics.append(
            make_diagnostic(
                sym_node,
                owner_stmt,
                code="invalid_bound_sym_name",
                reason=f"bound-sym name {name!r} is invalid",
            )
        )

    def emit_conflict(self, sym_node: AstNode, owner_stmt: AstNode, name: str, detail: str) -> None:
        self.diagnostics.append(
            make_diagnostic(
                sym_node,
                owner_stmt,
                code="bound_sym_name_conflict",
                reason=f"bound-sym name {name!r} {detail}",
            )
        )


def is_valid_bound_sym_name(name: str) -> bool:
    if name.isidentifier():
        return True
    return len(name) == 1 and not name[0].isspace() and not name[0].isdigit()


def make_diagnostic(sym_node: AstNode, owner_stmt: AstNode, *, code: str, reason: str) -> Diagnostic:
    loc = choose_loc(sym_node, owner_stmt)
    source = loc.get("source", "<ast>")
    line = safe_int(loc.get("line"), 1)
    column = safe_int(loc.get("column"), 1)
    end_column = safe_int(loc.get("end_column"), column + max(len(str(sym_node.get("name", ""))), 1) - 1)
    return Diagnostic(
        file=str(source),
        lineno=max(line - 1, 0),
        col_start_no=max(column - 1, 0),
        col_end_no=max(end_column, column) - 1,
        type="error",
        code=code,
        reason=reason,
    )


def choose_loc(sym_node: AstNode, owner_stmt: AstNode) -> AstNode:
    loc = sym_node.get("loc")
    if isinstance(loc, dict):
        return loc
    loc = owner_stmt.get("loc")
    if isinstance(loc, dict):
        return loc
    return {"source": "<ast>", "line": 1, "column": 1, "end_column": 1}


def safe_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default


def require_kind(node: AstNode) -> str:
    kind = node.get("kind")
    if not isinstance(kind, str) or not kind:
        raise AstCheckError("AST node requires non-empty string field 'kind'")
    return kind


def require_node(value: Any, label: str) -> AstNode:
    if not isinstance(value, dict):
        raise AstCheckError(f"{label} must be an object")
    return value


def require_list(node: AstNode, field: str) -> list[Any]:
    value = node.get(field)
    if not isinstance(value, list):
        raise AstCheckError(f"{require_kind(node)}.{field} must be a list")
    return value


def load_ast(path: Path | None) -> AstNode:
    try:
        text = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        return require_node(json.loads(text), "root JSON")
    except json.JSONDecodeError as error:
        raise AstCheckError(f"invalid JSON: {error}") from error
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
