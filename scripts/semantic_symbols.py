from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class SymbolCollectionContext:
    non_premise_symbols: frozenset[str]
    mode: Literal["required", "exposed"]
    premise_mode: bool = False


def collect_expanded_target_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    if isinstance(expr, lp.IdentifierExpr):
        return set()
    return collect_expr_required_symbols(lp, expr, non_premise_symbols=non_premise_symbols)


def statement_required_symbols(lp, statement, *, non_premise_symbols: frozenset[str]) -> set[str]:
    if isinstance(statement, (lp.ExpressionStatement, lp.Premise, lp.Branch)):
        if isinstance(statement, lp.Premise):
            return collect_premise_required_symbols(
                lp,
                statement.expression,
                non_premise_symbols=non_premise_symbols,
            )
        return collect_expr_required_symbols(
            lp,
            statement.expression,
            non_premise_symbols=non_premise_symbols,
        )

    if isinstance(statement, lp.Declaration):
        symbols: set[str] = set()
        for expr in (statement.alias, statement.input_expr, statement.output_expr):
            symbols.update(collect_expr_required_symbols(lp, expr, non_premise_symbols=non_premise_symbols))
        return symbols

    return set()


def canonical_declared_name(lp, expr, *, current_class: str | None) -> str | None:
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    if isinstance(expr, lp.SymbolExpr):
        return expr.value
    if isinstance(expr, lp.AttributeExpr) and expr.base is None and current_class is not None:
        return expr.attribute
    if isinstance(expr, lp.BinaryExpr) and expr.operator == "::":
        _, member_name = lp._extract_member_owner_and_name(expr, current_class=current_class)
        return member_name
    return None


def declared_symbols_for_expression(
    lp,
    expr,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(expr, lp.BinaryExpr) and expr.operator == "::":
        owner_name, member_name = lp._extract_member_owner_and_name(
            expr,
            current_class=current_class,
        )
        declared_symbols: set[str] = set()
        if owner_name is not None and owner_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            declared_symbols.add(owner_name)
        if member_name is not None and member_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            declared_symbols.add(member_name)
        return declared_symbols

    declared = canonical_declared_name(lp, expr, current_class=current_class)
    if declared is not None and declared not in lp._STATIC_NON_PREMISE_SYMBOLS:
        return {declared}
    if isinstance(expr, lp.BinaryExpr) and expr.operator == "~":
        relation_name = lp._extract_relation_name(expr.right)
        if relation_name is not None and relation_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            return {relation_name}
    if isinstance(expr, lp.BinaryExpr) and expr.operator in lp._IMPLICIT_DECLARE_OPERATORS:
        return collect_assignment_target_declared_symbols(
            lp,
            expr.left,
            current_class=current_class,
            non_premise_symbols=non_premise_symbols,
        )
    return set()


def statement_declared_symbols(
    lp,
    statement,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(statement, lp.Declaration):
        declared: set[str] = set()
        owner_name = lp._declaration_owner_class(statement, current_class=current_class)
        if owner_name is not None and owner_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            declared.add(owner_name)
        head_name = canonical_declared_name(lp, statement.head, current_class=current_class)
        if head_name is not None and head_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            declared.add(head_name)
        alias_name = lp._extract_alias_name(statement.alias)
        if alias_name is not None and alias_name not in lp._STATIC_NON_PREMISE_SYMBOLS:
            declared.add(alias_name)
        return declared

    if isinstance(statement, lp.ExpressionStatement):
        return declared_symbols_for_expression(
            lp,
            statement.expression,
            current_class=current_class,
            non_premise_symbols=non_premise_symbols,
        )

    return set()


def statement_exposed_symbols(lp, statement, *, non_premise_symbols: frozenset[str]) -> set[str]:
    if isinstance(statement, (lp.ExpressionStatement, lp.Premise, lp.Branch)):
        return collect_expr_exposed_symbols(lp, statement.expression, non_premise_symbols=non_premise_symbols)

    if isinstance(statement, lp.Declaration):
        symbols: set[str] = set()
        for expr in (statement.head, statement.alias, statement.input_expr, statement.output_expr):
            symbols.update(collect_expr_exposed_symbols(lp, expr, non_premise_symbols=non_premise_symbols))
        return symbols

    return set()


def collect_module_named_symbols(
    lp,
    items,
    *,
    semantic_index,
    non_premise_symbols: frozenset[str],
    current_class: str | None = None,
) -> list[str]:
    ordered_names: list[str] = []
    seen_names: set[str] = set()

    def append_names(names) -> None:
        for name in names:
            if name in seen_names:
                continue
            seen_names.add(name)
            ordered_names.append(name)

    for item in items:
        if isinstance(item, lp.Comment):
            continue
        append_names(
            sorted(
                statement_declared_symbols(
                    lp,
                    item,
                    current_class=current_class,
                    non_premise_symbols=non_premise_symbols,
                )
            )
        )
        if isinstance(item, lp.Heading):
            append_names(
                collect_module_named_symbols(
                    lp,
                    item.body,
                    semantic_index=semantic_index,
                    non_premise_symbols=non_premise_symbols,
                    current_class=current_class,
                )
            )
            continue
        if isinstance(item, lp.ExpressionStatement):
            child_class = lp._scoped_block_owner_class(item.expression, item.body, semantic_index)
            if child_class is not None:
                append_names(
                    collect_module_named_symbols(
                        lp,
                        item.body,
                        semantic_index=semantic_index,
                        non_premise_symbols=non_premise_symbols,
                        current_class=child_class,
                    )
                )
        elif isinstance(item, lp.Declaration):
            child_class = lp._declaration_owner_class(item, current_class=current_class) or current_class
            if child_class is not None and item.body:
                append_names(
                    collect_module_named_symbols(
                        lp,
                        item.body,
                        semantic_index=semantic_index,
                        non_premise_symbols=non_premise_symbols,
                        current_class=child_class,
                    )
                )

    return ordered_names


def collect_expr_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_expr_symbols(
        lp,
        expr,
        SymbolCollectionContext(non_premise_symbols=non_premise_symbols, mode="required"),
    )


def collect_expr_exposed_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_expr_symbols(
        lp,
        expr,
        SymbolCollectionContext(non_premise_symbols=non_premise_symbols, mode="exposed"),
    )


def collect_assignment_target_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_target_symbols(
        lp,
        expr,
        SymbolCollectionContext(non_premise_symbols=non_premise_symbols, mode="required"),
    )


def collect_assignment_target_exposed_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_target_symbols(
        lp,
        expr,
        SymbolCollectionContext(non_premise_symbols=non_premise_symbols, mode="exposed"),
    )


def collect_assignment_target_declared_symbols(
    lp,
    expr,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    declared = canonical_declared_name(lp, expr, current_class=current_class)
    if declared is not None:
        return {declared}

    if isinstance(expr, (lp.SequenceExpr, lp.DelimitedExpr)):
        symbols: set[str] = set()
        for item in expr.items:
            if item is None:
                continue
            symbols.update(
                collect_assignment_target_declared_symbols(
                    lp,
                    item,
                    current_class=current_class,
                    non_premise_symbols=non_premise_symbols,
                )
            )
        return symbols
    return set()


def collect_pipe_delimited_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    required: set[str] = set()
    available: set[str] = set()
    condition_segments, target_segment = lp._canonicalize_pipe_segments(
        lp._split_condition_segments(expr)
    )

    for segment in condition_segments:
        if not segment:
            continue
        item = lp._merge_segment_expr(segment)
        required.update(
            collect_premise_required_symbols(lp, item, non_premise_symbols=non_premise_symbols)
            - available
        )
        available.update(
            collect_expr_exposed_symbols(lp, item, non_premise_symbols=non_premise_symbols)
        )

    if target_segment:
        item = lp._merge_segment_expr(target_segment)
        required.update(
            collect_premise_required_symbols(lp, item, non_premise_symbols=non_premise_symbols)
            - available
        )
    return required


def collect_premise_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_expr_symbols(
        lp,
        expr,
        SymbolCollectionContext(
            non_premise_symbols=non_premise_symbols,
            mode="required",
            premise_mode=True,
        ),
    )


def collect_premise_target_required_symbols(lp, expr, *, non_premise_symbols: frozenset[str]) -> set[str]:
    return _collect_target_symbols(
        lp,
        expr,
        SymbolCollectionContext(
            non_premise_symbols=non_premise_symbols,
            mode="required",
            premise_mode=True,
        ),
    )


def collect_enum_symbols(lp, items) -> frozenset[str]:
    enum_symbols: set[str] = set()
    for item in items:
        enum_symbols.update(_collect_node_enum_symbols(lp, item))
    return frozenset(enum_symbols)


def extract_enum_members(lp, expr) -> set[str]:
    if not isinstance(expr, lp.BinaryExpr):
        return set()
    definition = lp._extract_enum_definition(expr)
    if definition is None:
        return set()
    _, member_names = definition
    return member_names


def _collect_node_enum_symbols(lp, node) -> set[str]:
    enum_symbols: set[str] = set()
    if isinstance(node, lp.ExpressionStatement):
        enum_symbols.update(extract_enum_members(lp, node.expression))
    for child in node.children():
        enum_symbols.update(_collect_node_enum_symbols(lp, child))
    return enum_symbols


def _collect_expr_symbols(lp, expr, context: SymbolCollectionContext) -> set[str]:
    if expr is None:
        return set()

    if isinstance(expr, lp.IdentifierExpr):
        if context.premise_mode and context.mode == "required":
            return set()
        if expr.name in context.non_premise_symbols:
            return set()
        return {expr.name}

    if isinstance(expr, (lp.NumberExpr, lp.StringExpr, lp.SymbolExpr)):
        return set()

    if isinstance(expr, lp.UnaryExpr):
        return _collect_expr_symbols(lp, expr.operand, context)

    if isinstance(expr, lp.BinaryExpr):
        if expr.operator == "->":
            bound_symbols = lp._collect_lambda_bound_symbols(expr.left)
            bound_ctx = SymbolCollectionContext(
                non_premise_symbols=context.non_premise_symbols | bound_symbols,
                mode=context.mode,
                premise_mode=context.premise_mode,
            )
            if context.premise_mode:
                left_symbols = _collect_target_symbols(lp, expr.left, context) - bound_symbols
            else:
                left_symbols = _collect_expr_symbols(lp, expr.left, context) - bound_symbols
            right_symbols = _collect_expr_symbols(lp, expr.right, bound_ctx) - bound_symbols
            return left_symbols | right_symbols

        if context.premise_mode and expr.operator in {"=", "∈", "∉", "!∈", "!∉", "is", "~"}:
            return _collect_target_symbols(lp, expr.left, context) | _collect_expr_symbols(lp, expr.right, context)

        if expr.operator == "=":
            return _collect_target_symbols(lp, expr.left, context) | _collect_expr_symbols(lp, expr.right, context)

        if context.mode == "required" and expr.operator == "::":
            return _collect_expr_symbols(lp, expr.left, context)

        return _collect_expr_symbols(lp, expr.left, context) | _collect_expr_symbols(lp, expr.right, context)

    if isinstance(expr, lp.SequenceExpr):
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(_collect_expr_symbols(lp, item, context))
        return symbols

    if isinstance(expr, lp.DelimitedExpr):
        if context.mode == "required" and "|" in expr.separators:
            return collect_pipe_delimited_required_symbols(
                lp,
                expr,
                non_premise_symbols=context.non_premise_symbols,
            )
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(_collect_expr_symbols(lp, item, context))
        return symbols

    if isinstance(expr, lp.AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_expr_symbols(lp, expr.base, context)

    if isinstance(expr, lp.CallExpr):
        symbols: set[str] = set()
        if isinstance(expr.callee, lp.IdentifierExpr):
            if context.mode == "exposed":
                symbols.add(expr.callee.name)
            elif not context.premise_mode and expr.callee.name not in lp._OPAQUE_FUNCTION_NAMES:
                symbols.add(expr.callee.name)
        else:
            nested_ctx = context
            if context.premise_mode and context.mode == "required":
                nested_ctx = SymbolCollectionContext(
                    non_premise_symbols=context.non_premise_symbols,
                    mode=context.mode,
                    premise_mode=True,
                )
            symbols.update(_collect_expr_symbols(lp, expr.callee, nested_ctx))
        for arg in expr.args:
            symbols.update(_collect_expr_symbols(lp, arg, context))
        return symbols

    if isinstance(expr, lp.IndexExpr):
        return _collect_expr_symbols(lp, expr.base, context) | _collect_expr_symbols(lp, expr.index, context)

    if isinstance(expr, lp.QuantifiedExpr):
        return _collect_expr_symbols(lp, expr.body, context)

    return set()


def _collect_target_symbols(lp, expr, context: SymbolCollectionContext) -> set[str]:
    if isinstance(expr, lp.IdentifierExpr):
        if context.mode == "required":
            return set()
        if expr.name in context.non_premise_symbols:
            return set()
        return {expr.name}

    if isinstance(expr, lp.AttributeExpr):
        if expr.base is None:
            return set()
        return (
            _collect_target_symbols(lp, expr.base, context)
            if context.premise_mode
            else _collect_expr_symbols(lp, expr.base, context)
        )

    if isinstance(expr, lp.CallExpr):
        symbols: set[str] = set()
        if isinstance(expr.callee, lp.IdentifierExpr):
            if context.mode == "exposed":
                symbols.add(expr.callee.name)
            elif not context.premise_mode and expr.callee.name not in lp._OPAQUE_FUNCTION_NAMES:
                symbols.add(expr.callee.name)
        else:
            callee_fn = _collect_target_symbols if context.premise_mode else _collect_expr_symbols
            symbols.update(callee_fn(lp, expr.callee, context))
        arg_fn = collect_premise_required_symbols if context.premise_mode and context.mode == "required" else None
        for arg in expr.args:
            if arg_fn is not None:
                symbols.update(arg_fn(lp, arg, non_premise_symbols=context.non_premise_symbols))
            else:
                symbols.update(_collect_expr_symbols(lp, arg, context))
        return symbols

    if isinstance(expr, lp.IndexExpr):
        left = _collect_target_symbols(lp, expr.base, context) if context.premise_mode else _collect_expr_symbols(lp, expr.base, context)
        right = _collect_expr_symbols(lp, expr.index, context)
        return left | right

    if isinstance(expr, lp.BinaryExpr) and expr.operator == "->":
        bound_symbols = lp._collect_lambda_bound_symbols(expr.left)
        bound_ctx = SymbolCollectionContext(
            non_premise_symbols=context.non_premise_symbols | bound_symbols,
            mode=context.mode,
            premise_mode=context.premise_mode,
        )
        left = _collect_target_symbols(lp, expr.left, context) - bound_symbols
        right = _collect_expr_symbols(lp, expr.right, bound_ctx) - bound_symbols
        return left | right

    if isinstance(expr, lp.BinaryExpr) and context.mode == "required" and not context.premise_mode and expr.operator == "::":
        return _collect_expr_symbols(lp, expr.left, context)

    return _collect_expr_symbols(lp, expr, context)
