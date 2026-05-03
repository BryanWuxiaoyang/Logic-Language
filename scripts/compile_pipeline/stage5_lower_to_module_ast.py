#!/usr/bin/env python3
"""Stage 5: lower parsed module statements to module_AST-shaped nodes."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_module import (
    CompileError,
    LiteralValue,
    Module,
    Statement,
    find_matching,
    find_quoted_literal_end,
    is_literal_quote_start,
    is_plain_sym,
    lower_member_calls,
    parse_literal_text,
    split_top_level,
    top_level_assignment_index,
)
from compile_pipeline.stage1_normalize_source import SourceLoc
from compile_pipeline.stage4_parse_statements import ParsedStatements, run as parse_statements

AstNode = dict[str, Any]

OPERATOR_CALLS: tuple[tuple[str, str], ...] = (
    ("≠", "!="),
    ("!=", "!="),
    ("≥", ">="),
    (">=", ">="),
    ("≤", "<="),
    ("<=", "<="),
    ("&&", "&&"),
    ("||", "||"),
    ("+", "+"),
    ("-", "-"),
    ("*", "*"),
    ("/", "/"),
    ("∉", "∉"),
    ("∈", "∈"),
    ("⊄", "⊄"),
    ("⊂", "⊂"),
    ("⊈", "⊈"),
    ("⊆", "⊆"),
    (">", ">"),
    ("<", "<"),
    ("~", "~"),
)


@dataclass(frozen=True)
class ModuleAstResult:
    ast: AstNode

    def summary(self) -> str:
        lines = ["stage: stage5_lower_to_module_ast"]
        summarize_ast(self.ast, lines, 0)
        return "\n".join(lines)


class AstLowerer:
    def __init__(self, loc: SourceLoc) -> None:
        self.loc = loc.to_json()
        self.temp_index = 0
        self.generated_bound_stack: list[list[AstNode]] = []
        self.generated_premise_stack: list[list[AstNode]] = []

    def lower_module(self, module: Module, *, generated: bool = False) -> AstNode:
        self.generated_bound_stack.append([])
        self.generated_premise_stack.append([])
        premise_bindings: list[AstNode] = []
        premise_pss: list[AstNode] = []
        target_pss: list[AstNode] = []

        for statement in module.predicate_statements:
            bindings, nodes = self.lower_statement(statement, target_section=False)
            premise_bindings.extend(bindings)
            for node in nodes:
                if node.get("kind") == "binding_stmt":
                    premise_bindings.append(node)
                else:
                    premise_pss.append(node)
        for statement in module.target_statements:
            bindings, nodes = self.lower_statement(statement, target_section=True)
            premise_bindings.extend(bindings)
            for node in nodes:
                if node.get("kind") == "binding_stmt":
                    raise CompileError("target_PSs cannot contain binding_stmt")
                target_pss.append(node)

        generated_premise_pss = self.generated_premise_stack.pop()
        explicit_predicate_keys = {
            stmt_identity_key(node)
            for node in [*premise_pss, *target_pss]
            if node.get("kind") == "func_stmt"
        }
        for node in generated_premise_pss:
            if stmt_identity_key(node) not in explicit_predicate_keys:
                premise_pss.append(node)

        generated_syms = self.generated_bound_stack.pop()
        bound_names = [sym_node(sym, self.loc) for sym in module.syms if sym not in intrinsic_syms()]
        kind = "quantified_stmt" if module.type == "quantifier" else "set_stmt"
        ast: AstNode = {
            "kind": kind,
            "loc": self.loc,
            "bound_syms": [*bound_names, *generated_syms],
            "premise_binding_stmts": premise_bindings,
            "premise_PSs": dedupe_stmt_nodes(premise_pss),
            "target_PSs": dedupe_stmt_nodes(target_pss),
        }
        if generated:
            ast["generated"] = True
        if module.quantifier is not None:
            ast["quantifier_sym"] = sym_node(module.quantifier)
        return ast

    def lower_statement(self, statement: Statement, *, target_section: bool) -> tuple[list[AstNode], list[AstNode]]:
        text = lower_member_calls(statement.text.strip())
        if not text:
            raise CompileError("empty statement")
        placeholder = re.fullmatch(r"\$module(?P<index>\d+)", text)
        if placeholder is not None:
            return [], [self.lower_module(statement.sub_modules[int(placeholder.group("index"))])]

        assignment_index = top_level_assignment_index(text)
        if assignment_index is not None:
            return self.lower_assignment(
                text[:assignment_index].strip(),
                text[assignment_index + 1 :].strip(),
                statement,
                target_section=target_section,
            )
        bindings, node = self.lower_call_statement(text, statement)
        return bindings, [node]

    def lower_assignment(self, lhs: str, rhs: str, statement: Statement, *, target_section: bool) -> tuple[list[AstNode], list[AstNode]]:
        lhs_items = parse_tuple_or_list_items(lhs)
        if lhs_items is not None:
            return self.lower_compound_lhs(lhs_items, rhs, statement, target_section=target_section)
        if is_plain_sym(lhs):
            rhs_expr = self.parse_expr(rhs, statement)
            if rhs_expr["kind"] == "sym":
                return [], [func_stmt("=", [sym_node(lhs, self.loc), rhs_expr], self.loc)]
            if rhs_expr["kind"] in {"func_stmt", "set_stmt", "quantified_stmt"} or rhs_expr["kind"].endswith("_literal_stmt"):
                if target_section:
                    bindings: list[AstNode] = []
                    rhs_sym = self.ensure_sym(rhs_expr, bindings, preferred=preferred_temp_name(rhs))
                    return bindings, [func_stmt("=", [sym_node(lhs, self.loc), rhs_sym], self.loc)]
                nested_bindings = rhs_expr.pop("_bindings", [])
                return nested_bindings, [binding_stmt(lhs, rhs_expr, self.loc)]
            raise CompileError(f"unsupported assignment RHS: {rhs}")
        bindings: list[AstNode] = []
        lhs_sym = self.ensure_sym(self.parse_expr(lhs, statement), bindings)
        rhs_sym = self.ensure_sym(self.parse_expr(rhs, statement), bindings)
        return bindings, [func_stmt("=", [lhs_sym, rhs_sym], self.loc)]

    def lower_compound_lhs(self, lhs_items: list[str], rhs: str, statement: Statement, *, target_section: bool) -> tuple[list[AstNode], list[AstNode]]:
        if not all(is_plain_sym(item) for item in lhs_items):
            raise CompileError("tuple/list assignment left-hand side must contain only symbols")
        bindings: list[AstNode] = []
        rhs_sym = self.ensure_sym(self.parse_expr(rhs, statement), bindings, preferred=preferred_temp_name(rhs))
        target_nodes: list[AstNode] = []
        for index, lhs in enumerate(lhs_items):
            index_literal = literal_stmt(LiteralValue("value", str(index), str(index)), self.loc)
            index_sym = self.ensure_sym(index_literal, bindings, preferred="value")
            index_call = func_stmt("[]", [rhs_sym, index_sym], self.loc, generated=True)
            if target_section:
                component_sym = self.ensure_sym(index_call, bindings, preferred="[]")
                target_nodes.append(func_stmt("=", [sym_node(lhs, self.loc), component_sym], self.loc))
            else:
                bindings.append(binding_stmt(lhs, index_call, self.loc))
        if not lhs_items:
            raise CompileError("empty tuple/list assignment left-hand side")
        return bindings, target_nodes

    def lower_call_statement(self, text: str, statement: Statement) -> tuple[list[AstNode], AstNode]:
        expr = self.parse_expr(text, statement)
        if expr["kind"] == "func_stmt":
            return expr.pop("_bindings", []), expr
        raise CompileError(f"unsupported non-call statement: {text}")

    def parse_expr(self, text: str, statement: Statement) -> AstNode:
        text = text.strip()
        placeholder = re.fullmatch(r"\$module(?P<index>\d+)", text)
        if placeholder is not None:
            return self.lower_module(statement.sub_modules[int(placeholder.group("index"))])
        literal = parse_literal_or_numeric(text)
        if literal is not None:
            return literal_stmt(literal, self.loc)
        items = parse_tuple_or_list_items(text)
        if items is not None:
            return literal_collection("tuple_literal_stmt", [self.parse_expr(item, statement) for item in items], self.loc)
        set_items = parse_set_literal_items(text)
        if set_items is not None:
            return literal_collection("set_literal_stmt", [self.parse_expr(item, statement) for item in set_items], self.loc)
        grouped = strip_outer_grouping_parens(text)
        if grouped is not None:
            return self.parse_expr(grouped, statement)
        index_call = parse_index_call(text)
        if index_call is not None:
            receiver, index = index_call
            return self.call_expr("[]", [receiver, index], statement)
        call = parse_call(text)
        if call is not None:
            name, args = call
            return self.call_expr(name, args, statement)
        operator = split_operator(text)
        if operator is not None:
            lhs, op, rhs = operator
            return self.call_expr(op, [lhs, rhs], statement)
        if is_sym_name(text):
            return sym_node(text, self.loc)
        raise CompileError(f"unsupported expression: {text}")

    def call_expr(self, name: str, arg_texts: list[str], statement: Statement) -> AstNode:
        bindings: list[AstNode] = []
        args = [self.ensure_sym(self.parse_expr(arg, statement), bindings, preferred=preferred_temp_name(arg)) for arg in arg_texts if arg.strip()]
        node = func_stmt(name, args, self.loc)
        if bindings:
            node["_bindings"] = bindings
        return node

    def ensure_sym(self, expr: AstNode, bindings: list[AstNode], *, preferred: str | None = None) -> AstNode:
        if expr["kind"] == "sym":
            return expr
        nested_bindings = expr.pop("_bindings", [])
        bindings.extend(nested_bindings)
        temp = self.fresh_temp(preferred or preferred_temp_name(expr.get("kind", "tmp")))
        temp_sym = sym_node(temp, self.loc, generated=True)
        if self.generated_bound_stack:
            self.generated_bound_stack[-1].append(temp_sym)
        bindings.append(binding_stmt(temp, expr, self.loc, generated=True))
        classifier = literal_classifier_name(expr.get("kind"))
        if classifier is not None and self.generated_premise_stack:
            self.generated_premise_stack[-1].append(func_stmt("~", [sym_node(classifier, self.loc), temp_sym], self.loc, generated=True))
        return temp_sym

    def fresh_temp(self, preferred: str) -> str:
        base = "__tmp" + sanitize_temp_name(preferred)
        candidate = f"{base}{self.temp_index}"
        self.temp_index += 1
        return candidate


def run(parsed: ParsedStatements | str, loc: SourceLoc | None = None) -> ModuleAstResult:
    if isinstance(parsed, str):
        parsed = parse_statements(parsed)
    loc = loc or SourceLoc("__stdin__", 1, 1, 1, 1)
    return ModuleAstResult(ast=AstLowerer(loc).lower_module(parsed.module))


def sym_node(name: str, loc: dict[str, Any] | None = None, *, generated: bool = False) -> AstNode:
    node: AstNode = {"kind": "sym", "name": name}
    if loc is not None:
        node["loc"] = loc
    if generated:
        node["generated"] = True
    return node


def func_stmt(name: str, args: list[AstNode], loc: dict[str, Any], *, generated: bool = False) -> AstNode:
    node: AstNode = {"kind": "func_stmt", "loc": loc, "call_sym": sym_node(name, loc), "arg_sym_list": args}
    if generated:
        node["generated"] = True
    return node


def literal_classifier_name(kind: str | None) -> str | None:
    return {
        "tuple_literal_stmt": "tuple",
        "set_literal_stmt": "set",
        "value_literal_stmt": "value",
        "char_literal_stmt": "char",
        "str_literal_stmt": "string",
    }.get(kind)


def stmt_identity_key(node: AstNode) -> tuple[Any, ...]:
    kind = node.get("kind")
    if kind == "func_stmt":
        call_name = node.get("call_sym", {}).get("name")
        arg_names = tuple(arg.get("name") for arg in node.get("arg_sym_list", []))
        return (kind, call_name, arg_names)
    if kind == "binding_stmt":
        dst_name = node.get("dst_sym", {}).get("name")
        src_stmt = node.get("src_stmt", {})
        return (kind, dst_name, src_stmt.get("kind"))
    return (kind,)


def dedupe_stmt_nodes(nodes: list[AstNode]) -> list[AstNode]:
    seen: set[tuple[Any, ...]] = set()
    result: list[AstNode] = []
    for node in nodes:
        if node.get("kind") != "func_stmt":
            result.append(node)
            continue
        key = stmt_identity_key(node)
        if key in seen:
            continue
        seen.add(key)
        result.append(node)
    return result


def binding_stmt(dst: str, src: AstNode, loc: dict[str, Any], *, generated: bool = False) -> AstNode:
    node: AstNode = {"kind": "binding_stmt", "loc": loc, "dst_sym": sym_node(dst, loc, generated=generated), "src_stmt": src}
    if generated:
        node["generated"] = True
    return node


def literal_stmt(literal: LiteralValue, loc: dict[str, Any]) -> AstNode:
    kind = {"char": "char_literal_stmt", "string": "str_literal_stmt", "value": "value_literal_stmt"}[literal.kind]
    return {"kind": kind, "loc": loc, "value": literal.value}


def literal_collection(kind: str, items: list[AstNode], loc: dict[str, Any]) -> AstNode:
    return {"kind": kind, "loc": loc, "item_stmts": items}


def parse_literal_or_numeric(text: str) -> LiteralValue | None:
    literal = parse_literal_text(text)
    if literal is not None:
        return literal
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return LiteralValue("value", text, text)
    return None


def parse_tuple_or_list_items(text: str) -> list[str] | None:
    text = text.strip()
    if len(text) < 2:
        return None
    pairs = {"(": ")", "[": "]"}
    if text[0] not in pairs or text[-1] != pairs[text[0]]:
        return None
    if find_matching(text, 0, text[0], text[-1]) != len(text) - 1:
        return None
    inner = text[1:-1].strip()
    if not inner:
        return []
    items = [item.strip() for item in split_top_level(inner, ",") if item.strip()]
    if len(items) <= 1 and "," not in inner:
        return None
    return items


def parse_set_literal_items(text: str) -> list[str] | None:
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    if find_matching(text, 0, "{", "}") != len(text) - 1:
        return None
    inner = text[1:-1].strip()
    if not inner:
        return None
    if "|" in inner or "=>" in inner:
        return None
    return [item.strip() for item in split_top_level(inner, ",") if item.strip()]


def strip_outer_grouping_parens(text: str) -> str | None:
    text = text.strip()
    if len(text) < 2 or not text.startswith("(") or not text.endswith(")"):
        return None
    if find_matching(text, 0, "(", ")") != len(text) - 1:
        return None
    inner = text[1:-1].strip()
    if not inner:
        return None
    if len(split_top_level(inner, ",")) > 1:
        return None
    return inner


def parse_call(text: str) -> tuple[str, list[str]] | None:
    text = text.strip()
    if not text.endswith(")"):
        return None
    open_index = text.find("(")
    if open_index <= 0 or find_matching(text, open_index, "(", ")") != len(text) - 1:
        return None
    name = text[:open_index].strip()
    if not is_sym_name(name):
        return None
    inner = text[open_index + 1 : -1].strip()
    args = [] if not inner else [arg.strip() for arg in split_top_level(inner, ",")]
    return name, args


def parse_index_call(text: str) -> tuple[str, str] | None:
    text = text.strip()
    if not text.endswith("]"):
        return None
    open_index = text.rfind("[")
    if open_index <= 0 or find_matching(text, open_index, "[", "]") != len(text) - 1:
        return None
    return text[:open_index].strip(), text[open_index + 1 : -1].strip()


def split_operator(text: str) -> tuple[str, str, str] | None:
    for raw, canonical in OPERATOR_CALLS:
        parts = split_top_level_token(text, raw) if raw.isalpha() else split_top_level(text, raw)
        if len(parts) == 2:
            lhs, rhs = parts[0].strip(), parts[1].strip()
            if lhs and rhs:
                return lhs, canonical, rhs
    return None


def split_top_level_token(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and text.startswith(separator, index):
            left_ok = index == 0 or not is_sym_name_char(text[index - 1])
            right_index = index + len(separator)
            right_ok = right_index >= len(text) or not is_sym_name_char(text[right_index])
            if left_ok and right_ok:
                parts.append(text[start:index])
                index += len(separator)
                start = index
                continue
        index += 1
    parts.append(text[start:])
    return parts


def is_sym_name(text: str) -> bool:
    return re.fullmatch(r"[^\s()\[\]{},]+", text) is not None


def preferred_temp_name(text: str) -> str:
    call = parse_call(str(text))
    if call is not None:
        return call[0]
    operator = split_operator(str(text))
    if operator is not None:
        return operator[1]
    if isinstance(text, str):
        return text
    return "tmp"


def sanitize_temp_name(value: str) -> str:
    if value == "[]":
        return "index"
    aliases = {
        "+": "add",
        "-": "sub",
        "*": "mul",
        "/": "div",
        "&&": "and",
        "||": "or",
        "=": "eq",
        "~": "inherit",
        "<": "lt",
        ">": "gt",
        "<=": "le",
        ">=": "ge",
    }
    value = aliases.get(value, value)
    sanitized = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    return sanitized or "tmp"


def is_sym_name_char(char: str) -> bool:
    return char.isalnum() or char in {"_", "'"}


def intrinsic_syms() -> set[str]:
    return {"tuple", "set", "function", "value", "true", "false", "bool", "sym", "char", "string", "list"}


def summarize_ast(node: AstNode, lines: list[str], indent: int) -> None:
    pad = " " * indent
    lines.append(f"{pad}{node.get('kind')}")
    if node.get("kind") in {"set_stmt", "quantified_stmt"}:
        lines.append(f"{pad}  bound_syms={[sym.get('name') for sym in node.get('bound_syms', [])]}")
        lines.append(f"{pad}  premise_binding_stmts={len(node.get('premise_binding_stmts', []))}")
        lines.append(f"{pad}  premise_PSs={len(node.get('premise_PSs', []))}")
        lines.append(f"{pad}  target_PSs={len(node.get('target_PSs', []))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 5 AST lowering.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    args = parser.parse_args()
    source = args.text if args.text is not None else args.file.read_text(encoding="utf-8") if args.file is not None else sys.stdin.read()
    source_name = str(args.file.resolve()) if args.file is not None and args.text is None else "__stdin__"
    try:
        result = run(source, SourceLoc(source_name, 1, 1, len(source.splitlines()) or 1, len((source.splitlines() or [""])[-1]) + 1))
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(result.summary())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
