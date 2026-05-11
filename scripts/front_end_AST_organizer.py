#!/usr/bin/env python3
"""Organize source-preserving front-end AST and render module text."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import (
    Call_expr,
    Char_literal_expr,
    ClassDecl,
    ClassFieldAssign,
    ClassFieldDecl,
    ClassMethodDecl,
    ExprNode,
    FunctionDecl,
    Literal_expr,
    Module_ref_expr,
    Set_expr,
    SourceFileAst,
    SourceModule,
    SourceStatement,
    String_literal_expr,
    Sym_expr,
    Tuple_expr,
    Value_literal_expr,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.stage1_front_end import parse_front_end_ast


def organize_module_text(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> str:
    ast = parse_front_end_ast(text, base_dir, source=source, allow_imports=allow_imports)
    return render_source_file_ast(organize_parse_ast(ast))


def organize_parse_ast(parse_ast: SourceFileAst) -> SourceFileAst:
    organized = deepcopy(parse_ast)
    organized.modules = [organize_source_module(module) for module in organized.modules]
    return organized


def organize_source_module(module: SourceModule) -> SourceModule:
    module = deepcopy(module)
    module.children = [organize_source_module(child) for child in module.children]
    module.premise_proposition_stmts = [organize_statement(stmt) for stmt in module.premise_proposition_stmts]
    module.target_proposition_stmts = [organize_statement(stmt) for stmt in module.target_proposition_stmts]

    class_order: list[str] = []
    classes_by_name: dict[str, ClassDecl] = {}
    for class_decl in module.classes:
        name = class_decl.name.name
        if name not in classes_by_name:
            classes_by_name[name] = ClassDecl(class_decl.name, source_loc=class_decl.source_loc)
            class_order.append(name)
        classes_by_name[name].members.extend(class_decl.members)

    remaining_declarations: list[FunctionDecl] = []
    for declaration in module.declarations:
        if declaration.owner is not None:
            owner = declaration.owner.name
            if owner not in classes_by_name:
                classes_by_name[owner] = ClassDecl(declaration.owner, source_loc=declaration.source_loc)
                class_order.append(owner)
            classes_by_name[owner].members.append(ClassMethodDecl(declaration, source_loc=declaration.source_loc))
        else:
            remaining_declarations.append(declaration)

    grouped_declarations: list[FunctionDecl] = []
    seen_functions: set[str] = set()
    for declaration in remaining_declarations:
        name = declaration.name.name
        if name in seen_functions:
            continue
        seen_functions.add(name)
        grouped_declarations.extend(item for item in remaining_declarations if item.name.name == name)

    class_names = set(class_order)
    class_inheritance, other_targets = partition_class_inheritance(module.target_proposition_stmts, class_names)
    ordered_classes: list[ClassDecl] = []
    for name in class_order:
        inherited_members = classes_by_name[name].members
        ordered_classes.append(ClassDecl(classes_by_name[name].name, inherited_members, classes_by_name[name].source_loc))

    module.classes = ordered_classes
    module.declarations = grouped_declarations
    module.target_proposition_stmts = [*class_inheritance, *other_targets]
    module.statements = [*module.premise_proposition_stmts, *module.target_proposition_stmts]
    return module


def organize_statement(statement: SourceStatement) -> SourceStatement:
    statement = deepcopy(statement)
    statement.sub_modules = [organize_source_module(module) for module in statement.sub_modules]
    return statement


def partition_class_inheritance(statements: list[SourceStatement], class_names: set[str]) -> tuple[list[SourceStatement], list[SourceStatement]]:
    class_inheritance: list[SourceStatement] = []
    remaining: list[SourceStatement] = []
    for statement in statements:
        rhs = inheritance_rhs_name(statement)
        if rhs in class_names:
            class_inheritance.append(statement)
        else:
            remaining.append(statement)
    return class_inheritance, remaining


def inheritance_rhs_name(statement: SourceStatement) -> str | None:
    expr = statement.expr
    if not isinstance(expr, Call_expr) or expr.call_sym is None or expr.call_sym.name != "~" or len(expr.args) != 2:
        return None
    rhs = expr.args[1]
    if isinstance(rhs, Sym_expr) and rhs.sym is not None:
        return rhs.sym.name
    return None


def render_source_file_ast(ast: SourceFileAst) -> str:
    return "\n".join(render_source_module(module, top_level=True) for module in ast.modules).rstrip() + "\n"


def render_source_module(module: SourceModule, *, top_level: bool = False, indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    if not top_level:
        opener = module.quantifier.name if module.quantifier is not None else ("{" if module.type == "set" else "∀")
        lines.append(f"{prefix}{opener}{{")
        indent += 2
        prefix = " " * indent
    if module.bound_syms:
        lines.append(f"{prefix}| {', '.join(sym.name for sym in module.bound_syms)}")
    for statement in module.premise_proposition_stmts:
        lines.append(f"{prefix}| {render_source_statement(statement, indent).strip()}")
    for statement in module.target_proposition_stmts:
        lines.append(f"{prefix}{render_source_statement(statement, indent).strip()}")
    for class_decl in module.classes:
        lines.extend(render_class_decl(class_decl, indent))
    for declaration in module.declarations:
        lines.extend(render_function_decl(declaration, indent=indent))
    for child in module.children:
        lines.append(render_source_module(child, indent=indent))
    if not top_level:
        lines.append(" " * (indent - 2) + "}")
    return "\n".join(lines)


def render_class_decl(class_decl: ClassDecl, indent: int = 0) -> list[str]:
    prefix = " " * indent
    lines = [f"{prefix}{class_decl.name.name}"]
    for member in class_decl.members:
        if isinstance(member, ClassMethodDecl):
            lines.extend(render_function_decl(member.decl, indent=indent + 4, class_member=True))
        elif isinstance(member, ClassFieldDecl):
            lines.append(f"{' ' * (indent + 4)}::{member.name.name}")
        elif isinstance(member, ClassFieldAssign):
            rhs = render_expr(member.rhs) if isinstance(member.rhs, ExprNode) else ""
            lines.append(f"{' ' * (indent + 4)}::{member.name.name} = {rhs}".rstrip())
    return lines


def render_function_decl(declaration: FunctionDecl, *, indent: int = 0, class_member: bool = False) -> list[str]:
    prefix = " " * indent
    if class_member:
        name = f"::{declaration.name.name}"
    elif declaration.owner is not None:
        name = f"{declaration.owner.name}::{declaration.name.name}"
    else:
        name = declaration.name.name
    header = f"{prefix}{name}: {render_signature_terms(declaration.inputs)} => {render_signature_terms(declaration.outputs)}"
    lines = [header]
    for statement in declaration.body_premise_proposition_stmts:
        lines.append(f"{prefix}    | {render_source_statement(statement, indent + 4).strip()}")
    body_targets = declaration.body_target_proposition_stmts or [
        statement for statement in declaration.body if statement not in declaration.body_premise_proposition_stmts
    ]
    for statement in body_targets:
        lines.append(f"{prefix}    {render_source_statement(statement, indent + 4).strip()}")
    return lines


def render_signature_terms(terms) -> str:
    names = [term.name for term in terms]
    if len(names) == 1:
        return names[0]
    return f"({', '.join(names)})"


def render_source_statement(statement: SourceStatement, indent: int = 0) -> str:
    if statement.sub_modules and statement.expr is None:
        return "\n".join(render_source_module(module, indent=indent) for module in statement.sub_modules)
    if statement.expr is not None:
        return render_expr(statement.expr)
    if statement.sub_modules:
        return "\n".join(render_source_module(module, indent=indent) for module in statement.sub_modules)
    return ""


def render_expr(expr) -> str:
    if isinstance(expr, SourceStatement):
        return render_source_statement(expr)
    if isinstance(expr, Sym_expr) and expr.sym is not None:
        return expr.sym.name
    if isinstance(expr, Call_expr) and expr.call_sym is not None:
        args = [render_expr(arg) for arg in expr.args]
        if expr.call_sym.name in {"~", "=", "!=", "≠", ">=", "≥", "<=", "≤", ">", "<", "∈", "∉", "⊂", "⊄", "⊆", "⊈"} and len(args) == 2:
            return f"{args[0]} {expr.call_sym.name} {args[1]}"
        if expr.call_sym.name == "!" and len(args) == 1:
            return f"!{args[0]}"
        return f"{expr.call_sym.name}({', '.join(args)})"
    if isinstance(expr, Tuple_expr):
        return f"({', '.join(render_expr(item) for item in expr.items)})"
    if isinstance(expr, Set_expr):
        return "{" + ", ".join(render_expr(item) for item in expr.items) + "}"
    if isinstance(expr, Char_literal_expr):
        return repr(expr.value or "")
    if isinstance(expr, String_literal_expr):
        return repr(expr.value or "")
    if isinstance(expr, Value_literal_expr):
        return str(expr.value or "")
    if isinstance(expr, Literal_expr):
        return str(expr.value or "")
    if isinstance(expr, Module_ref_expr):
        return ""
    return str(getattr(expr, "value", "") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize logic-language front-end parse AST and print module text.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text to organize; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    args = parser.parse_args()

    if args.text is not None:
        source_text = args.text
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    elif args.file is not None:
        source_text = args.file.read_text(encoding="utf-8")
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
        allow_imports = True
    else:
        source_text = sys.stdin.read()
        source_name = "__stdin__"
        base_dir = args.base_dir or Path.cwd()
        allow_imports = True
    try:
        sys.stdout.write(organize_module_text(source_text, base_dir, source=source_name, allow_imports=allow_imports))
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
