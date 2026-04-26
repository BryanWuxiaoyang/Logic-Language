from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

try:
    from semantic_parser import (
        AttributeExpr,
        BinaryExpr,
        Branch,
        CallExpr,
        Comment,
        Condition,
        Declaration,
        DelimitedExpr,
        Expr,
        ExpressionStatement,
        Heading,
        IdentifierExpr,
        Import,
        ParserError,
        Premise,
        QuantifiedExpr,
        SequenceExpr,
        Statement,
        SymbolExpr,
        TokenizerError,
        _build_semantic_index,
        _canonical_declared_name,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _is_else_identifier,
        _resolve_branch_premise_expr,
        _scoped_block_owner_class,
        _split_expanded_target_exprs,
        _statement_declared_symbols,
        _STATIC_NON_PREMISE_SYMBOLS,
        load_module_closure,
        parse_condition_text,
        program_to_source,
        render_import_path,
        resolve_import_path,
    )
except ImportError:  # pragma: no cover - module execution fallback
    from .semantic_parser import (
        AttributeExpr,
        BinaryExpr,
        Branch,
        CallExpr,
        Comment,
        Condition,
        Declaration,
        DelimitedExpr,
        Expr,
        ExpressionStatement,
        Heading,
        IdentifierExpr,
        Import,
        ParserError,
        Premise,
        QuantifiedExpr,
        SequenceExpr,
        Statement,
        SymbolExpr,
        TokenizerError,
        _build_semantic_index,
        _canonical_declared_name,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _is_else_identifier,
        _resolve_branch_premise_expr,
        _scoped_block_owner_class,
        _split_expanded_target_exprs,
        _statement_declared_symbols,
        _STATIC_NON_PREMISE_SYMBOLS,
        load_module_closure,
        parse_condition_text,
        program_to_source,
        render_import_path,
        resolve_import_path,
    )


GLOBAL_CONSTRAINT_GROUP = "__global_constraints__"


def _signature_items(expr: Expr | None) -> list[Expr]:
    if expr is None:
        return []
    if isinstance(expr, (DelimitedExpr, SequenceExpr)):
        return [item for item in expr.items if item is not None]
    return [expr]


def _normalize_symbol_name(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s*::\s*", "::", text)
    text = re.sub(r"\s*\.\s*", ".", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _expr_symbol_name(expr: Expr | None) -> str | None:
    if expr is None:
        return None
    if isinstance(expr, IdentifierExpr):
        return expr.name
    if isinstance(expr, SymbolExpr):
        return expr.value
    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return expr.attribute
        base = _expr_symbol_name(expr.base)
        if base is None:
            return None
        return f"{base}.{expr.attribute}"
    if isinstance(expr, BinaryExpr) and expr.operator == "::":
        owner, member = _extract_member_owner_and_name(expr, current_class=None)
        if owner is not None and member is not None:
            return f"{owner}::{member}"
    return _normalize_symbol_name(program_to_source(expr))


def _declared_symbol_from_expression(
    expr: Expr,
    *,
    current_class: str | None,
) -> str | None:
    if isinstance(expr, (IdentifierExpr, SymbolExpr)):
        return _expr_symbol_name(expr)

    if isinstance(expr, AttributeExpr) and expr.base is None and current_class is not None:
        return f"{current_class}::{expr.attribute}"

    if isinstance(expr, BinaryExpr) and expr.operator == "::":
        owner, member = _extract_member_owner_and_name(expr, current_class=current_class)
        if owner is not None and member is not None:
            return f"{owner}::{member}"

    return None


def _declaration_symbol_name(
    declaration: Declaration,
    *,
    current_class: str | None,
) -> str | None:
    owner_class = _declaration_owner_class(declaration, current_class=current_class)
    if owner_class is not None:
        _, member_name = _extract_member_owner_and_name(
            declaration.head,
            current_class=owner_class,
        )
        if declaration.head is None:
            member_name = "call"
        if member_name is not None:
            return f"{owner_class}::{member_name}"
    return _expr_symbol_name(declaration.head)


def _condition_from_quantified_expression(expr: QuantifiedExpr) -> Condition:
    text = program_to_source(expr)
    return parse_condition_text(text)


def _as_scope_premise(statement: Statement) -> Premise:
    if isinstance(statement, Premise):
        return Premise(
            expression=copy.deepcopy(statement.expression),
            body=[],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )
    if isinstance(statement, ExpressionStatement):
        return Premise(
            expression=copy.deepcopy(statement.expression),
            body=[],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )
    raise TypeError(f"unsupported scope statement type: {type(statement).__name__}")


def _clone_as_target(expr: Expr, *, line: int, column: int, trailing_comment: str | None) -> ExpressionStatement:
    return ExpressionStatement(
        expression=copy.deepcopy(expr),
        body=[],
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def _expand_condition_items(
    items: list[Statement],
    *,
    states: list[list[Statement]],
    quantifier: str,
) -> tuple[list[Condition], list[list[Statement]]]:
    emitted_conditions: list[Condition] = []
    active_states = [list(state) for state in states]
    index = 0

    while index < len(items):
        item = items[index]

        if isinstance(item, Comment):
            index += 1
            continue

        if isinstance(item, Branch):
            branches: list[Branch] = []
            while index < len(items) and isinstance(items[index], Branch):
                branches.append(items[index])
                index += 1

            next_states: list[list[Statement]] = []
            for state in active_states:
                prior_branch_exprs: list[Expr] = []
                for branch in branches:
                    branch_expr = _resolve_branch_premise_expr(branch, prior_branch_exprs)
                    branch_state = state + [
                        Premise(
                            expression=copy.deepcopy(branch_expr),
                            body=[],
                            line=branch.line,
                            column=branch.column,
                            trailing_comment=branch.trailing_comment,
                        )
                    ]
                    branch_emitted, branch_end_states = _expand_condition_items(
                        branch.body,
                        states=[branch_state],
                        quantifier=quantifier,
                    )
                    emitted_conditions.extend(branch_emitted)
                    next_states.extend(branch_end_states)
                    if not _is_else_identifier(branch.expression):
                        prior_branch_exprs.append(branch.expression)
            active_states = next_states
            continue

        if isinstance(item, Premise):
            next_states: list[list[Statement]] = []
            for state in active_states:
                premise_state = state + [_as_scope_premise(item)]
                nested_emitted, nested_end_states = _expand_condition_items(
                    item.body,
                    states=[premise_state],
                    quantifier=quantifier,
                )
                emitted_conditions.extend(nested_emitted)
                next_states.extend(nested_end_states)
            active_states = next_states
            index += 1
            continue

        if isinstance(item, ExpressionStatement):
            next_states: list[list[Statement]] = []
            target_exprs = _split_expanded_target_exprs(item.expression)
            for state in active_states:
                for target_expr in target_exprs:
                    emitted_conditions.append(
                        Condition(
                            quantifier=quantifier,
                            body=state
                            + [
                                _clone_as_target(
                                    target_expr,
                                    line=item.line,
                                    column=item.column,
                                    trailing_comment=item.trailing_comment,
                                )
                            ],
                            line=item.line,
                            column=item.column,
                            trailing_comment=None,
                        )
                    )

                target_state = state + [
                    Premise(
                        expression=copy.deepcopy(target_expr),
                        body=[],
                        line=item.line,
                        column=item.column,
                        trailing_comment=item.trailing_comment,
                    )
                    for target_expr in target_exprs
                ]
                nested_emitted, nested_end_states = _expand_condition_items(
                    item.body,
                    states=[target_state],
                    quantifier=quantifier,
                )
                emitted_conditions.extend(nested_emitted)
                next_states.extend(nested_end_states)
            active_states = next_states
            index += 1
            continue

        if isinstance(item, Condition):
            nested_emitted, _ = _expand_condition_items(
                item.body,
                states=active_states,
                quantifier=item.quantifier,
            )
            emitted_conditions.extend(nested_emitted)
            active_states = [state + [copy.deepcopy(item)] for state in active_states]
            index += 1
            continue

        if isinstance(item, Heading):
            nested_emitted, nested_end_states = _expand_condition_items(
                item.body,
                states=active_states,
                quantifier=quantifier,
            )
            emitted_conditions.extend(nested_emitted)
            active_states = nested_end_states
            index += 1
            continue

        if isinstance(item, Import):
            index += 1
            continue

        active_states = [state + [copy.deepcopy(item)] for state in active_states]
        index += 1

    return emitted_conditions, active_states


def _declaration_callable_head(
    declaration: Declaration,
    *,
    owner_class: str | None,
) -> Expr | None:
    if owner_class is None:
        return copy.deepcopy(declaration.head)

    _, member_name = _extract_member_owner_and_name(
        declaration.head,
        current_class=owner_class,
    )
    if declaration.head is None:
        member_name = "call"
    if member_name is None:
        return copy.deepcopy(declaration.head)

    return BinaryExpr(
        left=IdentifierExpr(name=owner_class, line=declaration.line, column=declaration.column),
        operator="::",
        right=IdentifierExpr(name=member_name, line=declaration.line, column=declaration.column),
        line=declaration.line,
        column=declaration.column,
    )


def _expand_declaration_conditions(
    declaration: Declaration,
    *,
    current_class: str | None,
    initial_state: list[Statement],
) -> list[Condition]:
    owner_class = _declaration_owner_class(declaration, current_class=current_class)
    args = [copy.deepcopy(expr) for expr in _signature_items(declaration.input_expr)]

    working_state = list(initial_state)
    if owner_class is not None and args:
        working_state.append(
            Premise(
                expression=BinaryExpr(
                    left=IdentifierExpr(
                        name=owner_class,
                        line=declaration.line,
                        column=declaration.column,
                    ),
                    operator="~",
                    right=copy.deepcopy(args[0]),
                    line=declaration.line,
                    column=declaration.column,
                ),
                body=[],
                line=declaration.line,
                column=declaration.column,
            )
        )

    body_items: list[Statement] = []
    callable_head = _declaration_callable_head(
        declaration,
        owner_class=owner_class,
    )
    mapping_expr: Expr | None = None
    if callable_head is not None and declaration.output_expr is not None:
        mapping_expr = BinaryExpr(
            left=copy.deepcopy(declaration.output_expr),
            operator="=",
            right=CallExpr(
                callee=callable_head,
                args=args,
                separators=[","] * max(0, len(args) - 1),
                delimiter="()",
                line=declaration.line,
                column=declaration.column,
            ),
            line=declaration.line,
            column=declaration.column,
        )

        # Function declarations expose their implicit call relation as scope premise.
        working_state.append(
            Premise(
                expression=copy.deepcopy(mapping_expr),
                body=[],
                line=declaration.line,
                column=declaration.column,
            )
        )

        body_items.append(
            ExpressionStatement(
                expression=copy.deepcopy(mapping_expr),
                body=[],
                line=declaration.line,
                column=declaration.column,
            )
        )

    body_items.extend(copy.deepcopy(declaration.body))
    conditions, _ = _expand_condition_items(
        body_items,
        states=[working_state],
        quantifier="∀",
    )
    return conditions


def _append_conditions(target: list[str], conditions: list[Condition]) -> None:
    for condition in conditions:
        target.append(program_to_source(condition))


def _statement_is_declaration_only(
    item: ExpressionStatement,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> bool:
    return bool(
        _statement_declared_symbols(
            item,
            current_class=current_class,
            non_premise_symbols=non_premise_symbols,
        )
    ) and not item.body


def _analyze_module(module: LoadedModule) -> tuple[list[str], list[str], list[str]]:
    semantic_index = _build_semantic_index(module.program)
    non_premise_symbols = (
        _STATIC_NON_PREMISE_SYMBOLS | frozenset(semantic_index.class_names)
    )
    direct_imports: list[str] = []
    seen_imports: set[str] = set()
    named_syms: list[str] = []
    seen_named_syms: set[str] = set()
    conds: list[str] = []

    for item in module.program.items:
        if isinstance(item, Import):
            imported_file = resolve_import_path(module.path.parent, item.module_path)
            raw_path = Path(item.module_path.strip().replace("\\", "/"))
            if raw_path.is_absolute():
                rendered = imported_file.with_suffix("").as_posix()
            else:
                rendered = render_import_path(module.path, imported_file)
            if rendered not in seen_imports:
                seen_imports.add(rendered)
                direct_imports.append(rendered)

    def append_named_symbols(statement: Statement, *, current_class: str | None) -> None:
        for symbol_name in sorted(
            _statement_declared_symbols(
                statement,
                current_class=current_class,
                non_premise_symbols=non_premise_symbols,
            )
        ):
            if symbol_name in seen_named_syms:
                continue
            seen_named_syms.add(symbol_name)
            named_syms.append(symbol_name)

    def append_statement_conditions(
        statement: Statement,
        *,
        current_class: str | None,
    ) -> None:
        initial_state: list[Statement] = []
        if current_class is not None:
            initial_state.append(
                Premise(
                    expression=IdentifierExpr(
                        name=current_class,
                        line=statement.line,
                        column=statement.column,
                    ),
                    body=[],
                    line=statement.line,
                    column=statement.column,
                )
            )

        if isinstance(statement, Condition):
            conditions, _ = _expand_condition_items(
                statement.body,
                states=[initial_state],
                quantifier=statement.quantifier,
            )
            _append_conditions(conds, conditions)
            return

        if isinstance(statement, ExpressionStatement) and isinstance(
            statement.expression, QuantifiedExpr
        ):
            quantified_condition = _condition_from_quantified_expression(statement.expression)
            conditions, _ = _expand_condition_items(
                quantified_condition.body,
                states=[initial_state],
                quantifier=quantified_condition.quantifier,
            )
            _append_conditions(conds, conditions)
            return

        conditions, _ = _expand_condition_items(
            [copy.deepcopy(statement)],
            states=[initial_state],
            quantifier="∀",
        )
        _append_conditions(conds, conditions)

    def walk_block(items: list[Statement], *, current_class: str | None) -> None:
        for item in items:
            if isinstance(item, (Comment, Import)):
                continue
            if isinstance(item, Heading):
                walk_block(item.body, current_class=current_class)
                continue
            if isinstance(item, Declaration):
                append_named_symbols(item, current_class=current_class)
                append_statement_conditions(item, current_class=current_class)
                child_class = _declaration_owner_class(item, current_class=current_class) or current_class
                if item.body:
                    walk_block(item.body, current_class=child_class)
                continue
            if isinstance(item, Condition):
                append_statement_conditions(item, current_class=current_class)
                continue
            if isinstance(item, ExpressionStatement):
                append_named_symbols(item, current_class=current_class)
                child_class = _scoped_block_owner_class(
                    item.expression,
                    item.body,
                    semantic_index,
                ) or current_class
                if not _statement_is_declaration_only(
                    item,
                    current_class=current_class,
                    non_premise_symbols=non_premise_symbols,
                ):
                    append_statement_conditions(item, current_class=current_class)
                if item.body:
                    walk_block(item.body, current_class=child_class)

    walk_block(module.program.items, current_class=None)
    return direct_imports, named_syms, conds


def _render_lines(section_name: str, values: list[str]) -> list[str]:
    lines = [section_name]
    for value in values:
        lines.extend(("    " + line) if line else "" for line in value.splitlines())
    return lines


def render_direct_module(module: LoadedModule) -> str:
    direct_imports, named_syms, conds = _analyze_module(module)
    lines: list[str] = []
    for import_path in direct_imports:
        lines.append(f"$import {import_path}")
    if direct_imports:
        lines.append("")
    lines.extend(_render_lines("@named_syms", named_syms))
    lines.append("")
    lines.extend(_render_lines("@conds", conds))
    return "\n".join(lines).rstrip() + "\n"


def render_full_module(modules: list[LoadedModule]) -> str:
    full_named_syms: list[str] = []
    seen_named_syms: set[str] = set()
    full_conds: list[str] = []
    for module in modules:
        _, named_syms, conds = _analyze_module(module)
        for symbol_name in named_syms:
            if symbol_name in seen_named_syms:
                continue
            seen_named_syms.add(symbol_name)
            full_named_syms.append(symbol_name)
        full_conds.extend(conds)

    lines: list[str] = []
    lines.extend(_render_lines("@full_named_syms", full_named_syms))
    lines.append("")
    lines.extend(_render_lines("@full_conds", full_conds))
    return "\n".join(lines).rstrip() + "\n"


def expand_module_file(
    input_file: str | Path,
    *,
    output_file: str | Path | None = None,
) -> Path:
    input_path = Path(input_file).resolve()
    output_path = (
        input_path.with_suffix(".expanded.lp")
        if output_file is None
        else Path(output_file).resolve()
    )
    modules = load_module_closure(input_path)
    output_path.write_text(render_direct_module(modules[-1]), encoding="utf-8")
    return output_path


def expand_full_module_file(
    input_file: str | Path,
    *,
    output_file: str | Path | None = None,
) -> Path:
    input_path = Path(input_file).resolve()
    output_path = (
        input_path.with_suffix(".full.expanded.lp")
        if output_file is None
        else Path(output_file).resolve()
    )
    modules = load_module_closure(input_path)
    output_path.write_text(render_full_module(modules), encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand a .lp module into explicit symbol and constraint sections, "
            "including recursive imports."
        )
    )
    parser.add_argument("input_module", help="Path to input .lp module file.")
    parser.add_argument(
        "--output",
        help="Path to output expanded .lp file (default: <input>.expanded.lp).",
    )
    args = parser.parse_args(argv)

    try:
        out = expand_module_file(
            args.input_module,
            output_file=args.output,
        )
    except (OSError, TokenizerError, ParserError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
