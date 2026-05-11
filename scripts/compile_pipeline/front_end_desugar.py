#!/usr/bin/env python3
"""Stage 2: desugar typed logic-language modules."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import (
    Call_expr,
    DECL_BODY_OUTPUT_MARKER,
    DECL_OUTPUT_MARKER,
    GENERATED_SYM_PREFIX,
    ExprNode,
    Module,
    Module_ref_expr,
    SourceFileAst,
    SourceLoc,
    Statement,
    SymNode,
    Sym_expr,
    Tuple_expr,
    dedupe,
    loc_to_json,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.source_syntax import is_plain_sym
from inheritance_sources import SYMBOL_SOURCE, selected_inheritance_source
from compile_pipeline.check_naming_convention import check_naming_convention


CANONICAL_INFIX_OPERATORS = {"~", "=", "!=", "≠", ">=", "≥", "<=", "≤", ">", "<", "∈", "∉", "⊂", "⊄", "⊆", "⊈"}


@dataclass(frozen=True)
class BindingInfo:
    name: str
    loc: dict[str, object] | None = None


@dataclass(frozen=True)
class ScopeState:
    ancestor_bound_syms: set[str]
    visible_class_names: set[str]


@dataclass(frozen=True)
class DesugarResult:
    import_count: int
    body_line_count: int
    visible_sym_count: int
    ast: SourceFileAst
    diagnostics: list[dict[str, object]]

    def summary(self) -> str:
        return json.dumps(
            {
                "stage": "front_end_desugar",
                "imports": self.import_count,
                "module_count": len(self.ast.modules),
                "visible_syms": self.visible_sym_count,
                "diagnostics": len(self.diagnostics),
                "root": module_summary(lowered_module_from_ast(self.ast)),
            },
            ensure_ascii=False,
        )


def run(source_ast: SourceFileAst, base_dir: Path | str = ".") -> DesugarResult:
    if not isinstance(source_ast, SourceFileAst):
        raise CompileError("front_end_desugar requires SourceFileAst")
    module = lowered_module_from_ast(source_ast)
    if module is None:
        diagnostics = check_naming_convention(source_ast)
        return DesugarResult(source_ast.import_count, 0, 0, source_ast, diagnostics)

    visible_class_names = collect_declared_classes(module)
    visible_syms = collect_root_visible_syms(module) | visible_class_names
    desugarer = ModuleDesugarer(visible_syms)
    desugared_module = desugarer.desugar_module(module, ScopeState(set(visible_syms), set(visible_class_names)))
    source_ast.modules[0].lowered_module = desugared_module
    diagnostics = check_naming_convention(source_ast)
    return DesugarResult(source_ast.import_count, module_statement_count(desugared_module), len(visible_syms), source_ast, diagnostics)


def lowered_module_from_ast(source_ast: SourceFileAst) -> Module | None:
    if not source_ast.modules:
        return None
    module = source_ast.modules[0].lowered_module
    return module if isinstance(module, Module) else None


def module_statement_count(module: Module | None) -> int:
    if module is None:
        return 0
    total = len(module.predicate_statements) + len(module.target_statements)
    for statement in [*module.predicate_statements, *module.target_statements]:
        total += sum(module_statement_count(submodule) for submodule in statement.sub_modules)
    return total


def module_summary(module: Module | None) -> dict[str, object] | None:
    if module is None:
        return None
    return {
        "type": module.type,
        "quantifier": module.quantifier,
        "bound_syms": len(module.syms),
        "premise_statements": len(module.predicate_statements),
        "target_statements": len(module.target_statements),
        "declared_classes": len(module.declared_classes),
    }


def collect_declared_classes(module: Module) -> set[str]:
    classes = set(module.declared_classes)
    for statement in [*module.predicate_statements, *module.target_statements]:
        for submodule in statement.sub_modules:
            classes.update(collect_declared_classes(submodule))
    return classes


def collect_root_visible_syms(module: Module) -> set[str]:
    visible = set(module.declared_classes)
    visible.update(module.declaration_syms)
    for sym in module.syms:
        if sym and sym[0].isupper():
            visible.add(sym)
    return visible


def is_bool_predicate_sym(sym: str) -> bool:
    if is_generated_sym(sym):
        return False
    normalized = sym.lstrip("_").rstrip("'")
    normalized = re.sub(r"\d+$", "", normalized)
    return normalized.startswith("is_")


def typed_statement(
    expr: ExprNode,
    loc: dict[str, object] | SourceLoc | None = None,
    *,
    sub_modules: list[Module] | None = None,
) -> Statement:
    source_loc = normalize_loc(loc) or expr_loc(expr)
    return Statement(
        sub_modules=sub_modules or [],
        source_loc=source_loc,
        sym_locs=sym_locs_from_expr(expr),
        expr=expr,
    )


def normalize_loc(loc: dict[str, object] | SourceLoc | None) -> dict[str, object] | None:
    if loc is None:
        return None
    return loc_to_json(loc)


def expr_loc(expr: ExprNode | None) -> dict[str, object] | None:
    if expr is None or expr.source_loc is None:
        return None
    return loc_to_json(expr.source_loc)


def sym_expr(name: str, loc: dict[str, object] | SourceLoc | None = None) -> ExprNode:
    loc_json = normalize_loc(loc)
    return Sym_expr(loc_json, sym=SymNode(name, loc_json, generated=is_generated_sym(name), source_name=source_name_for_generated(name)))


def call_expr(name: str, args: list[ExprNode], loc: dict[str, object] | SourceLoc | None = None) -> ExprNode:
    loc_json = normalize_loc(loc)
    return Call_expr(loc_json, call_sym=SymNode(name, loc_json), args=args)


def infix_statement(lhs: str, operator: str, rhs: str, loc: dict[str, object] | SourceLoc | None = None) -> Statement:
    return typed_statement(call_expr(operator, [sym_expr(lhs, loc), sym_expr(rhs, loc)], loc), loc)


def module_ref_statement(submodule: Module, loc: dict[str, object] | SourceLoc | None = None) -> Statement:
    loc_json = normalize_loc(loc)
    return typed_statement(Module_ref_expr(loc_json, value="0"), loc_json, sub_modules=[submodule])


def marker_statement(marker: str, syms: list[str], loc: dict[str, object] | SourceLoc | None = None) -> Statement:
    return Statement(source_loc=normalize_loc(loc), marker=marker, marker_syms=syms)


def sym_locs_from_expr(expr: ExprNode | None) -> dict[str, dict[str, object]]:
    locs: dict[str, dict[str, object]] = {}
    if expr is None:
        return locs
    if expr.sym is not None and expr.sym.source_loc is not None:
        locs[expr.sym.name] = loc_to_json(expr.sym.source_loc)
    if expr.call_sym is not None and expr.call_sym.source_loc is not None:
        locs[expr.call_sym.name] = loc_to_json(expr.call_sym.source_loc)
    for child in [*expr.args, *expr.items]:
        locs.update(sym_locs_from_expr(child))
    return locs


def source_name_for_generated(name: str) -> str | None:
    return name[len(GENERATED_SYM_PREFIX) :] if is_generated_sym(name) else None


class ModuleDesugarer:
    def __init__(self, visible_syms: set[str]) -> None:
        self.reserved_syms = set(visible_syms)
        self.fresh_index = 0

    def desugar_module(self, module: Module, scope: ScopeState) -> Module | None:
        output_syms, body_output_syms, predicate_statements = self.extract_function_output_markers(module.predicate_statements)
        output_sym_set = set(output_syms)
        body_output_sym_set = set(body_output_syms)
        declaration_sym_set = set(module.declaration_syms)
        ancestor_bound_syms = set(scope.ancestor_bound_syms)
        inferred_syms = [] if module.suppress_inferred_syms else [
            sym for sym in self.infer_statement_syms(predicate_statements) if sym not in ancestor_bound_syms
        ]
        original_syms = dedupe([*module.syms, *inferred_syms])
        original_locs = self.bound_locs_for(module, original_syms)
        visible_class_names = set(scope.visible_class_names) | set(module.declared_classes)
        local_bindings: list[BindingInfo] = []
        local_syms_set: set[str] = set()
        self.reserved_syms.update(ancestor_bound_syms)

        for index, source in enumerate(original_syms):
            local_bindings.append(BindingInfo(source, original_locs[index] if index < len(original_locs) else None))
            local_syms_set.add(source)
            self.reserved_syms.add(source)

        current_scope = ScopeState(ancestor_bound_syms | local_syms_set, visible_class_names)
        local_syms = [binding.name for binding in local_bindings]
        desugared_predicates = [self.desugar_statement(statement, current_scope) for statement in predicate_statements]
        desugared_targets: list[Statement] = []
        for statement in module.target_statements:
            desugared_targets.extend(self.desugar_target_statement(statement, current_scope))
        target_inheritance_rhs = inheritance_rhs_names(desugared_targets)
        premise_binding_lhs = set() if body_output_sym_set else leading_premise_binding_lhs_names(desugared_predicates)
        target_binding_names = (output_sym_set | declaration_sym_set) - body_output_sym_set
        premise_bindings = [
            binding
            for binding in local_bindings
            if binding.name not in target_binding_names
            and binding.name not in body_output_sym_set
            and binding.name not in premise_binding_lhs
            and binding.name not in target_inheritance_rhs
        ]
        output_bindings = [binding for binding in local_bindings if binding.name in target_binding_names]
        predicates = self.implicit_predicates(premise_bindings, visible_class_names, desugared_predicates, current_scope)
        target_inheritance = self.implicit_predicates(output_bindings, visible_class_names, desugared_targets, current_scope)
        class_targets = dedupe_sym_only_facts([infix_statement(SYMBOL_SOURCE, "~", class_name, module.declared_class_locs.get(class_name)) for class_name in module.declared_classes])
        targets = [*class_targets, *target_inheritance, *desugared_targets]
        predicates.extend(desugared_predicates)
        predicates = dedupe_sym_only_facts([predicate for predicate in predicates if not is_empty_statement(predicate)])
        targets = [target for target in targets if not is_empty_statement(target)]
        if output_sym_set and len(output_syms) > 1 and not targets:
            targets.append(marker_statement(DECL_OUTPUT_MARKER, output_syms))
        if output_sym_set and len(output_syms) == 1 and not targets:
            return None

        return Module(
            type=module.type,
            syms=local_syms,
            predicate_statements=predicates,
            target_statements=targets,
            quantifier=module.quantifier,
            source_loc=module.source_loc,
            declared_classes=module.declared_classes,
            declaration_syms=module.declaration_syms,
            suppress_inferred_syms=module.suppress_inferred_syms,
            bound_sym_locs=original_locs,
        )

    def bound_locs_for(self, module: Module, syms: list[str]) -> list[dict[str, object] | None]:
        loc_by_sym: dict[str, dict[str, object] | None] = {}
        for index, sym in enumerate(module.syms):
            if sym not in loc_by_sym:
                loc_by_sym[sym] = module.bound_sym_locs[index] if index < len(module.bound_sym_locs) else None
        for statement in [*module.predicate_statements, *module.target_statements]:
            for sym, loc in statement.sym_locs.items():
                loc_by_sym.setdefault(sym, loc)
        return [loc_by_sym.get(sym) for sym in syms]

    def extract_function_output_markers(self, statements: list[Statement]) -> tuple[list[str], list[str], list[Statement]]:
        declaration_output_syms: list[str] = []
        body_output_syms: list[str] = []
        remaining: list[Statement] = []
        for statement in statements:
            marker_name = statement.marker
            if statement.sub_modules or marker_name not in {DECL_OUTPUT_MARKER, DECL_BODY_OUTPUT_MARKER}:
                remaining.append(statement)
                continue
            parsed = [sym for sym in statement.marker_syms if is_plain_sym(sym)]
            if marker_name == DECL_OUTPUT_MARKER:
                declaration_output_syms.extend(parsed)
            else:
                body_output_syms.extend(parsed)
                remaining.append(statement)
        return dedupe(declaration_output_syms), dedupe(body_output_syms), remaining

    def infer_statement_syms(self, statements: list[Statement]) -> list[str]:
        syms: list[str] = []
        for statement in statements:
            syms.extend(infer_syms_from_expr(statement.expr))
        return dedupe(syms)

    def desugar_statement(self, statement: Statement, scope: ScopeState) -> Statement:
        sub_modules: list[Module] = []
        for submodule in statement.sub_modules:
            desugared = self.desugar_module(submodule, scope)
            if desugared is None:
                continue
            sub_modules.append(desugared)
        expr = rewrite_expr(statement.expr)
        if isinstance(expr, Module_ref_expr):
            expr = Module_ref_expr(expr.source_loc, value="0") if sub_modules else None
        return Statement(
            sub_modules=sub_modules,
            source_loc=statement.source_loc,
            sym_locs=statement.sym_locs,
            source_name=statement.source_name,
            expr=expr,
            marker=statement.marker,
            marker_syms=statement.marker_syms,
        )

    def desugar_target_statement(self, statement: Statement, scope: ScopeState) -> list[Statement]:
        if not statement.sub_modules and statement.marker in {DECL_OUTPUT_MARKER, DECL_BODY_OUTPUT_MARKER}:
            return []
        return [self.desugar_statement(statement, scope)]

    def implicit_predicates(
        self,
        bindings: list[BindingInfo],
        visible_syms: set[str],
        authored_predicates: list[Statement],
        scope: ScopeState,
    ) -> list[Statement]:
        predicates: list[Statement] = []
        for binding in bindings:
            if is_generated_sym(binding.name) or binding.name in CANONICAL_INFIX_OPERATORS:
                continue
            specific_predicates = self.naming_inheritance(binding.name, visible_syms, scope, binding.loc)
            predicates.extend(specific_predicates)

        inherited_rhs = inheritance_rhs_names([*authored_predicates, *predicates])
        for binding in bindings:
            if is_generated_sym(binding.name) or binding.name in CANONICAL_INFIX_OPERATORS:
                continue
            if binding.name not in inherited_rhs:
                predicates.append(infix_statement(SYMBOL_SOURCE, "~", binding.name, binding.loc))
        return predicates

    def naming_inheritance(self, sym: str, visible_syms: set[str], scope: ScopeState, loc: dict[str, object] | None = None) -> list[Statement]:
        predicates: list[Statement] = []
        if is_bool_predicate_sym(sym):
            predicates.append(infix_statement("Bool", "~", sym, loc))
            return predicates

        source_sym = selected_inheritance_source(sym, visible_syms)
        if source_sym is not None and source_sym != sym:
            predicates.append(infix_statement(source_sym, "~", sym, loc))

        collection = self.collection_inheritance(sym, visible_syms)
        if collection is not None:
            item = self.fresh_sym(f"{sym}_item")
            predicates.append(infix_statement(collection[0], "~", sym, loc))
            item_module = Module(
                type="quantifier",
                syms=[item],
                predicate_statements=[infix_statement(item, "∈", sym, loc)],
                target_statements=[infix_statement(collection[1], "~", item, loc)],
                quantifier="∀",
                source_loc=loc,
                bound_sym_locs=[None],
            )
            desugared_item_module = self.desugar_module(item_module, scope)
            if desugared_item_module is not None:
                predicates.append(module_ref_statement(desugared_item_module, loc))
        return predicates

    def collection_inheritance(self, sym: str, visible_syms: set[str]) -> tuple[str, str] | None:
        if sym.endswith("_list"):
            source = selected_inheritance_source(sym[: -len("_list")], visible_syms)
            if source is not None:
                return ("Tuple", source)
        if sym.endswith("s") and len(sym) > 1:
            source = selected_inheritance_source(sym[:-1], visible_syms)
            if source is not None:
                return ("Set", source)
        return None

    def fresh_sym(self, preferred: str) -> str:
        candidate = preferred
        while candidate in self.reserved_syms:
            candidate = f"{preferred}{self.fresh_index}"
            self.fresh_index += 1
        self.reserved_syms.add(candidate)
        return candidate


def dedupe_sym_only_facts(values: list[Statement]) -> list[Statement]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    output: list[Statement] = []
    for value in values:
        key = sym_only_statement_key(value)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        output.append(value)
    return output


def sym_only_statement_key(statement: Statement) -> tuple[str, tuple[str, ...]] | None:
    expr = statement.expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None:
        return None
    arg_names: list[str] = []
    for arg in expr.args:
        if not isinstance(arg, Sym_expr) or arg.sym is None:
            return None
        arg_names.append(arg.sym.name)
    return expr.call_sym.name, tuple(arg_names)


def rewrite_expr(expr: ExprNode | None) -> ExprNode | None:
    # Stage1 already canonicalizes member calls and wrapper expressions.
    return expr


def is_empty_statement(statement: Statement) -> bool:
    return statement.marker is None and statement.expr is None and not statement.sub_modules


def infer_syms_from_expr(expr: ExprNode | None) -> list[str]:
    if not isinstance(expr, Call_expr) or expr.call_sym is None:
        return []
    op = expr.call_sym.name
    if op in {"=", ">", "<", ">=", "<=", "≤", "≥", "∈", "∉", "⊂", "⊄", "⊆", "⊈", "≠"} and expr.args:
        return expr_binder_names(expr.args[0])
    if op == "~" and len(expr.args) == 2:
        lhs = expr.args[0]
        if isinstance(lhs, Sym_expr) and lhs.sym is not None and lhs.sym.name in {"Function", "Predicate"}:
            return []
        rhs = expr.args[1]
        if isinstance(rhs, Sym_expr) and rhs.sym is not None and is_plain_sym(rhs.sym.name):
            return [rhs.sym.name]
    return []


def expr_binder_names(expr: ExprNode) -> list[str]:
    if isinstance(expr, Sym_expr) and expr.sym is not None and is_plain_sym(expr.sym.name):
        return [expr.sym.name]
    if isinstance(expr, Tuple_expr):
        names: list[str] = []
        for item in expr.items:
            names.extend(expr_binder_names(item))
        return names
    return []


def inheritance_rhs_names(statements: list[Statement]) -> set[str]:
    names: set[str] = set()
    for statement in statements:
        rhs = inheritance_rhs_name(statement)
        if rhs is not None:
            names.add(rhs)
    return names


def leading_premise_binding_lhs_names(statements: list[Statement]) -> set[str]:
    names: set[str] = set()
    if not statements:
        return names
    expr = statements[0].expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None or expr.call_sym.name != "=" or not expr.args:
        return names
    names.update(expr_binder_names(expr.args[0]))
    return names


def inheritance_rhs_name(statement: Statement) -> str | None:
    expr = statement.expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None or expr.call_sym.name != "~" or len(expr.args) != 2:
        return None
    rhs = expr.args[1]
    if isinstance(rhs, Sym_expr) and rhs.sym is not None and is_plain_sym(rhs.sym.name):
        return rhs.sym.name
    return None


def is_generated_sym(sym: str) -> bool:
    return sym.startswith(GENERATED_SYM_PREFIX)
