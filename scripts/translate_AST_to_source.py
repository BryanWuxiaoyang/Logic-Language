#!/usr/bin/env python3
"""Translate semantic object AST JSON back to canonical module source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from AST import (
    Binding_stmt,
    Char_literal_stmt,
    Func_stmt,
    Module_stmt,
    Quantified_stmt,
    Set_literal_stmt,
    Set_stmt,
    Stmt,
    Str_literal_stmt,
    Sym,
    Tuple_literal_stmt,
    Value_literal_stmt,
    object_ast_from_json,
)


class TranslateError(Exception):
    """Raised when an AST cannot be represented as source text."""


BINARY_OPERATORS = {
    "=": "=",
    "~": "~",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "&&": "&&",
    "||": "||",
    "!=": "≠",
    "≠": "≠",
    ">=": "≥",
    "≥": "≥",
    "<=": "≤",
    "≤": "≤",
    ">": ">",
    "<": "<",
    "∈": "∈",
    "∉": "∉",
    "⊂": "⊂",
    "⊄": "⊄",
    "⊆": "⊆",
    "⊈": "⊈",
}


def translate_ast_to_source(ast: dict[str, Any] | Stmt) -> str:
    root = object_ast_from_json(ast) if isinstance(ast, dict) else ast
    text = Renderer().render_stmt(root)
    return text.rstrip() + "\n"


class Renderer:
    def __init__(self) -> None:
        self.bound_scopes: list[set[str]] = []

    def render_stmt(self, node: Stmt) -> str:
        return "\n".join(self.render_lines(node, 0))

    def render_lines(self, node: Stmt, indent: int) -> list[str]:
        if isinstance(node, Module_stmt):
            return self.render_module(node, indent)
        if isinstance(node, Binding_stmt):
            return self.render_binding_lines(node, indent)
        if isinstance(node, Func_stmt):
            return [self.indent(indent) + self.render_func(node)]
        if isinstance(node, Sym):
            return [self.indent(indent) + self.render_sym(node)]
        if isinstance(node, (Char_literal_stmt, Str_literal_stmt, Value_literal_stmt, Tuple_literal_stmt, Set_literal_stmt)):
            return [self.indent(indent) + self.render_literal(node)]
        raise TranslateError(f"unsupported AST node class: {type(node).__name__}")

    def render_module(self, node: Module_stmt, indent: int) -> list[str]:
        if not node.target_proposition_stmts:
            raise TranslateError(f"{type(node).__name__} requires at least one target_proposition_stmts item")

        local_bound_names = {sym.name for sym in node.bound_syms}
        binders = ", ".join(self.render_bound_sym(sym) for sym in node.bound_syms)
        premise_nodes: list[Stmt] = [*node.premise_binding_stmts, *node.premise_proposition_stmts]
        target_nodes: list[Stmt] = [*node.target_proposition_stmts]

        lines = [self.indent(indent) + self.module_opener(node)]
        self.bound_scopes.append(local_bound_names)
        try:
            if binders:
                lines.append(self.indent(indent + 1) + "| " + binders)
            if premise_nodes:
                lines.extend(self.section_lines(premise_nodes, indent=indent + 1, item_prefix="| "))
            lines.extend(self.section_lines(target_nodes, indent=indent + 1, item_prefix=""))
            lines.append(self.indent(indent) + "}")
            return lines
        finally:
            self.bound_scopes.pop()

    def module_opener(self, node: Module_stmt) -> str:
        if isinstance(node, Set_stmt):
            return "{"
        if isinstance(node, Quantified_stmt):
            return f"{node.quantifier_sym.name or '∀'}{{"
        raise TranslateError(f"unsupported module node class: {type(node).__name__}")

    def section_lines(self, items: list[Stmt], *, indent: int, item_prefix: str) -> list[str]:
        lines: list[str] = []
        for item in items:
            item_lines = self.render_lines(item, indent)
            if not item_lines:
                continue
            first_line = item_lines[0]
            prefix_base = self.indent(indent)
            if not first_line.startswith(prefix_base):
                raise TranslateError("rendered item did not preserve requested indentation")
            lines.append(prefix_base + item_prefix + first_line[len(prefix_base):])
            lines.extend(item_lines[1:])
        return lines

    def indent(self, depth: int) -> str:
        return "  " * depth

    def render_binding_lines(self, node: Binding_stmt, indent: int) -> list[str]:
        dst = self.render_sym(node.dst_sym)
        src_lines = self.render_lines(node.src_stmt, indent)
        if not src_lines:
            raise TranslateError("binding_stmt.src_stmt rendered no lines")
        prefix = self.indent(indent)
        first_src = src_lines[0]
        if not first_src.startswith(prefix):
            raise TranslateError("binding_stmt.src_stmt did not preserve requested indentation")
        lines = [prefix + f"{dst} = " + first_src[len(prefix):]]
        lines.extend(src_lines[1:])
        return lines

    def render_func(self, node: Func_stmt) -> str:
        call_name = node.call_sym.name
        rendered_args = [self.render_sym(arg) for arg in node.arg_sym_list]
        if call_name == "[]":
            if len(rendered_args) != 2:
                raise TranslateError("index Func_stmt [] requires exactly two arguments")
            return f"{rendered_args[0]}[{rendered_args[1]}]"
        if call_name in BINARY_OPERATORS and len(rendered_args) == 2:
            return f"{rendered_args[0]} {BINARY_OPERATORS[call_name]} {rendered_args[1]}"
        return f"{self.render_sym(node.call_sym)}({', '.join(rendered_args)})"

    def render_literal(self, node: Stmt) -> str:
        if isinstance(node, Char_literal_stmt):
            if len(node.value) != 1:
                raise TranslateError("Char_literal_stmt.value must contain exactly one character")
            return quote_literal(node.value, "'")
        if isinstance(node, Str_literal_stmt):
            return quote_literal(node.value, '"')
        if isinstance(node, Value_literal_stmt):
            return str(node.value)
        if isinstance(node, Tuple_literal_stmt):
            items = [self.render_stmt(item) for item in node.item_stmts]
            if len(items) == 1:
                return f"({items[0]},)"
            return "(" + ", ".join(items) + ")"
        if isinstance(node, Set_literal_stmt):
            items = [self.render_stmt(item) for item in node.item_stmts]
            return "{" + ", ".join(items) + "}"
        raise TranslateError(f"unsupported literal node class: {type(node).__name__}")

    def render_sym(self, node: Sym) -> str:
        if self.is_lexically_bound(node.name):
            return generated_source_name(node.name)
        return node.name

    def render_bound_sym(self, node: Sym) -> str:
        return generated_source_name(node.name)

    def is_lexically_bound(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self.bound_scopes))


def generated_source_name(name: str) -> str:
    return name if name.startswith("^") else "^" + name


def quote_literal(value: str, quote: str) -> str:
    escapes = {
        "\\": "\\\\",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        '"': '\\"',
        "'": "\\'",
    }
    body = "".join(escapes.get(char, char) for char in value)
    return quote + body + quote


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate semantic object AST JSON to logic-language source.")
    parser.add_argument("file", nargs="?", type=Path, help="AST JSON file; defaults to stdin")
    args = parser.parse_args()
    try:
        text = args.file.read_text(encoding="utf-8") if args.file is not None else sys.stdin.read()
        source = translate_ast_to_source(json.loads(text))
    except (OSError, json.JSONDecodeError, ValueError, TranslateError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
