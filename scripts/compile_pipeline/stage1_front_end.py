#!/usr/bin/env python3
"""Stage 1 front-end: parse imports/source and perform surface desugaring."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import (
    DECL_BODY_OUTPUT_MARKER,
    DECL_OUTPUT_MARKER,
    Call_expr,
    ClassDecl,
    ClassFieldAssign,
    ClassFieldDecl,
    ClassMethodDecl,
    FunctionDecl,
    Module,
    Module_ref_expr,
    SourceFileAst,
    SourceModule,
    SourceStatement,
    Statement,
    SymNode,
    Sym_expr,
    Tuple_expr,
    dedupe,
    loc_to_json,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.front_end_source_loader import run_parse_ast
from compile_pipeline.front_end_desugar import run as desugar_source
from compile_pipeline.source_syntax import is_generated_sym_name, lower_head
from inheritance_sources import SYMBOL_SOURCE, selected_inheritance_source


@dataclass(frozen=True)
class FrontEndResult:
    ast: SourceFileAst
    parse_ast: SourceFileAst
    desugar_ast: SourceFileAst
    import_count: int
    diagnostics: list[dict[str, object]]

    def summary(self) -> str:
        module = self.ast.modules[0].lowered_module if self.ast.modules else None
        return json.dumps(
            {
                "stage": "stage1_front_end",
                "imports": self.import_count,
                "diagnostics": len(self.diagnostics),
                "root": {
                    "kind": getattr(module, "type", None),
                    "bound_syms": len(getattr(module, "syms", []) or []),
                    "premise_statements": len(getattr(module, "predicate_statements", []) or []),
                    "target_statements": len(getattr(module, "target_statements", []) or []),
                },
            },
            ensure_ascii=False,
        )


def run(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> FrontEndResult:
    parse_ast = parse_front_end_ast(text, base_dir, source=source, allow_imports=allow_imports)
    desugar_ast = desugar_front_end_ast(parse_ast)
    lowered_ast, diagnostics, import_count = lower_front_end_ast(
        desugar_ast,
        text=text,
        base_dir=base_dir,
        source=source,
        allow_imports=allow_imports,
    )
    if any(entry.get("type") == "error" for entry in diagnostics):
        raise CompileError(format_diagnostics(diagnostics))
    return FrontEndResult(
        ast=lowered_ast,
        parse_ast=parse_ast,
        desugar_ast=desugar_ast,
        import_count=import_count,
        diagnostics=diagnostics,
    )


def parse_front_end_ast(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> SourceFileAst:
    return run_parse_ast(text, base_dir, source=source, allow_imports=allow_imports)


def desugar_front_end_ast(parse_ast: SourceFileAst) -> SourceFileAst:
    desugared = deepcopy(parse_ast)
    for module in desugared.modules:
        desugar_source_module(module, set())
    return desugared


def desugar_source_module(module: SourceModule, visible_classes: set[str]) -> None:
    local_classes = [class_decl.name.name for class_decl in module.classes]
    current_visible = set(visible_classes) | set(local_classes)
    existing_target_keys = {inheritance_key(statement) for statement in module.target_proposition_stmts}
    for class_name in local_classes:
        statement = inherit_statement(SYMBOL_SOURCE, class_name, class_name, module.source_loc)
        if inheritance_key(statement) not in existing_target_keys:
            module.target_proposition_stmts.append(statement)
            existing_target_keys.add(inheritance_key(statement))
    for declaration in module.declarations:
        desugar_function_decl(declaration, current_visible, module.target_proposition_stmts)
    for class_decl in module.classes:
        for member in class_decl.members:
            declaration = getattr(member, "decl", None)
            if isinstance(declaration, FunctionDecl):
                desugar_function_decl(declaration, current_visible, module.target_proposition_stmts)
    for child in module.children:
        desugar_source_module(child, current_visible)


def desugar_function_decl(declaration: FunctionDecl, visible_classes: set[str], module_targets: list[SourceStatement]) -> None:
    classifier = "Predicate" if [sym.name for sym in declaration.outputs] == ["bool"] else "Function"
    function_fact = inherit_statement(classifier, declaration.name.name, declaration.name.name, declaration.name.source_loc)
    if inheritance_key(function_fact) not in {inheritance_key(statement) for statement in module_targets}:
        module_targets.append(function_fact)
    declaration.premise_proposition_stmts = [
        statement for sym in declaration.inputs for statement in implicit_inheritance_for_sym(sym, visible_classes)
    ]
    declaration.target_proposition_stmts = [
        statement for sym in declaration.outputs for statement in implicit_inheritance_for_sym(sym, visible_classes)
    ]


def implicit_inheritance_for_sym(sym: SymNode, visible_classes: set[str]) -> list[SourceStatement]:
    if sym.name.startswith("^"):
        return []
    source = selected_inheritance_source(sym.name, visible_classes)
    if source is not None and source != sym.name:
        return [inherit_statement(source, sym.name, sym.name, sym.source_loc)]
    return [inherit_statement(SYMBOL_SOURCE, sym.name, sym.name, sym.source_loc)]


def inherit_statement(lhs: str, rhs: str, source_name: str, loc: object | None) -> SourceStatement:
    loc_json = loc_to_json(loc) if loc is not None else None
    expr = Call_expr(
        loc_json,
        call_sym=SymNode("~", loc_json),
        args=[
            Sym_expr(loc_json, sym=SymNode(lhs, loc_json)),
            Sym_expr(loc_json, sym=SymNode(rhs, loc_json)),
        ],
    )
    return SourceStatement(loc_json, expr=expr)


def inheritance_key(statement: SourceStatement) -> tuple[str, str] | None:
    expr = statement.expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None or expr.call_sym.name != "~" or len(expr.args) != 2:
        return None
    lhs, rhs = expr.args
    if not isinstance(lhs, Sym_expr) or lhs.sym is None or not isinstance(rhs, Sym_expr) or rhs.sym is None:
        return None
    return lhs.sym.name, rhs.sym.name


def lower_front_end_ast(
    desugar_ast: SourceFileAst,
    *,
    text: str | None = None,
    base_dir: Path | str = ".",
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> tuple[SourceFileAst, list[dict[str, object]], int]:
    source_ast = lower_source_file_ast(desugar_ast)
    desugared = desugar_source(source_ast, Path(base_dir).resolve())
    return desugared.ast, desugared.diagnostics, desugared.import_count


def lower_source_file_ast(source_ast: SourceFileAst) -> SourceFileAst:
    lowered = deepcopy(source_ast)
    for module in lowered.modules:
        module.lowered_module = lower_source_module(module)
    return lowered


def lower_source_module(module: SourceModule) -> Module:
    predicate_statements = [lower_source_statement(statement) for statement in module.premise_proposition_stmts]
    raw_target_statements = [lower_source_statement(statement) for statement in module.target_proposition_stmts]
    early_target_statements = [statement for statement in raw_target_statements if is_inheritance_statement(statement)]
    remaining_target_statements = [statement for statement in raw_target_statements if not is_inheritance_statement(statement)]
    target_statements = [*early_target_statements]
    declared_classes: list[str] = []
    declared_class_locs: dict[str, dict[str, object]] = {}

    for class_decl in module.classes:
        declared_classes.append(class_decl.name.name)
        if class_decl.name.source_loc is not None:
            declared_class_locs[class_decl.name.name] = loc_to_json(class_decl.name.source_loc)
        for member in class_decl.members:
            if isinstance(member, ClassMethodDecl):
                target_statements.extend(lower_function_decl(member.decl))
            elif isinstance(member, ClassFieldDecl):
                target_statements.extend(lower_class_field_decl(member))
            elif isinstance(member, ClassFieldAssign):
                lowered = lower_class_field_assign(member)
                if member.premise:
                    predicate_statements.extend(lowered)
                else:
                    target_statements.extend(lowered)

    for declaration in module.declarations:
        lowered = lower_function_decl(declaration)
        if declaration.premise:
            predicate_statements.extend(lowered)
        else:
            target_statements.extend(lowered)
    target_statements.extend(remaining_target_statements)

    return Module(
        type="set" if module.type == "set" else "quantifier",
        syms=[sym.name for sym in module.bound_syms],
        predicate_statements=predicate_statements,
        target_statements=target_statements,
        quantifier=module.quantifier.name if module.quantifier is not None else ("∀" if module.type != "set" else None),
        source_loc=loc_to_json(module.source_loc) if module.source_loc is not None else None,
        declared_classes=dedupe(declared_classes),
        declaration_syms=[],
        suppress_inferred_syms=module.suppress_inferred_syms,
        bound_sym_locs=[loc_to_json(sym.source_loc) if sym.source_loc is not None else None for sym in module.bound_syms],
        bound_sym_source_names=[source_name_for_bound_sym(sym.name) for sym in module.bound_syms],
        declared_class_locs=declared_class_locs,
    )


def lower_function_decl(declaration: FunctionDecl) -> list[Statement]:
    outputs = [sym.name for sym in declaration.outputs]
    statements = [
        lower_source_statement(inherit_statement(
            "Predicate" if outputs == ["bool"] else "Function",
            declaration.name.name,
            declaration.name.name,
            declaration.name.source_loc,
        )),
        module_ref_statement(declaration_module(declaration, body=False), declaration.source_loc),
    ]
    if declaration.body_premise_proposition_stmts or declaration.body_target_proposition_stmts:
        statements.append(module_ref_statement(declaration_module(declaration, body=True), declaration.source_loc))
    return statements


def lower_class_field_decl(field: ClassFieldDecl) -> list[Statement]:
    owner_name = field.owner.name if field.owner is not None else ""
    receiver = "_" + lower_head(owner_name) if owner_name else "_class"
    output = "_" + field.name.name
    declaration = FunctionDecl(
        name=field.name,
        inputs=[SymNode(receiver, field.source_loc)],
        outputs=[SymNode(output, field.source_loc)],
        owner=field.owner,
        source_loc=field.source_loc,
    )
    return lower_function_decl(declaration)


def lower_class_field_assign(assign: ClassFieldAssign) -> list[Statement]:
    owner_name = assign.owner.name if assign.owner is not None else ""
    receiver = "_" + lower_head(owner_name) if owner_name else "_class"
    declaration = FunctionDecl(
        name=assign.name,
        inputs=[SymNode(receiver, assign.source_loc)],
        outputs=[SymNode("_" + assign.name.name, assign.source_loc)],
        owner=assign.owner,
        source_loc=assign.source_loc,
    )
    return [
        *lower_function_decl(declaration),
        module_ref_statement(class_field_assignment_module(assign, receiver), assign.source_loc),
    ]


def class_field_assignment_module(assign: ClassFieldAssign, receiver: str) -> Module:
    rhs = assign.rhs.expr if isinstance(assign.rhs, SourceStatement) else assign.rhs
    target = call_expr(
        "=",
        [
            call_expr(assign.name.name, [sym_expr(receiver, assign.source_loc)], assign.source_loc),
            rhs,
        ],
        assign.source_loc,
    )
    return Module(
        type="quantifier",
        syms=[receiver],
        predicate_statements=[
            lower_source_statement(inherit_statement(assign.owner.name if assign.owner is not None else "Class", receiver, receiver, assign.source_loc))
        ],
        target_statements=[typed_statement(target, assign.source_loc)],
        quantifier="∀",
        source_loc=loc_to_json(assign.source_loc) if assign.source_loc is not None else None,
        bound_sym_locs=[loc_to_json(assign.source_loc) if assign.source_loc is not None else None],
        bound_sym_source_names=[source_name_for_bound_sym(receiver)],
    )


def declaration_module(declaration: FunctionDecl, *, body: bool) -> Module:
    inputs = [sym.name for sym in declaration.inputs]
    outputs = [sym.name for sym in declaration.outputs]
    body_syms = [sym.name for sym in declaration.body_module.bound_syms] if body and isinstance(declaration.body_module, SourceModule) else []
    binding = declaration_binding_statement(declaration)
    predicate_statements = [
        marker_statement(DECL_BODY_OUTPUT_MARKER if body else DECL_OUTPUT_MARKER, outputs, declaration.source_loc),
        binding,
    ]
    if body:
        body_module = lower_source_module(declaration.body_module) if isinstance(declaration.body_module, SourceModule) else None
        if body_module is not None:
            predicate_statements.extend(body_module.predicate_statements)
            target_statements = body_module.target_statements
        else:
            predicate_statements.extend(lower_source_statement(statement) for statement in declaration.body_premise_proposition_stmts)
            target_statements = [lower_source_statement(statement) for statement in declaration.body_target_proposition_stmts]
    else:
        target_statements = []
    return Module(
        type="quantifier",
        syms=[*inputs, *outputs, *body_syms],
        predicate_statements=predicate_statements,
        target_statements=target_statements,
        quantifier="∀",
        source_loc=loc_to_json(declaration.body_module.source_loc)
        if body and isinstance(declaration.body_module, SourceModule) and declaration.body_module.source_loc is not None
        else (loc_to_json(declaration.source_loc) if declaration.source_loc is not None else None),
        declaration_syms=dedupe(outputs),
        bound_sym_locs=[
            loc_to_json(sym.source_loc) if sym.source_loc is not None else None
            for sym in [*declaration.inputs, *declaration.outputs, *(declaration.body_module.bound_syms if body and isinstance(declaration.body_module, SourceModule) else [])]
        ],
        bound_sym_source_names=[source_name_for_bound_sym(sym) for sym in [*inputs, *outputs, *body_syms]],
    )


def declaration_binding_statement(declaration: FunctionDecl) -> Statement:
    inputs = [sym.name for sym in declaration.inputs]
    outputs = [sym.name for sym in declaration.outputs]
    call = call_expr(declaration.name.name, [sym_expr(name, declaration.source_loc) for name in inputs], declaration.source_loc)
    if outputs == ["bool"]:
        return typed_statement(call, declaration.source_loc)
    lhs = sym_expr(outputs[0], declaration.source_loc) if len(outputs) == 1 else Tuple_expr(
        normalize_loc(declaration.source_loc),
        items=[sym_expr(name, declaration.source_loc) for name in outputs],
    )
    return typed_statement(call_expr("=", [lhs, call], declaration.source_loc), declaration.source_loc)


def lower_source_statement(statement: SourceStatement) -> Statement:
    sub_modules = [lower_source_module(module) for module in statement.sub_modules]
    expr = statement.expr
    if expr is None and sub_modules:
        expr = Module_ref_expr(normalize_loc(statement.source_loc), value="0")
    return Statement(
        sub_modules=sub_modules,
        source_loc=normalize_loc(statement.source_loc),
        sym_locs=sym_locs_from_expr(expr),
        expr=expr,
    )


def is_inheritance_statement(statement: Statement) -> bool:
    expr = statement.expr
    return isinstance(expr, Call_expr) and expr.call_sym is not None and expr.call_sym.name == "~"


def marker_statement(marker: str, syms: list[str], loc: object | None) -> Statement:
    return Statement(source_loc=normalize_loc(loc), marker=marker, marker_syms=syms)


def module_ref_statement(submodule: Module, loc: object | None) -> Statement:
    loc_json = normalize_loc(loc)
    return Statement(sub_modules=[submodule], source_loc=loc_json, expr=Module_ref_expr(loc_json, value="0"))


def typed_statement(expr, loc: object | None) -> Statement:
    return Statement(source_loc=normalize_loc(loc), sym_locs=sym_locs_from_expr(expr), expr=expr)


def sym_expr(name: str, loc: object | None):
    loc_json = normalize_loc(loc)
    return Sym_expr(loc_json, sym=SymNode(name, loc_json, generated=name.startswith("^"), source_name=source_name_for_bound_sym(name)))


def call_expr(name: str, args: list, loc: object | None):
    loc_json = normalize_loc(loc)
    return Call_expr(loc_json, call_sym=SymNode(name, loc_json), args=args)


def normalize_loc(loc: object | None) -> dict[str, object] | None:
    if loc is None:
        return None
    return loc_to_json(loc)


def sym_locs_from_expr(expr) -> dict[str, dict[str, object]]:
    locs: dict[str, dict[str, object]] = {}
    if expr is None:
        return locs
    if getattr(expr, "sym", None) is not None and expr.sym.source_loc is not None:
        locs[expr.sym.name] = loc_to_json(expr.sym.source_loc)
    if getattr(expr, "call_sym", None) is not None and expr.call_sym.source_loc is not None:
        locs[expr.call_sym.name] = loc_to_json(expr.call_sym.source_loc)
    for child in [*getattr(expr, "args", []), *getattr(expr, "items", [])]:
        locs.update(sym_locs_from_expr(child))
    return locs


def source_name_for_bound_sym(sym: str) -> str | None:
    return sym[1:] if is_generated_sym_name(sym) else None


def format_diagnostics(diagnostics: list[dict[str, object]]) -> str:
    lines = ["stage1 front-end diagnostics failed:"]
    for entry in diagnostics:
        file = str(entry.get("file", "<ast>"))
        line = int(entry.get("lineno", 0) or 0) + 1
        column = int(entry.get("col_start_no", 0) or 0) + 1
        code = str(entry.get("code", "front_end_error"))
        reason = str(entry.get("reason", "front-end diagnostic failed"))
        lines.append(f"{file}:{line}:{column}: {code}: {reason}")
    return "\n".join(lines)
