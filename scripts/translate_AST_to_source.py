#!/usr/bin/env python3
"""Translate module_AST JSON back to canonical logic-language source text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


AstNode = dict[str, Any]


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


def translate_ast_to_source(ast: AstNode) -> str:
    text = Renderer().render_stmt(require_node(ast, "root"))
    return text.rstrip() + "\n"


class Renderer:
    def render_stmt(self, node: AstNode) -> str:
        return "\n".join(self.render_lines(node, 0))

    def render_lines(self, node: AstNode, indent: int) -> list[str]:
        kind = require_kind(node)
        if kind in {"quantified_stmt", "set_stmt"}:
            return self.render_module(node, indent)
        if kind == "binding_stmt":
            return self.render_binding_lines(node, indent)
        if kind == "func_stmt":
            return [self.indent(indent) + self.render_func(node)]
        if kind == "sym":
            return [self.indent(indent) + self.render_sym(node)]
        if kind.endswith("_literal_stmt"):
            return [self.indent(indent) + self.render_literal(node)]
        raise TranslateError(f"unsupported AST node kind: {kind}")

    def render_module(self, node: AstNode, indent: int) -> list[str]:
        kind = require_kind(node)
        bound_syms = require_list(node, "bound_syms")
        premise_bindings = require_list(node, "premise_binding_stmts")
        premise_pss = require_list(node, "premise_PSs")
        target_pss = require_list(node, "target_PSs")
        if not target_pss:
            raise TranslateError(f"{kind} requires at least one target_PSs item")

        binders = ", ".join(self.render_sym(require_sym(sym, "bound_syms item")) for sym in bound_syms)
        premise_nodes = [require_node(stmt, "premise_binding_stmts item") for stmt in premise_bindings]
        premise_nodes.extend(require_node(stmt, "premise_PSs item") for stmt in premise_pss)
        target_nodes = [require_node(stmt, "target_PSs item") for stmt in target_pss]

        lines = [self.indent(indent) + self.module_opener(node)]
        if binders:
            lines.append(self.indent(indent + 1) + "| " + binders)
        if premise_nodes:
            lines.extend(self.section_lines(premise_nodes, indent=indent + 1, item_prefix="| "))
        lines.extend(self.section_lines(target_nodes, indent=indent + 1, item_prefix=""))
        lines.append(self.indent(indent) + "}")
        return lines

    def module_opener(self, node: AstNode) -> str:
        kind = require_kind(node)
        if kind == "set_stmt":
            return "{"
        quantifier = node.get("quantifier_sym", {}).get("name", "∀")
        if not isinstance(quantifier, str) or not quantifier:
            raise TranslateError("quantified_stmt.quantifier_sym.name must be a non-empty string when present")
        return f"{quantifier}{{"

    def section_lines(self, items: list[AstNode], *, indent: int, item_prefix: str) -> list[str]:
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

    def render_binding_lines(self, node: AstNode, indent: int) -> list[str]:
        dst = self.render_sym(require_sym(node.get("dst_sym"), "binding_stmt.dst_sym"))
        src_node = require_node(node.get("src_stmt"), "binding_stmt.src_stmt")
        src_lines = self.render_lines(src_node, indent)
        if not src_lines:
            raise TranslateError("binding_stmt.src_stmt rendered no lines")
        prefix = self.indent(indent)
        first_src = src_lines[0]
        if not first_src.startswith(prefix):
            raise TranslateError("binding_stmt.src_stmt did not preserve requested indentation")
        lines = [prefix + f"{dst} = " + first_src[len(prefix):]]
        lines.extend(src_lines[1:])
        return lines

    def render_func(self, node: AstNode) -> str:
        call_sym = require_sym(node.get("call_sym"), "func_stmt.call_sym")
        call_name = call_sym["name"]
        args = [require_sym(arg, "func_stmt.arg_sym_list item") for arg in require_list(node, "arg_sym_list")]
        rendered_args = [self.render_sym(arg) for arg in args]
        if call_name == "[]":
            if len(rendered_args) != 2:
                raise TranslateError("index func_stmt [] requires exactly two arguments")
            return f"{rendered_args[0]}[{rendered_args[1]}]"
        if call_name in BINARY_OPERATORS and len(rendered_args) == 2:
            return f"{rendered_args[0]} {BINARY_OPERATORS[call_name]} {rendered_args[1]}"
        return f"{call_name}({', '.join(rendered_args)})"

    def render_literal(self, node: AstNode) -> str:
        kind = require_kind(node)
        if kind == "char_literal_stmt":
            value = require_scalar_value(node, "char_literal_stmt.value")
            if len(value) != 1:
                raise TranslateError("char_literal_stmt.value must contain exactly one character")
            return quote_literal(value, "'")
        if kind == "str_literal_stmt":
            return quote_literal(require_scalar_value(node, "str_literal_stmt.value"), '"')
        if kind == "value_literal_stmt":
            return str(node.get("value", ""))
        if kind == "tuple_literal_stmt":
            items = [self.render_stmt(require_node(item, "tuple_literal_stmt.item_stmts item")) for item in require_list(node, "item_stmts")]
            if len(items) == 1:
                return f"({items[0]},)"
            return "(" + ", ".join(items) + ")"
        if kind == "set_literal_stmt":
            items = [self.render_stmt(require_node(item, "set_literal_stmt.item_stmts item")) for item in require_list(node, "item_stmts")]
            return "{" + ", ".join(items) + "}"
        raise TranslateError(f"unsupported literal node kind: {kind}")

    def render_sym(self, node: AstNode) -> str:
        sym = require_sym(node, "sym")
        return sym["name"]


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


def require_kind(node: AstNode) -> str:
    kind = node.get("kind")
    if not isinstance(kind, str) or not kind:
        raise TranslateError("AST node requires non-empty string field 'kind'")
    return kind


def require_node(value: Any, label: str) -> AstNode:
    if not isinstance(value, dict):
        raise TranslateError(f"{label} must be an object")
    return value


def require_sym(value: Any, label: str) -> AstNode:
    node = require_node(value, label)
    if node.get("kind") != "sym":
        raise TranslateError(f"{label} must be a sym node")
    name = node.get("name")
    if not isinstance(name, str) or not name:
        raise TranslateError(f"{label}.name must be a non-empty string")
    return node


def require_list(node: AstNode, field: str) -> list[Any]:
    value = node.get(field)
    if not isinstance(value, list):
        raise TranslateError(f"{require_kind(node)}.{field} must be a list")
    return value


def require_scalar_value(node: AstNode, label: str) -> str:
    value = node.get("value")
    if not isinstance(value, str):
        raise TranslateError(f"{label} must be a string")
    return value


def load_ast(path: Path | None) -> AstNode:
    try:
        text = path.read_text(encoding="utf-8") if path is not None else sys.stdin.read()
        return require_node(json.loads(text), "root JSON")
    except json.JSONDecodeError as error:
        raise TranslateError(f"invalid JSON: {error}") from error
    except OSError as error:
        raise TranslateError(str(error)) from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate module_AST JSON to canonical logic-language source text.")
    parser.add_argument("file", nargs="?", type=Path, help="AST JSON file; defaults to stdin")
    args = parser.parse_args()
    try:
        sys.stdout.write(translate_ast_to_source(load_ast(args.file)))
    except TranslateError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
