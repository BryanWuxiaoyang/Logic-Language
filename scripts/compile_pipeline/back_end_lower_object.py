#!/usr/bin/env python3
"""Stage 5: lower parsed module statements to module_AST-shaped nodes."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import (
    DECL_BODY_OUTPUT_MARKER,
    DECL_OUTPUT_MARKER,
    GENERATED_SYM_PREFIX,
    Binding_stmt,
    Call_expr,
    Char_literal_stmt,
    Empty_expr,
    ExprNode,
    Func_stmt,
    Literal_expr,
    Lambda_expr,
    Module,
    Module_ref_expr,
    Module_stmt,
    Quantified_stmt,
    Set_literal_stmt,
    Set_expr,
    Set_stmt,
    SourceLoc,
    Source_loc,
    Stmt,
    Statement,
    Str_literal_stmt,
    Sym,
    SymNode,
    Sym_expr,
    Tuple_expr,
    Tuple_literal_stmt,
    Value_literal_stmt,
    loc_to_json,
    object_ast_to_json,
    pred_or_func_from_parts,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.source_syntax import is_generated_sym_name, is_plain_sym
from compile_pipeline.source_utils import LiteralValue
from compile_pipeline.back_end_statements import ParsedStatements

AstNode = Stmt

@dataclass(frozen=True)
class ModuleAstResult:
    ast: Stmt

    def summary(self) -> str:
        node = object_ast_to_json(self.ast)
        return json.dumps(
            {
                "stage": "back_end_lower_object",
                "root": ast_summary(node),
            },
            ensure_ascii=False,
        )


class AstLowerer:
    def __init__(self, loc: SourceLoc) -> None:
        self.loc = loc.to_json()
        self.temp_index = 0
        self.generated_bound_stack: list[list[AstNode]] = []
        self.generated_premise_stack: list[list[AstNode]] = []
        self.generated_target_stack: list[list[AstNode]] = []
        self.lambda_scopes: list[dict[str, str]] = []

    def lower_module(self, module: Module, *, generated: bool = False) -> AstNode:
        self.generated_bound_stack.append([])
        self.generated_premise_stack.append([])
        self.generated_target_stack.append([])
        premise_bindings: list[AstNode] = []
        premise_pss: list[AstNode] = []
        target_pss: list[AstNode] = []
        suppress_next_body_output_classifiers = False

        for statement in module.predicate_statements:
            if statement.marker in {DECL_OUTPUT_MARKER, DECL_BODY_OUTPUT_MARKER}:
                suppress_next_body_output_classifiers = statement.marker == DECL_BODY_OUTPUT_MARKER
                continue
            bindings, nodes = self.lower_statement(
                statement,
                target_section=False,
                suppress_generated_classifiers=suppress_next_body_output_classifiers,
            )
            suppress_next_body_output_classifiers = False
            premise_bindings.extend(bindings)
            for node in nodes:
                if isinstance(node, Binding_stmt):
                    premise_bindings.append(node)
                else:
                    premise_pss.append(node)
        for statement in module.target_statements:
            bindings, nodes = self.lower_statement(statement, target_section=True)
            premise_bindings.extend(bindings)
            for node in nodes:
                if isinstance(node, Binding_stmt):
                    raise self.located_error("target_proposition_stmts cannot contain Binding_stmt", statement)
                target_pss.append(node)

        generated_premise_pss = self.generated_premise_stack.pop()
        explicit_predicate_keys = {
            stmt_identity_key(node)
            for node in [*premise_pss, *target_pss]
            if is_sym_only_func_stmt(node)
        }
        for node in generated_premise_pss:
            if stmt_identity_key(node) not in explicit_predicate_keys:
                premise_pss.append(node)
        generated_target_pss = self.generated_target_stack.pop()
        target_predicate_keys = {
            stmt_identity_key(node)
            for node in target_pss
            if is_sym_only_func_stmt(node)
        }
        generated_target_nodes: list[AstNode] = []
        for node in generated_target_pss:
            key = stmt_identity_key(node)
            if key not in target_predicate_keys:
                generated_target_nodes.append(node)
                target_predicate_keys.add(key)
        target_pss = [*generated_target_nodes, *target_pss]

        generated_syms = self.generated_bound_stack.pop()
        bound_locs = module.bound_sym_locs or []
        bound_source_names = module.bound_sym_source_names or []
        bound_names = [
            sym_node(
                sym,
                bound_locs[index] if index < len(bound_locs) and bound_locs[index] is not None else self.loc,
                source_name=bound_source_names[index] if index < len(bound_source_names) else None,
            )
            for index, sym in enumerate(module.syms)
        ]
        module_cls = Quantified_stmt if module.type == "quantifier" else Set_stmt
        ast = module_cls(
            source_loc=loc_from_any(self.loc),
            generated=generated,
            bound_syms=[*bound_names, *generated_syms],
            premise_binding_stmts=premise_bindings,
            premise_proposition_stmts=dedupe_stmt_nodes(premise_pss),
            target_proposition_stmts=dedupe_stmt_nodes(target_pss),
        )
        if module.quantifier is not None:
            ast.quantifier_sym = sym_node(module.quantifier, self.loc)
        return ast

    def lower_statement(
        self,
        statement: Statement,
        *,
        target_section: bool,
        suppress_generated_classifiers: bool = False,
    ) -> tuple[list[AstNode], list[AstNode]]:
        if statement.marker in {DECL_OUTPUT_MARKER, DECL_BODY_OUTPUT_MARKER}:
            return [], []
        if statement.expr is not None:
            return self.lower_typed_statement(
                statement.expr,
                statement,
                target_section=target_section,
                suppress_generated_classifiers=suppress_generated_classifiers,
            )
        raise self.located_error("back_end_lower_object requires typed expression or typed marker for every statement", statement)

    def lower_typed_statement(
        self,
        expr: ExprNode,
        statement: Statement,
        *,
        target_section: bool,
        suppress_generated_classifiers: bool = False,
    ) -> tuple[list[AstNode], list[AstNode]]:
        if isinstance(expr, Call_expr) and expr.call_sym is not None and expr.call_sym.name == "=" and len(expr.args) == 2:
            return self.lower_typed_assignment(
                expr.args[0],
                expr.args[1],
                statement,
                target_section=target_section,
                suppress_generated_classifiers=suppress_generated_classifiers,
            )
        bindings: list[AstNode] = []
        node = self.expr_node_to_ast(expr, statement, bindings)
        return bindings, [node]

    def lower_typed_assignment(
        self,
        lhs: ExprNode,
        rhs: ExprNode,
        statement: Statement,
        *,
        target_section: bool,
        suppress_generated_classifiers: bool = False,
    ) -> tuple[list[AstNode], list[AstNode]]:
        lhs_items = expr_tuple_sym_names(lhs)
        if lhs_items is not None:
            return self.lower_typed_compound_lhs(
                lhs_items,
                rhs,
                statement,
                target_section=target_section,
                suppress_generated_classifiers=suppress_generated_classifiers,
            )
        if isinstance(lhs, Sym_expr) and lhs.sym is not None and is_plain_sym(lhs.sym.name):
            bindings: list[AstNode] = []
            rhs_expr = self.expr_node_to_ast(rhs, statement, bindings)
            lhs_loc = loc_for_sym_node(lhs.sym, self.statement_loc(statement))
            stmt_loc = expr_loc_json(lhs) or self.statement_loc(statement)
            if isinstance(rhs_expr, Sym):
                return bindings, [func_stmt("=", [sym_node(lhs.sym.name, lhs_loc), rhs_expr], stmt_loc)]
            if isinstance(rhs_expr, (Func_stmt, Module_stmt, Char_literal_stmt, Str_literal_stmt, Value_literal_stmt, Tuple_literal_stmt, Set_literal_stmt)):
                if target_section:
                    rhs_sym = self.ensure_sym(rhs_expr, bindings, preferred=preferred_expr_node_name(rhs))
                    return bindings, [func_stmt("=", [sym_node(lhs.sym.name, lhs_loc), rhs_sym], stmt_loc)]
                return bindings, [binding_stmt(lhs.sym.name, rhs_expr, stmt_loc, dst_loc=lhs_loc)]
            raise self.located_error(f"unsupported assignment RHS: {rhs.kind}", statement, rhs)
        bindings = []
        lhs_sym = self.ensure_sym(self.expr_node_to_ast(lhs, statement, bindings), bindings)
        rhs_sym = self.ensure_sym(self.expr_node_to_ast(rhs, statement, bindings), bindings)
        return bindings, [func_stmt("=", [lhs_sym, rhs_sym], self.statement_loc(statement))]

    def lower_typed_compound_lhs(
        self,
        lhs_items: list[SymNodeInfo],
        rhs: ExprNode,
        statement: Statement,
        *,
        target_section: bool,
        suppress_generated_classifiers: bool = False,
    ) -> tuple[list[AstNode], list[AstNode]]:
        bindings: list[AstNode] = []
        rhs_sym = self.ensure_sym(self.expr_node_to_ast(rhs, statement, bindings), bindings, preferred=preferred_expr_node_name(rhs))
        if not suppress_generated_classifiers:
            origin_loc = rhs_sym.source_loc.to_json() if isinstance(rhs_sym, Sym) else self.statement_loc(statement)
            tuple_classifier = func_stmt("~", [sym_node("Tuple", origin_loc), rhs_sym], origin_loc, generated=True)
            if self.generated_target_stack:
                self.generated_target_stack[-1].append(tuple_classifier)
            elif self.generated_premise_stack:
                self.generated_premise_stack[-1].append(tuple_classifier)
        target_nodes: list[AstNode] = []
        for index, lhs in enumerate(lhs_items):
            index_literal = literal_stmt(LiteralValue("value", str(index), str(index)), self.statement_loc(statement))
            index_sym = self.ensure_sym(
                index_literal,
                bindings,
                preferred="value",
                suppress_literal_classifier=suppress_generated_classifiers,
            )
            index_call = func_stmt("[]", [rhs_sym, index_sym], self.statement_loc(statement), generated=True)
            if target_section:
                component_sym = self.ensure_sym(index_call, bindings, preferred="[]")
                target_nodes.append(func_stmt("=", [sym_node(lhs.name, lhs.loc), component_sym], self.statement_loc(statement)))
            else:
                bindings.append(binding_stmt(lhs.name, index_call, self.statement_loc(statement), dst_loc=lhs.loc))
        if not lhs_items:
            raise self.located_error("empty tuple/list assignment left-hand side", statement)
        return bindings, target_nodes

    def expr_node_to_ast(self, expr: ExprNode, statement: Statement, bindings: list[AstNode]) -> AstNode:
        loc = expr_loc_json(expr) or self.statement_loc(statement)
        if isinstance(expr, Lambda_expr):
            function_name = self.fresh_temp("lambda")
            parameter_name = self.fresh_temp("lambda_arg")
            parameter_loc = loc_for_sym_node(expr.sym, loc)
            parameter_expr = Sym_expr(parameter_loc, sym=SymNode(parameter_name, parameter_loc, generated=True))
            application = Call_expr(loc, call_sym=SymNode(function_name, loc, generated=True), args=[parameter_expr])
            definition = Module(
                type="quantifier", syms=[parameter_name], quantifier="∀",
                predicate_statements=[],
                bound_sym_locs=[parameter_loc], source_loc=loc,
                target_statements=[Statement(source_loc=loc, sub_modules=statement.sub_modules, expr=Call_expr(
                    loc, call_sym=SymNode("=", loc), args=[application, expr.args[0]]
                ))],
            )
            self.lambda_scopes.append({expr.sym.name: parameter_name})
            try:
                definition_ast = self.lower_module(definition, generated=True)
            finally:
                self.lambda_scopes.pop()
            function_sym = sym_node(function_name, loc, generated=True)
            self.generated_bound_stack[-1].append(function_sym)
            self.generated_premise_stack[-1].extend([
                func_stmt("~", [sym_node("Function", loc), function_sym], loc, generated=True),
                definition_ast,
            ])
            return function_sym
        if isinstance(expr, Sym_expr) and expr.sym is not None:
            name = self.lambda_name(expr.sym.name)
            return sym_node(name, loc_for_sym_node(expr.sym, loc), generated=expr.sym.generated or name != expr.sym.name, source_name=expr.sym.source_name)
        if isinstance(expr, Literal_expr):
            kind = expr.literal_kind
            raw = expr.value or ""
            return literal_stmt(LiteralValue(kind, expr.value or raw, raw), loc)
        if isinstance(expr, Tuple_expr):
            return literal_collection("tuple_literal_stmt", [self.expr_node_to_ast(item, statement, bindings) for item in expr.items], loc)
        if isinstance(expr, Set_expr):
            return literal_collection("set_literal_stmt", [self.expr_node_to_ast(item, statement, bindings) for item in expr.items], loc)
        if isinstance(expr, Module_ref_expr):
            index = int(expr.value or "0")
            return self.lower_module(statement.sub_modules[index])
        if isinstance(expr, Call_expr) and expr.call_sym is not None:
            local_bindings: list[AstNode] = []
            args = [
                self.ensure_sym(self.expr_node_to_ast(arg, statement, local_bindings), local_bindings, preferred=preferred_expr_node_name(arg))
                for arg in expr.args
            ]
            bindings.extend(local_bindings)
            return func_stmt(
                self.lambda_name(expr.call_sym.name),
                args,
                loc,
                call_loc=loc_for_sym_node(expr.call_sym, loc),
            )
        if isinstance(expr, Empty_expr):
            raise self.located_error("empty statement", statement, expr)
        raise self.located_error(f"unsupported expression: {expr.kind}", statement, expr)

    def lambda_name(self, name: str) -> str:
        for scope in reversed(self.lambda_scopes):
            if name in scope:
                return scope[name]
        return name

    def located_error(self, message: str, statement: Statement | None = None, expr: ExprNode | None = None) -> CompileError:
        loc = expr_loc_json(expr) if expr is not None else None
        if loc is None and statement is not None:
            loc = self.statement_loc(statement)
        return CompileError(message, source_loc=loc or self.loc)

    def ensure_sym(
        self,
        expr: AstNode,
        bindings: list[AstNode],
        *,
        preferred: str | None = None,
        suppress_literal_classifier: bool = False,
    ) -> AstNode:
        if isinstance(expr, Sym):
            return expr
        temp = self.fresh_temp(preferred or preferred_temp_name(temp_kind_name(expr)))
        origin_loc = expr.source_loc.to_json()
        origin_name = source_name_for_expr(expr, preferred or preferred_temp_name(temp_kind_name(expr)))
        temp_sym = sym_node(temp, origin_loc, generated=True, source_name=origin_name)
        if self.generated_bound_stack:
            self.generated_bound_stack[-1].append(temp_sym)
        bindings.append(binding_stmt(temp, expr, origin_loc, generated=True, source_name=origin_name))
        classifier = literal_classifier_name(expr)
        if classifier is not None and self.generated_target_stack and not suppress_literal_classifier:
            self.generated_target_stack[-1].append(func_stmt("~", [sym_node(classifier, origin_loc), temp_sym], origin_loc, generated=True))
        return temp_sym

    def statement_loc(self, statement: Statement) -> dict[str, Any]:
        return statement.source_loc or self.loc

    def fresh_temp(self, preferred: str) -> str:
        base = GENERATED_SYM_PREFIX + "tmp" + sanitize_temp_name(preferred)
        candidate = f"{base}{self.temp_index}"
        self.temp_index += 1
        return candidate


def run(parsed: ParsedStatements, loc: SourceLoc | None = None) -> ModuleAstResult:
    if not isinstance(parsed, ParsedStatements):
        raise CompileError("back_end_lower_object requires ParsedStatements")
    loc = loc or SourceLoc("__stdin__", 1, 1, 1, 1)
    return ModuleAstResult(ast=AstLowerer(loc).lower_module(parsed.module))


def sym_node(name: str, loc: dict[str, Any] | Source_loc | None = None, *, generated: bool = False, source_name: str | None = None) -> Sym:
    is_generated = generated or is_generated_sym_name(name)
    return Sym(
        source_loc=loc_from_any(loc),
        generated=is_generated,
        name=name,
        source_name=(source_name or generated_source_name(name)) if is_generated else source_name,
    )


def func_stmt(name: str, args: list[AstNode], loc: dict[str, Any], *, generated: bool = False, call_loc: dict[str, Any] | None = None) -> Func_stmt:
    if not all(isinstance(arg, Sym) for arg in args):
        raise CompileError("Func_stmt arguments must be Sym")
    return pred_or_func_from_parts(
        sym_node(name, call_loc or loc),
        [arg for arg in args if isinstance(arg, Sym)],
        loc_from_any(loc),
        generated,
    )


def literal_classifier_name(stmt: Stmt) -> str | None:
    if isinstance(stmt, Tuple_literal_stmt):
        return "Tuple"
    if isinstance(stmt, Set_literal_stmt):
        return "Set"
    if isinstance(stmt, Value_literal_stmt):
        return "Value"
    if isinstance(stmt, Char_literal_stmt):
        return "Char"
    if isinstance(stmt, Str_literal_stmt):
        return "String"
    return None


def stmt_identity_key(node: AstNode) -> tuple[Any, ...]:
    if not isinstance(node, Func_stmt):
        return (type(node).__name__, id(node))
    return ("Func_stmt", node.call_sym.name, tuple(arg.name for arg in node.arg_sym_list))


def is_sym_only_func_stmt(node: AstNode) -> bool:
    return isinstance(node, Func_stmt) and bool(node.call_sym.name) and all(isinstance(arg, Sym) and arg.name for arg in node.arg_sym_list)


def dedupe_stmt_nodes(nodes: list[AstNode]) -> list[AstNode]:
    seen: set[tuple[Any, ...]] = set()
    result: list[AstNode] = []
    for node in nodes:
        if not is_sym_only_func_stmt(node):
            result.append(node)
            continue
        key = stmt_identity_key(node)
        if key in seen:
            continue
        seen.add(key)
        result.append(node)
    return result


def binding_stmt(
    dst: str,
    src: AstNode,
    loc: dict[str, Any],
    *,
    generated: bool = False,
    dst_loc: dict[str, Any] | None = None,
    source_name: str | None = None,
) -> AstNode:
    return Binding_stmt(
        source_loc=loc_from_any(loc),
        generated=generated,
        dst_sym=sym_node(dst, dst_loc or loc, generated=generated, source_name=source_name),
        src_stmt=src,
    )


def literal_stmt(literal: LiteralValue, loc: dict[str, Any]) -> AstNode:
    loc_obj = loc_from_any(loc)
    if literal.kind == "char":
        return Char_literal_stmt(source_loc=loc_obj, value=literal.value)
    if literal.kind == "string":
        return Str_literal_stmt(source_loc=loc_obj, value=literal.value)
    return Value_literal_stmt(source_loc=loc_obj, value=literal.value)


def literal_collection(kind: str, items: list[AstNode], loc: dict[str, Any]) -> AstNode:
    loc_obj = loc_from_any(loc)
    if kind == "tuple_literal_stmt":
        return Tuple_literal_stmt(source_loc=loc_obj, item_stmts=items)
    if kind == "set_literal_stmt":
        return Set_literal_stmt(source_loc=loc_obj, item_stmts=items)
    raise CompileError(f"unsupported literal collection kind: {kind}")


def generated_source_name(name: str) -> str:
    if is_generated_sym_name(name):
        return name[len(GENERATED_SYM_PREFIX) :]
    return name


def source_name_for_expr(expr: AstNode, fallback: str) -> str:
    if isinstance(expr, Sym):
        return expr.name
    if isinstance(expr, Func_stmt) and expr.call_sym.name:
        return expr.call_sym.name
    if isinstance(expr, (Char_literal_stmt, Str_literal_stmt, Value_literal_stmt)):
        return expr.value
    return fallback


@dataclass(frozen=True)
class SymNodeInfo:
    name: str
    loc: dict[str, Any]


def expr_loc_json(expr: ExprNode) -> dict[str, Any] | None:
    if expr.source_loc is None:
        return None
    return loc_to_json(expr.source_loc)


def loc_for_sym_node(sym: SymNode, fallback: dict[str, Any]) -> dict[str, Any]:
    if sym.source_loc is None:
        return fallback
    return loc_to_json(sym.source_loc)


def loc_from_any(loc: dict[str, Any] | Source_loc | None) -> Source_loc:
    if isinstance(loc, Source_loc):
        return Source_loc(loc.file_path, loc.line, loc.column, loc.end_line, loc.end_column)
    if isinstance(loc, dict):
        return Source_loc.from_json(loc)
    return Source_loc("__stdin__", 1, 1, 1, 1)


def expr_tuple_sym_names(expr: ExprNode) -> list[SymNodeInfo] | None:
    if not isinstance(expr, Tuple_expr):
        return None
    output: list[SymNodeInfo] = []
    for item in expr.items:
        if not isinstance(item, Sym_expr) or item.sym is None or not is_plain_sym(item.sym.name):
            return None
        output.append(SymNodeInfo(item.sym.name, loc_for_sym_node(item.sym, expr_loc_json(item) or {"source": "__stdin__", "line": 1, "column": 1, "end_line": 1, "end_column": 1})))
    return output


def preferred_expr_node_name(expr: ExprNode) -> str:
    if isinstance(expr, Sym_expr) and expr.sym is not None:
        return expr.sym.name
    if isinstance(expr, Call_expr) and expr.call_sym is not None:
        return expr.call_sym.name
    if expr.value:
        return expr.value
    return expr.kind


def preferred_temp_name(value: object) -> str:
    return str(value or "tmp")


def temp_kind_name(stmt: Stmt) -> str:
    if isinstance(stmt, Value_literal_stmt):
        return "value_literal_stmt"
    if isinstance(stmt, Char_literal_stmt):
        return "char_literal_stmt"
    if isinstance(stmt, Str_literal_stmt):
        return "str_literal_stmt"
    if isinstance(stmt, Tuple_literal_stmt):
        return "tuple_literal_stmt"
    if isinstance(stmt, Set_literal_stmt):
        return "set_literal_stmt"
    if isinstance(stmt, Func_stmt):
        return "func_stmt"
    if isinstance(stmt, Set_stmt):
        return "set_stmt"
    if isinstance(stmt, Quantified_stmt):
        return "quantified_stmt"
    if isinstance(stmt, Sym):
        return "sym"
    if isinstance(stmt, Binding_stmt):
        return "binding_stmt"
    return type(stmt).__name__


def sanitize_temp_name(value: str) -> str:
    if value == "[]":
        return "index"
    if value == "[:]":
        return "slice"
    aliases = {
        "+": "add",
        "-": "sub",
        "*": "mul",
        "/": "div",
        "%": "mod",
        "!": "not",
        "&&": "and",
        "||": "or",
        "=": "eq",
        "~": "inherit",
        "<": "lt",
        ">": "gt",
        "<=": "le",
        ">=": "ge",
        "!=": "neq",
        "∪": "union",
        "∩": "intersect",
        "∧": "land",
        "∨": "lor",
        "∈": "in",
        "∉": "notin",
        "⊂": "subset",
        "⊄": "notsubset",
        "⊆": "subseteq",
        "⊈": "notsubseteq",
    }
    value = aliases.get(value, value)
    sanitized = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    return sanitized or "tmp"


def ast_summary(node: dict[str, object]) -> dict[str, object]:
    return {
        "kind": node.get("kind"),
        "bound_syms": len(node.get("bound_syms", [])),
        "premise_binding_stmts": len(node.get("premise_binding_stmts", [])),
        "premise_proposition_stmts": len(node.get("premise_proposition_stmts", [])),
        "target_proposition_stmts": len(node.get("target_proposition_stmts", [])),
    }
