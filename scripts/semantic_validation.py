from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator


@dataclass(slots=True)
class ValidationContext:
    issues: list
    allow_condition_clauses: bool
    allow_imports: bool
    available_symbols: frozenset[str]
    non_premise_symbols: frozenset[str]
    semantic_index: object
    current_class: str | None = None


def decompose_condition(lp, condition):
    bodies, _ = decompose_condition_items(lp, condition.body, states=[[]])
    return [
        lp.Condition(
            quantifier=condition.quantifier,
            body=body,
            line=condition.line,
            column=condition.column,
            trailing_comment=condition.trailing_comment,
        )
        for body in bodies
    ]


def decompose_condition_items(lp, items, *, states):
    emitted_conditions: list[list] = []
    active_states = [list(state) for state in states]
    index = 0

    while index < len(items):
        item = items[index]

        if isinstance(item, lp.Comment):
            active_states = [state + [clone_statement(lp, item)] for state in active_states]
            index += 1
            continue

        if isinstance(item, lp.Branch):
            branches = []
            while index < len(items) and isinstance(items[index], lp.Branch):
                branches.append(items[index])
                index += 1

            branch_conditions, active_states = expand_branch_group(
                lp,
                branches,
                states=active_states,
            )
            emitted_conditions.extend(branch_conditions)
            continue

        if isinstance(item, lp.Premise):
            premise_conditions, active_states = advance_premise(
                lp,
                item,
                states=active_states,
            )
            emitted_conditions.extend(premise_conditions)
            index += 1
            continue

        if isinstance(item, lp.ExpressionStatement):
            target_conditions, active_states = advance_target(
                lp,
                item,
                states=active_states,
            )
            emitted_conditions.extend(target_conditions)
            index += 1
            continue

        active_states = [state + [clone_statement(lp, item)] for state in active_states]
        index += 1

    return emitted_conditions, active_states


def expand_branch_group(lp, branches, *, states):
    emitted_conditions: list[list] = []
    next_states: list[list] = []

    for state in states:
        prior_branch_exprs = []
        for branch in branches:
            branch_expr = resolve_branch_premise_expr(lp, branch, prior_branch_exprs)
            branch_state = state + [
                target_expr_to_premise(
                    lp,
                    branch_expr,
                    line=branch.line,
                    column=branch.column,
                    trailing_comment=branch.trailing_comment,
                )
            ]
            branch_conditions, branch_states = decompose_condition_items(
                lp,
                branch.body,
                states=[branch_state],
            )
            emitted_conditions.extend(branch_conditions)
            next_states.extend(branch_states)
            if not lp._is_else_identifier(branch.expression):
                prior_branch_exprs.append(branch.expression)

    return emitted_conditions, next_states


def advance_premise(lp, premise, *, states):
    emitted_conditions: list[list] = []
    next_states: list[list] = []

    for state in states:
        premise_state = state + [clone_premise(lp, premise)]
        premise_conditions, premise_states = decompose_condition_items(
            lp,
            premise.body,
            states=[premise_state],
        )
        emitted_conditions.extend(premise_conditions)
        next_states.extend(premise_states)

    return emitted_conditions, next_states


def advance_target(lp, target, *, states):
    emitted_conditions: list[list] = []
    next_states: list[list] = []

    for state in states:
        target_exprs = split_expanded_target_exprs(lp, target.expression)
        for target_expr in target_exprs:
            emitted_conditions.append(
                state
                + [
                    clone_target_expr(
                        lp,
                        target_expr,
                        line=target.line,
                        column=target.column,
                        trailing_comment=target.trailing_comment,
                    )
                ]
            )

        target_state = state + [
            target_expr_to_premise(
                lp,
                target_expr,
                line=target.line,
                column=target.column,
                trailing_comment=target.trailing_comment,
            )
            for target_expr in target_exprs
        ]
        nested_conditions, nested_states = decompose_condition_items(
            lp,
            target.body,
            states=[target_state],
        )
        emitted_conditions.extend(nested_conditions)
        next_states.extend(nested_states)

    return emitted_conditions, next_states


def clone_premise(lp, premise):
    return lp.Premise(
        expression=premise.expression,
        body=[],
        line=premise.line,
        column=premise.column,
        trailing_comment=premise.trailing_comment,
    )


def clone_target(lp, target):
    return lp.ExpressionStatement(
        expression=target.expression,
        body=[],
        line=target.line,
        column=target.column,
        trailing_comment=target.trailing_comment,
    )


def branch_to_premise(lp, branch):
    return lp.Premise(
        expression=branch.expression,
        body=[],
        line=branch.line,
        column=branch.column,
        trailing_comment=branch.trailing_comment,
    )


def target_to_premise(lp, target):
    return lp.Premise(
        expression=target.expression,
        body=[],
        line=target.line,
        column=target.column,
        trailing_comment=target.trailing_comment,
    )


def clone_target_expr(lp, expr, *, line: int, column: int, trailing_comment: str | None):
    return lp.ExpressionStatement(
        expression=expr,
        body=[],
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def target_expr_to_premise(lp, expr, *, line: int, column: int, trailing_comment: str | None):
    return lp.Premise(
        expression=expr,
        body=[],
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def split_expanded_target_exprs(lp, expr):
    if not isinstance(expr, lp.SequenceExpr):
        return [expr]
    return [item for item in expr.items if item is not None] or [expr]


def resolve_branch_premise_expr(lp, branch, prior_branch_exprs):
    if not lp._is_else_identifier(branch.expression):
        return branch.expression
    return build_residual_else_guard(lp, prior_branch_exprs, branch)


def build_residual_else_guard(lp, prior_branch_exprs, branch):
    negated_items = [
        negate_expr(lp, expr, line=branch.line, column=branch.column)
        for expr in prior_branch_exprs
    ]
    if not negated_items:
        return lp.IdentifierExpr(name="else", line=branch.line, column=branch.column)
    if len(negated_items) == 1:
        return negated_items[0]
    return lp.SequenceExpr(
        items=negated_items,
        separators=[","] * (len(negated_items) - 1),
        line=branch.line,
        column=branch.column,
    )


def negate_expr(lp, expr, *, line: int, column: int):
    if isinstance(expr, lp.UnaryExpr) and expr.operator == "!":
        return expr.operand
    return lp.UnaryExpr(operator="!", operand=expr, line=line, column=column)


def clone_statement(lp, statement):
    if isinstance(statement, lp.Condition):
        return lp.Condition(
            quantifier=statement.quantifier,
            body=[clone_statement(lp, item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, lp.Premise):
        return lp.Premise(
            expression=statement.expression,
            body=[clone_statement(lp, item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, lp.Branch):
        return lp.Branch(
            expression=statement.expression,
            body=[clone_statement(lp, item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, (lp.ExpressionStatement, lp.Declaration, lp.Heading, lp.Import, lp.Comment)):
        if hasattr(statement, "body"):
            return replace(statement, body=[clone_statement(lp, item) for item in statement.body])
        return replace(statement)

    return statement


def lower_condition_declaration_premise(
    lp,
    declaration,
    *,
    premise_line: int,
    premise_column: int,
    trailing_comment: str | None,
):
    if declaration.head is None:
        return declaration

    call_args = lp._signature_expr_items(declaration.input_expr)
    mapping_expr = lp.ExpressionStatement(
        expression=lp.BinaryExpr(
            left=declaration.output_expr,
            operator="=",
            right=lp.CallExpr(
                callee=declaration.head,
                args=call_args,
                separators=[","] * max(0, len(call_args) - 1),
                delimiter="()",
                line=declaration.line,
                column=declaration.column,
            ),
            line=declaration.line,
            column=declaration.column,
        ),
        body=[],
        line=declaration.line,
        column=declaration.column,
    )
    local_signature = replace(declaration, body=[], trailing_comment=None)
    quantified_body = [mapping_expr, *[clone_statement(lp, item) for item in declaration.body]]
    return lp.Premise(
        expression=declaration.head,
        body=[
            local_signature,
            lp.ExpandedCondition(
                quantifier="∀",
                body=quantified_body,
                line=declaration.line,
                column=declaration.column,
                trailing_comment=None,
            ),
        ],
        line=premise_line,
        column=premise_column,
        trailing_comment=trailing_comment,
    )


def validate_block(lp, items, context: ValidationContext) -> None:
    current_symbols = set(context.available_symbols)
    import_prefix_open = context.allow_imports

    for item in items:
        if isinstance(item, lp.Heading):
            import_prefix_open = False
            if not item.body:
                _issue(lp, context, "heading must contain an indented body", item.line, item.column)
            validate_block(
                lp,
                item.body,
                ValidationContext(
                    issues=context.issues,
                    allow_condition_clauses=False,
                    allow_imports=False,
                    available_symbols=frozenset(current_symbols),
                    non_premise_symbols=context.non_premise_symbols,
                    semantic_index=context.semantic_index,
                    current_class=context.current_class,
                ),
            )
            continue

        if isinstance(item, lp.Import):
            if not context.allow_imports or not import_prefix_open:
                _issue(lp, context, "import is only valid in the leading module import block", item.line, item.column)
            validation_error = lp.validate_import_path(item.module_path)
            if validation_error is not None:
                _issue(lp, context, validation_error, item.line, item.column)
            if item.body:
                _issue(lp, context, "import cannot have an indented body", item.line, item.column)
            continue

        if isinstance(item, lp.ExpandedCondition):
            import_prefix_open = False
            if not item.body:
                _issue(lp, context, "expanded condition must contain an indented body", item.line, item.column)
            validate_condition_body(
                lp,
                item.body,
                issues=context.issues,
                available_symbols=frozenset(current_symbols),
                enforce_target_symbol_flow=item.quantifier == "∀",
                non_premise_symbols=context.non_premise_symbols,
                semantic_index=context.semantic_index,
                current_class=context.current_class,
            )
            continue

        if isinstance(item, lp.Branch):
            import_prefix_open = False
            if not context.allow_condition_clauses:
                _issue(lp, context, "branch clause '|-' is only valid inside an expanded condition", item.line, item.column)
            if not item.body:
                _issue(lp, context, "branch clause must contain an indented body", item.line, item.column)
            validate_condition_body(
                lp,
                item.body,
                issues=context.issues,
                available_symbols=frozenset(
                    current_symbols
                    | lp._statement_declared_symbols(
                        item,
                        current_class=context.current_class,
                        non_premise_symbols=context.non_premise_symbols,
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=context.non_premise_symbols,
                semantic_index=context.semantic_index,
                current_class=context.current_class,
            )
            continue

        if isinstance(item, lp.Premise):
            import_prefix_open = False
            if not context.allow_condition_clauses:
                _issue(lp, context, "premise clause '|' is only valid inside an expanded condition", item.line, item.column)
            validate_condition_body(
                lp,
                item.body,
                issues=context.issues,
                available_symbols=frozenset(
                    current_symbols
                    | lp._statement_declared_symbols(
                        item,
                        current_class=context.current_class,
                        non_premise_symbols=context.non_premise_symbols,
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=context.non_premise_symbols,
                semantic_index=context.semantic_index,
                current_class=context.current_class,
            )
            continue

        if isinstance(item, lp.Declaration):
            import_prefix_open = False
            if item.input_expr is None or item.output_expr is None:
                _issue(lp, context, "declaration signature must contain both input and output expressions", item.line, item.column)
            owner_class = lp._declaration_owner_class(item, current_class=context.current_class)
            if owner_class is not None and owner_class not in current_symbols:
                _issue(
                    lp,
                    context,
                    f"member owner symbol {owner_class!r} must be declared before this declaration",
                    item.line,
                    item.column,
                )
            child_class = owner_class or context.current_class
            validate_condition_body(
                lp,
                item.body,
                issues=context.issues,
                available_symbols=frozenset(
                    current_symbols
                    | lp._statement_declared_symbols(
                        item,
                        current_class=context.current_class,
                        non_premise_symbols=context.non_premise_symbols,
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=context.non_premise_symbols,
                semantic_index=context.semantic_index,
                current_class=child_class,
            )
            current_symbols.update(
                lp._statement_declared_symbols(
                    item,
                    current_class=context.current_class,
                    non_premise_symbols=context.non_premise_symbols,
                )
            )
            continue

        if isinstance(item, lp.ExpressionStatement):
            import_prefix_open = False
            missing_symbols = (
                lp._statement_required_symbols(item, non_premise_symbols=context.non_premise_symbols)
                - current_symbols
            )
            if missing_symbols:
                _issue(
                    lp,
                    context,
                    "statement uses undeclared symbols: " + ", ".join(sorted(missing_symbols)),
                    item.line,
                    item.column,
                )
            child_class = lp._scoped_block_owner_class(item.expression, item.body, context.semantic_index)
            validate_block(
                lp,
                item.body,
                ValidationContext(
                    issues=context.issues,
                    allow_condition_clauses=False,
                    allow_imports=False,
                    available_symbols=frozenset(
                        current_symbols
                        | lp._statement_declared_symbols(
                            item,
                            current_class=context.current_class,
                            non_premise_symbols=context.non_premise_symbols,
                        )
                    ),
                    non_premise_symbols=context.non_premise_symbols,
                    semantic_index=context.semantic_index,
                    current_class=child_class,
                ),
            )
            current_symbols.update(
                lp._statement_declared_symbols(
                    item,
                    current_class=context.current_class,
                    non_premise_symbols=context.non_premise_symbols,
                )
            )
            continue

        if isinstance(item, lp.Comment):
            if item.body:
                _issue(lp, context, "comment cannot have an indented body", item.line, item.column)
            continue

        import_prefix_open = False
        if isinstance(item, lp.Statement):
            current_symbols.update(
                lp._statement_declared_symbols(
                    item,
                    current_class=context.current_class,
                    non_premise_symbols=context.non_premise_symbols,
                )
            )


def validate_condition_body(
    lp,
    items,
    *,
    issues: list,
    available_symbols: frozenset[str],
    enforce_target_symbol_flow: bool,
    non_premise_symbols: frozenset[str],
    semantic_index,
    current_class: str | None = None,
) -> frozenset[str]:
    current_symbols = set(available_symbols)
    branch_end_symbols: list[frozenset[str]] = []
    index = 0

    while index < len(items):
        item = items[index]
        if isinstance(item, lp.Comment):
            if item.body:
                issues.append(lp.SemanticIssue("comment cannot have an indented body", item.line, item.column))
            index += 1
            continue

        if isinstance(item, lp.Branch):
            branches: list = []
            while index < len(items) and isinstance(items[index], lp.Branch):
                branches.append(items[index])
                index += 1

            validate_branch_group(lp, branches, issues)
            prior_branch_exprs: list = []
            for branch in branches:
                if not branch.body:
                    issues.append(lp.SemanticIssue("branch clause must contain an indented body", branch.line, branch.column))
                branch_expr = lp._resolve_branch_premise_expr(branch, prior_branch_exprs)
                branch_symbols = set(current_symbols) | lp._collect_expr_exposed_symbols(
                    branch_expr,
                    non_premise_symbols=non_premise_symbols,
                )
                branch_end_symbols.append(
                    validate_condition_body(
                        lp,
                        branch.body,
                        issues=issues,
                        available_symbols=frozenset(branch_symbols),
                        enforce_target_symbol_flow=enforce_target_symbol_flow,
                        non_premise_symbols=non_premise_symbols,
                        semantic_index=semantic_index,
                        current_class=current_class,
                    )
                )
                if not is_else_identifier(lp, branch.expression):
                    prior_branch_exprs.append(branch.expression)
            continue

        if branch_end_symbols:
            current_symbols = merge_branch_symbol_sets(branch_end_symbols, fallback=current_symbols)
            branch_end_symbols.clear()

        if isinstance(item, lp.Premise):
            if statement_contains_reserved_else(lp, item):
                append_reserved_else_issue(lp, item, issues)
            premise_symbols = set(current_symbols) | lp._statement_exposed_symbols(
                item,
                non_premise_symbols=non_premise_symbols,
            )
            if item.body:
                validate_condition_body(
                    lp,
                    item.body,
                    issues=issues,
                    available_symbols=frozenset(premise_symbols),
                    enforce_target_symbol_flow=enforce_target_symbol_flow,
                    non_premise_symbols=non_premise_symbols,
                    semantic_index=semantic_index,
                    current_class=current_class,
                )
            current_symbols = premise_symbols
            index += 1
            continue

        if statement_contains_reserved_else(lp, item):
            append_reserved_else_issue(lp, item, issues)

        target_exprs = lp._split_expanded_target_exprs(item.expression) if isinstance(item, lp.ExpressionStatement) else None

        if enforce_target_symbol_flow:
            _validate_target_flow(
                lp,
                item,
                target_exprs,
                current_symbols,
                issues,
                non_premise_symbols=non_premise_symbols,
            )

        next_symbols = set(current_symbols)
        if target_exprs is None:
            next_symbols.update(
                lp._statement_exposed_symbols(item, non_premise_symbols=non_premise_symbols)
            )
        else:
            for target_expr in target_exprs:
                next_symbols.update(
                    lp._collect_expr_exposed_symbols(
                        target_expr,
                        non_premise_symbols=non_premise_symbols,
                    )
                )

        if isinstance(item, lp.ExpandedCondition):
            if not item.body:
                issues.append(lp.SemanticIssue("expanded condition must contain an indented body", item.line, item.column))
            validate_condition_body(
                lp,
                item.body,
                issues=issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=item.quantifier == "∀",
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
                current_class=current_class,
            )
        elif isinstance(item, lp.Declaration):
            if item.input_expr is None or item.output_expr is None:
                issues.append(lp.SemanticIssue("declaration signature must contain both input and output expressions", item.line, item.column))
            validate_condition_body(
                lp,
                item.body,
                issues=issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=False,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
                current_class=lp._declaration_owner_class(item, current_class=current_class) or current_class,
            )
        elif isinstance(item, lp.ExpressionStatement):
            validate_condition_body(
                lp,
                item.body,
                issues=issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=enforce_target_symbol_flow,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
                current_class=lp._scoped_block_owner_class(item.expression, item.body, semantic_index) or current_class,
            )
        elif isinstance(item, lp.Heading):
            if not item.body:
                issues.append(lp.SemanticIssue("heading must contain an indented body", item.line, item.column))
            validate_block(
                lp,
                item.body,
                ValidationContext(
                    issues=issues,
                    allow_condition_clauses=False,
                    allow_imports=False,
                    available_symbols=frozenset(next_symbols),
                    non_premise_symbols=non_premise_symbols,
                    semantic_index=semantic_index,
                    current_class=current_class,
                ),
            )
        elif isinstance(item, lp.Import):
            issues.append(lp.SemanticIssue("import is only valid at module root scope", item.line, item.column))
            validation_error = lp.validate_import_path(item.module_path)
            if validation_error is not None:
                issues.append(lp.SemanticIssue(validation_error, item.line, item.column))
            if item.body:
                issues.append(lp.SemanticIssue("import cannot have an indented body", item.line, item.column))

        current_symbols = next_symbols
        index += 1

    if branch_end_symbols:
        current_symbols = merge_branch_symbol_sets(branch_end_symbols, fallback=current_symbols)

    return frozenset(current_symbols)


def merge_branch_symbol_sets(branch_sets: list[frozenset[str]], *, fallback: set[str]) -> frozenset[str]:
    if not branch_sets:
        return frozenset(fallback)
    merged = set(branch_sets[0])
    for branch_set in branch_sets[1:]:
        merged.intersection_update(branch_set)
    return frozenset(merged)


def validate_branch_group(lp, branches, issues: list) -> None:
    else_indexes = [index for index, branch in enumerate(branches) if is_else_identifier(lp, branch.expression)]
    if else_indexes:
        if len(branches) == 1:
            issues.append(lp.SemanticIssue("'else' branch requires at least one preceding branch", branches[0].line, branches[0].column))
        first_else = else_indexes[0]
        if first_else != len(branches) - 1:
            issues.append(lp.SemanticIssue("'else' branch must be the final branch in its group", branches[first_else].line, branches[first_else].column))
        for extra_else in else_indexes[1:]:
            issues.append(lp.SemanticIssue("only one 'else' branch is allowed in a branch group", branches[extra_else].line, branches[extra_else].column))

    for branch in branches:
        if statement_contains_reserved_else(lp, branch) and not is_else_identifier(lp, branch.expression):
            append_reserved_else_issue(lp, branch, issues)


def statement_contains_reserved_else(lp, statement) -> bool:
    if isinstance(statement, lp.Branch):
        return expr_contains_identifier(lp, statement.expression, "else") and not is_else_identifier(lp, statement.expression)
    if isinstance(statement, (lp.ExpressionStatement, lp.Premise)):
        return expr_contains_identifier(lp, statement.expression, "else")
    if isinstance(statement, lp.Declaration):
        return any(expr_contains_identifier(lp, expr, "else") for expr in (statement.head, statement.alias, statement.input_expr, statement.output_expr))
    return False


def append_reserved_else_issue(lp, statement, issues: list) -> None:
    issues.append(lp.SemanticIssue("'else' is reserved for the final branch guard '|- else'", statement.line, statement.column))


def expr_contains_identifier(lp, expr, name: str) -> bool:
    if expr is None:
        return False
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name == name
    if isinstance(expr, lp.UnaryExpr):
        return expr_contains_identifier(lp, expr.operand, name)
    if isinstance(expr, lp.BinaryExpr):
        return expr_contains_identifier(lp, expr.left, name) or expr_contains_identifier(lp, expr.right, name)
    if isinstance(expr, (lp.SequenceExpr, lp.DelimitedExpr)):
        return any(expr_contains_identifier(lp, item, name) for item in expr.items)
    if isinstance(expr, lp.AttributeExpr):
        return expr_contains_identifier(lp, expr.base, name)
    if isinstance(expr, lp.CallExpr):
        return expr_contains_identifier(lp, expr.callee, name) or any(expr_contains_identifier(lp, arg, name) for arg in expr.args)
    if isinstance(expr, lp.IndexExpr):
        return expr_contains_identifier(lp, expr.base, name) or expr_contains_identifier(lp, expr.index, name)
    if isinstance(expr, lp.QuantifiedExpr):
        return expr_contains_identifier(lp, expr.body, name)
    return False


def is_else_identifier(lp, expr) -> bool:
    return isinstance(expr, lp.IdentifierExpr) and expr.name == "else"


def validate_program_semantics(lp, root_node, issues: list, *, non_premise_symbols: frozenset[str], semantic_index) -> None:
    validate_function_inheritance_relations(lp, issues, semantic_index=semantic_index)

    for statement, in_condition in walk_statements(lp, root_node, in_condition=False):
        if not in_condition and statement_contains_reserved_else(lp, statement):
            append_reserved_else_issue(lp, statement, issues)

        for expr in walk_exprs(lp, statement):
            if isinstance(expr, lp.BinaryExpr) and lp._is_custom_operator_alias(expr.operator):
                validate_custom_operator_usage(lp, expr, issues, semantic_index=semantic_index)
            if isinstance(expr, lp.CallExpr):
                validate_call_expression(lp, expr, issues, semantic_index=semantic_index)


def walk_statements(lp, node, *, in_condition: bool) -> Iterator[tuple[object, bool]]:
    if isinstance(node, lp.Program):
        for item in node.items:
            yield from walk_statements(lp, item, in_condition=in_condition)
        return
    if not isinstance(node, lp.Statement):
        return
    yield node, in_condition
    child_in_condition = in_condition or isinstance(node, (lp.Condition, lp.Premise, lp.Branch))
    for child in node.body:
        yield from walk_statements(lp, child, in_condition=child_in_condition)


def walk_exprs(lp, node) -> Iterator[object]:
    if isinstance(node, lp.Expr):
        yield node
    for child in node.children():
        yield from walk_exprs(lp, child)


def validate_function_inheritance_relations(lp, issues: list, *, semantic_index) -> None:
    for parent_name, child_name in sorted(semantic_index.function_inheritance_relations):
        parent_shapes = {
            (signature.input_shape, signature.output_shape)
            for signature in semantic_index.function_signatures_by_name.get(parent_name, [])
        }
        child_shapes = {
            (signature.input_shape, signature.output_shape)
            for signature in semantic_index.function_signatures_by_name.get(child_name, [])
        }
        if parent_shapes and child_shapes and not parent_shapes.isdisjoint(child_shapes):
            continue
        line = 1
        column = 1
        if semantic_index.function_signatures_by_name.get(child_name):
            signature = semantic_index.function_signatures_by_name[child_name][0]
            line = signature.line
            column = signature.column
        issues.append(lp.SemanticIssue(
            "function inheritance requires matching signatures between "
            f"{parent_name} and {child_name}",
            line,
            column,
        ))


def validate_custom_operator_usage(lp, expr, issues: list, *, semantic_index) -> None:
    alias_specs = semantic_index.operator_aliases.get(expr.operator, [])
    if any(signature.call_arity() == 1 or signature.arity == 2 for signature in alias_specs):
        return
    issues.append(lp.SemanticIssue(f"custom operator {expr.operator!r} has no matching alias declaration", expr.line, expr.column))


def validate_call_expression(lp, expr, issues: list, *, semantic_index) -> None:
    signatures = candidate_call_signatures(lp, expr.callee, semantic_index=semantic_index)
    if not signatures:
        return

    arg_counts = call_arg_count_options(lp, expr)
    if arg_counts is None:
        matching_signatures = list(signatures)
    else:
        matching_signatures = [signature for signature in signatures if signature.call_arity() in arg_counts]

    if not matching_signatures:
        if isinstance(expr.callee, lp.AttributeExpr) and any(signature.call_arity() == 0 for signature in signatures):
            return
        actual_count = len([arg for arg in expr.args if arg is not None])
        issues.append(lp.SemanticIssue(
            f"call arity mismatch: expected {format_expected_arities(signatures)}, got {actual_count}",
            expr.line,
            expr.column,
        ))
        return

    if arg_counts is None:
        return

    for signature in matching_signatures:
        violation = find_subclass_dispatch_violation(lp, expr, signature=signature, semantic_index=semantic_index)
        if violation is None:
            return

    expected_parent_class, actual_child_class = find_subclass_dispatch_violation(
        lp,
        expr,
        signature=matching_signatures[0],
        semantic_index=semantic_index,
    ) or (None, None)
    if expected_parent_class is None or actual_child_class is None:
        return

    issues.append(lp.SemanticIssue(
        "direct subclass-to-parent call dispatch is not allowed; "
        f"rebind {actual_child_class}-typed symbols to {expected_parent_class}-typed "
        "symbols before the call",
        expr.line,
        expr.column,
    ))


def call_arg_count_options(lp, expr) -> set[int] | None:
    total = 0
    for arg in expr.args:
        if arg is None:
            continue
        expanded = expanded_arg_width(lp, arg)
        if expanded is None:
            return None
        total += expanded
    return {total}


def expanded_arg_width(lp, expr) -> int | None:
    if isinstance(expr, lp.UnaryExpr) and expr.operator == "*":
        operand = expr.operand
        if isinstance(operand, (lp.DelimitedExpr, lp.SequenceExpr)):
            return len([item for item in operand.items if item is not None])
        return None
    return 1


def candidate_call_signatures(lp, callee, *, semantic_index) -> list:
    if isinstance(callee, lp.IdentifierExpr):
        if callee.name in lp._OPAQUE_FUNCTION_NAMES:
            return []
        signatures = list(semantic_index.function_signatures_by_name.get(callee.name, []))
        if looks_like_class_identifier(lp, callee.name, semantic_index):
            owner_candidates = [callee.name, *parent_classes_for(lp, callee.name, semantic_index)]
            for owner_class in owner_candidates:
                signatures.extend(semantic_index.member_signatures_by_key.get((owner_class, "call"), []))
        return signatures

    if isinstance(callee, lp.AttributeExpr):
        receiver_class = infer_expr_class(lp, callee.base, semantic_index=semantic_index, allow_uppercase_fallback=True)
        if receiver_class is not None:
            signatures: list = []
            owner_candidates = [receiver_class, *parent_classes_for(lp, receiver_class, semantic_index)]
            for owner_class in owner_candidates:
                signatures.extend(semantic_index.member_signatures_by_key.get((owner_class, callee.attribute), []))
            if signatures:
                return signatures

        fallback_signatures: list = []
        for (owner_class, member_name), member_signatures in semantic_index.member_signatures_by_key.items():
            if member_name != callee.attribute:
                continue
            fallback_signatures.extend(member_signatures)
        return fallback_signatures

    return []


def format_expected_arities(signatures: list) -> str:
    return ", ".join(str(arity) for arity in sorted({sig.call_arity() for sig in signatures}))


def find_subclass_dispatch_violation(lp, expr, *, signature, semantic_index) -> tuple[str, str] | None:
    expected_classes = signature.call_arg_classes()
    call_args = [arg for arg in expr.args if arg is not None]
    for expected_class, arg in zip(expected_classes, call_args):
        if expected_class is None:
            continue
        actual_class = infer_expr_class(lp, arg, semantic_index=semantic_index, allow_uppercase_fallback=True)
        if actual_class is None or actual_class == expected_class:
            continue
        if is_subclass_of(lp, expected_class, actual_class, semantic_index=semantic_index):
            return expected_class, actual_class
    return None


def parent_classes_for(lp, class_name: str, semantic_index) -> tuple[str, ...]:
    parents_by_child: dict[str, tuple[str, ...]] = {}
    for parent_class, child_class in semantic_index.class_inheritance_relations:
        parents_by_child.setdefault(child_class, ())
        parents_by_child[child_class] = tuple(sorted(set(parents_by_child[child_class]) | {parent_class}))
    return lp._reachable_class_relations(parents_by_child, class_name, transitive=True)


def is_subclass_of(lp, parent_class: str, child_class: str, *, semantic_index) -> bool:
    if parent_class == child_class:
        return False
    return parent_class in parent_classes_for(lp, child_class, semantic_index)


def infer_expr_class(lp, expr, *, semantic_index, allow_uppercase_fallback: bool) -> str | None:
    if isinstance(expr, lp.IdentifierExpr):
        return infer_symbol_class_name(lp, expr.name, semantic_index=semantic_index, allow_uppercase_fallback=allow_uppercase_fallback)
    return None


def infer_symbol_class_name(lp, name: str, *, semantic_index, allow_uppercase_fallback: bool) -> str | None:
    explicit_classes = {
        parent_class
        for parent_class, symbol_name in semantic_index.symbol_inheritance_relations
        if symbol_name == name
    }
    if len(explicit_classes) == 1:
        return next(iter(explicit_classes))

    candidates = class_candidates_from_name(name)
    for candidate in candidates:
        if candidate in semantic_index.class_names:
            return candidate
    if allow_uppercase_fallback:
        for candidate in candidates:
            if looks_like_class_identifier(lp, candidate, semantic_index):
                return candidate
    return None


def class_candidates_from_name(name: str) -> tuple[str, ...]:
    seen: set[str] = set()
    pending = [name]
    candidates: list[str] = []
    while pending:
        current = pending.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        candidates.append(current)
        trimmed = current.rstrip("'")
        if trimmed != current:
            pending.append(trimmed)
            continue
        digit_trimmed = current.rstrip("0123456789")
        if digit_trimmed and digit_trimmed != current:
            pending.append(digit_trimmed)
        if current.endswith("_list") and len(current) > len("_list"):
            pending.append(current[: -len("_list")])
        if current.endswith("s") and len(current) > 1:
            pending.append(current[:-1])
        if "_" in current:
            parts = [part for part in current.split("_") if part]
            if parts:
                pending.append(parts[-1])
                pending.append(parts[0])
    return tuple(candidates)


def looks_like_class_identifier(lp, name: str, semantic_index) -> bool:
    return lp._looks_like_class_identifier(name, semantic_index)


def _validate_target_flow(lp, item, target_exprs, current_symbols, issues, *, non_premise_symbols: frozenset[str]) -> None:
    if target_exprs is not None:
        for target_expr in target_exprs:
            missing_symbols = (
                lp._collect_expanded_target_required_symbols(
                    target_expr,
                    non_premise_symbols=non_premise_symbols,
                )
                - current_symbols
            )
            if missing_symbols:
                issues.append(lp.SemanticIssue(
                    "expanded ∀ target uses symbols not available from prior premises: "
                    + ", ".join(sorted(missing_symbols)),
                    target_expr.line,
                    target_expr.column,
                ))
        return

    missing_symbols = lp._statement_required_symbols(item, non_premise_symbols=non_premise_symbols) - current_symbols
    if missing_symbols:
        issues.append(lp.SemanticIssue(
            "expanded ∀ target uses symbols not available from prior premises: "
            + ", ".join(sorted(missing_symbols)),
            item.line,
            item.column,
        ))


def _issue(lp, context: ValidationContext, message: str, line: int, column: int) -> None:
    context.issues.append(lp.SemanticIssue(message, line, column))
