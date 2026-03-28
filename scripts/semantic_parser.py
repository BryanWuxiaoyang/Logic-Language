from __future__ import annotations

import argparse
import pprint
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Iterator

try:
    from tokenizer import Token, TokenStream, TokenizerError, tokenize_text, tokenizer
except ImportError:  # pragma: no cover - module execution fallback
    from .tokenizer import Token, TokenStream, TokenizerError, tokenize_text, tokenizer


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    message: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ClassInheritanceRelation:
    class_name: str
    direct_parent_classes: tuple[str, ...]
    parent_classes: tuple[str, ...]
    direct_sub_classes: tuple[str, ...]
    sub_classes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassInheritanceGraph:
    parents_by_child: dict[str, tuple[str, ...]]
    children_by_parent: dict[str, tuple[str, ...]]

    def class_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.parents_by_child) | set(self.children_by_parent))
        )

    def relations(self) -> tuple[tuple[str, str], ...]:
        relations: list[tuple[str, str]] = []
        for parent in sorted(self.children_by_parent):
            for child in self.children_by_parent[parent]:
                relations.append((parent, child))
        return tuple(relations)

    def parent_classes(
        self,
        class_name: str,
        *,
        transitive: bool = True,
    ) -> tuple[str, ...]:
        return _reachable_class_relations(
            self.parents_by_child,
            class_name,
            transitive=transitive,
        )

    def sub_classes(
        self,
        class_name: str,
        *,
        transitive: bool = True,
    ) -> tuple[str, ...]:
        return _reachable_class_relations(
            self.children_by_parent,
            class_name,
            transitive=transitive,
        )

    def relation_for(self, class_name: str) -> ClassInheritanceRelation:
        return ClassInheritanceRelation(
            class_name=class_name,
            direct_parent_classes=self.parent_classes(class_name, transitive=False),
            parent_classes=self.parent_classes(class_name, transitive=True),
            direct_sub_classes=self.sub_classes(class_name, transitive=False),
            sub_classes=self.sub_classes(class_name, transitive=True),
        )


@dataclass(frozen=True, slots=True)
class SignatureSpec:
    name: str
    input_shape: str
    output_shape: str
    arity: int
    arg_classes: tuple[str | None, ...]
    owner_class: str | None
    alias: str | None
    line: int
    column: int

    def call_arity(self) -> int:
        if (
            self.owner_class is not None
            and self.arg_classes
            and self.arg_classes[0] == self.owner_class
        ):
            return max(0, self.arity - 1)
        return self.arity

    def call_arg_classes(self) -> tuple[str | None, ...]:
        if (
            self.owner_class is not None
            and self.arg_classes
            and self.arg_classes[0] == self.owner_class
        ):
            return self.arg_classes[1:]
        return self.arg_classes


@dataclass(slots=True)
class SemanticIndex:
    class_names: set[str] = field(default_factory=set)
    function_names: set[str] = field(default_factory=set)
    member_names_by_class: dict[str, set[str]] = field(default_factory=dict)
    function_signatures_by_name: dict[str, list[SignatureSpec]] = field(
        default_factory=dict
    )
    member_signatures_by_key: dict[tuple[str, str], list[SignatureSpec]] = field(
        default_factory=dict
    )
    operator_aliases: dict[str, list[SignatureSpec]] = field(default_factory=dict)
    class_inheritance_relations: set[tuple[str, str]] = field(default_factory=set)
    function_inheritance_relations: set[tuple[str, str]] = field(default_factory=set)
    symbol_inheritance_relations: set[tuple[str, str]] = field(default_factory=set)
    function_class_relations: set[tuple[str, str]] = field(default_factory=set)


class Node:
    line: int
    column: int

    def children(self) -> list[Node]:
        return []

    def collect_semantic_issues(self) -> list[SemanticIssue]:
        issues: list[SemanticIssue] = []
        semantic_index = _build_semantic_index(self)
        non_premise_symbols = (
            _STATIC_NON_PREMISE_SYMBOLS | _collect_enum_symbols(self.children())
        )
        _validate_block(
            self.children(),
            issues,
            allow_condition_clauses=False,
            available_symbols=frozenset(),
            non_premise_symbols=non_premise_symbols,
            semantic_index=semantic_index,
        )
        _validate_program_semantics(
            self,
            issues,
            non_premise_symbols=non_premise_symbols,
            semantic_index=semantic_index,
        )
        return issues

    def check_semantic(self) -> bool:
        return not self.collect_semantic_issues()


class Expr(Node):
    pass


class Statement(Node):
    body: list[Statement]
    trailing_comment: str | None


@dataclass(slots=True)
class IdentifierExpr(Expr):
    name: str
    line: int
    column: int


@dataclass(slots=True)
class NumberExpr(Expr):
    value: str
    line: int
    column: int


@dataclass(slots=True)
class StringExpr(Expr):
    value: str
    line: int
    column: int


@dataclass(slots=True)
class SymbolExpr(Expr):
    value: str
    line: int
    column: int


@dataclass(slots=True)
class UnaryExpr(Expr):
    operator: str
    operand: Expr
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.operand]


@dataclass(slots=True)
class BinaryExpr(Expr):
    left: Expr
    operator: str
    right: Expr
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.left, self.right]


@dataclass(slots=True)
class SequenceExpr(Expr):
    items: list[Expr | None]
    separators: list[str]
    line: int
    column: int

    def children(self) -> list[Node]:
        return [item for item in self.items if item is not None]


@dataclass(slots=True)
class DelimitedExpr(Expr):
    opener: str
    items: list[Expr | None]
    separators: list[str]
    closer: str
    line: int
    column: int

    def children(self) -> list[Node]:
        return [item for item in self.items if item is not None]


@dataclass(slots=True)
class AttributeExpr(Expr):
    base: Expr | None
    attribute: str
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.base] if self.base is not None else []


@dataclass(slots=True)
class CallExpr(Expr):
    callee: Expr
    args: list[Expr | None]
    separators: list[str]
    delimiter: str
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.callee, *[arg for arg in self.args if arg is not None]]


@dataclass(slots=True)
class IndexExpr(Expr):
    base: Expr
    index: DelimitedExpr
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.base, self.index]


@dataclass(slots=True)
class QuantifiedExpr(Expr):
    quantifier: str
    body: DelimitedExpr
    line: int
    column: int

    def children(self) -> list[Node]:
        return [self.body]


@dataclass(slots=True)
class Program(Node):
    items: list[Statement]
    line: int = 1
    column: int = 1

    def children(self) -> list[Node]:
        return list(self.items)


@dataclass(slots=True)
class Heading(Statement):
    title: str
    body: list[Statement]
    line: int
    column: int
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        return list(self.body)


@dataclass(slots=True)
class Import(Statement):
    module_path: str
    line: int
    column: int
    body: list[Statement] = field(default_factory=list)
    trailing_comment: str | None = None


@dataclass(slots=True)
class Comment(Statement):
    text: str
    line: int
    column: int
    body: list[Statement] = field(default_factory=list)
    trailing_comment: str | None = None


@dataclass(slots=True)
class ExpressionStatement(Statement):
    expression: Expr
    body: list[Statement]
    line: int
    column: int
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        return [self.expression, *self.body]


@dataclass(slots=True)
class Declaration(Statement):
    head: Expr | None
    input_expr: Expr | None
    output_expr: Expr | None
    body: list[Statement]
    line: int
    column: int
    alias: Expr | None = None
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        children: list[Node] = []
        if self.head is not None:
            children.append(self.head)
        if self.alias is not None:
            children.append(self.alias)
        if self.input_expr is not None:
            children.append(self.input_expr)
        if self.output_expr is not None:
            children.append(self.output_expr)
        children.extend(self.body)
        return children


@dataclass(slots=True)
class Condition(Statement):
    quantifier: str
    body: list[Statement]
    line: int
    column: int
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        return list(self.body)

    def decompose(self) -> list[Condition]:
        return _decompose_condition(self)


ExpandedCondition = Condition


def _decompose_condition(
    condition: Condition,
) -> list[Condition]:
    bodies, _ = _decompose_condition_items(condition.body, states=[[]])
    return [
        Condition(
            quantifier=condition.quantifier,
            body=body,
            line=condition.line,
            column=condition.column,
            trailing_comment=condition.trailing_comment,
        )
        for body in bodies
    ]


def _decompose_condition_items(
    items: list[Statement],
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    emitted_conditions: list[list[Statement]] = []
    active_states = [list(state) for state in states]
    index = 0

    while index < len(items):
        item = items[index]

        if isinstance(item, Comment):
            active_states = [
                state + [_clone_statement(item)] for state in active_states
            ]
            index += 1
            continue

        if isinstance(item, Branch):
            branches: list[Branch] = []
            while index < len(items) and isinstance(items[index], Branch):
                branches.append(items[index])
                index += 1

            branch_conditions, active_states = _expand_branch_group(
                branches,
                states=active_states,
            )
            emitted_conditions.extend(branch_conditions)
            continue

        if isinstance(item, Premise):
            premise_conditions, active_states = _advance_premise(
                item,
                states=active_states,
            )
            emitted_conditions.extend(premise_conditions)
            index += 1
            continue

        if isinstance(item, ExpressionStatement):
            target_conditions, active_states = _advance_target(
                item,
                states=active_states,
            )
            emitted_conditions.extend(target_conditions)
            index += 1
            continue

        active_states = [
            state + [_clone_statement(item)] for state in active_states
        ]
        index += 1

    return emitted_conditions, active_states


def _expand_branch_group(
    branches: list[Branch],
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    emitted_conditions: list[list[Statement]] = []
    next_states: list[list[Statement]] = []

    for state in states:
        prior_branch_exprs: list[Expr] = []
        for branch in branches:
            branch_expr = _resolve_branch_premise_expr(branch, prior_branch_exprs)
            branch_state = state + [
                _target_expr_to_premise(
                    branch_expr,
                    line=branch.line,
                    column=branch.column,
                    trailing_comment=branch.trailing_comment,
                )
            ]
            branch_conditions, branch_states = _decompose_condition_items(
                branch.body,
                states=[branch_state],
            )
            emitted_conditions.extend(branch_conditions)
            next_states.extend(branch_states)
            if not _is_else_identifier(branch.expression):
                prior_branch_exprs.append(branch.expression)

    return emitted_conditions, next_states


def _advance_premise(
    premise: Premise,
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    emitted_conditions: list[list[Statement]] = []
    next_states: list[list[Statement]] = []

    for state in states:
        premise_state = state + [_clone_premise(premise)]
        premise_conditions, premise_states = _decompose_condition_items(
            premise.body,
            states=[premise_state],
        )
        emitted_conditions.extend(premise_conditions)
        next_states.extend(premise_states)

    return emitted_conditions, next_states


def _advance_target(
    target: ExpressionStatement,
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    emitted_conditions: list[list[Statement]] = []
    next_states: list[list[Statement]] = []

    for state in states:
        target_exprs = _split_expanded_target_exprs(target.expression)
        for target_expr in target_exprs:
            emitted_conditions.append(
                state
                + [
                    _clone_target_expr(
                        target_expr,
                        line=target.line,
                        column=target.column,
                        trailing_comment=target.trailing_comment,
                    )
                ]
            )

        # Later siblings depend on all targets from the same line.
        target_state = state + [
            _target_expr_to_premise(
                target_expr,
                line=target.line,
                column=target.column,
                trailing_comment=target.trailing_comment,
            )
            for target_expr in target_exprs
        ]
        nested_conditions, nested_states = _decompose_condition_items(
            target.body,
            states=[target_state],
        )
        emitted_conditions.extend(nested_conditions)
        next_states.extend(nested_states)

    return emitted_conditions, next_states


def _clone_premise(premise: Premise) -> Premise:
    return Premise(
        expression=premise.expression,
        body=[],
        line=premise.line,
        column=premise.column,
        trailing_comment=premise.trailing_comment,
    )


def _clone_target(target: ExpressionStatement) -> ExpressionStatement:
    return ExpressionStatement(
        expression=target.expression,
        body=[],
        line=target.line,
        column=target.column,
        trailing_comment=target.trailing_comment,
    )


def _branch_to_premise(branch: Branch) -> Premise:
    return Premise(
        expression=branch.expression,
        body=[],
        line=branch.line,
        column=branch.column,
        trailing_comment=branch.trailing_comment,
    )


def _target_to_premise(target: ExpressionStatement) -> Premise:
    return Premise(
        expression=target.expression,
        body=[],
        line=target.line,
        column=target.column,
        trailing_comment=target.trailing_comment,
    )


def _clone_target_expr(
    expr: Expr,
    *,
    line: int,
    column: int,
    trailing_comment: str | None,
) -> ExpressionStatement:
    return ExpressionStatement(
        expression=expr,
        body=[],
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def _target_expr_to_premise(
    expr: Expr,
    *,
    line: int,
    column: int,
    trailing_comment: str | None,
) -> Premise:
    return Premise(
        expression=expr,
        body=[],
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def _split_expanded_target_exprs(expr: Expr) -> list[Expr]:
    if not isinstance(expr, SequenceExpr):
        return [expr]
    return [item for item in expr.items if item is not None] or [expr]


def _resolve_branch_premise_expr(branch: Branch, prior_branch_exprs: list[Expr]) -> Expr:
    if not _is_else_identifier(branch.expression):
        return branch.expression
    return _build_residual_else_guard(prior_branch_exprs, branch)


def _build_residual_else_guard(prior_branch_exprs: list[Expr], branch: Branch) -> Expr:
    negated_items: list[Expr] = [
        _negate_expr(expr, line=branch.line, column=branch.column)
        for expr in prior_branch_exprs
    ]
    if not negated_items:
        return IdentifierExpr(name="else", line=branch.line, column=branch.column)
    if len(negated_items) == 1:
        return negated_items[0]
    return SequenceExpr(
        items=negated_items,
        separators=[","] * (len(negated_items) - 1),
        line=branch.line,
        column=branch.column,
    )


def _negate_expr(expr: Expr, *, line: int, column: int) -> Expr:
    if isinstance(expr, UnaryExpr) and expr.operator == "!":
        return expr.operand
    return UnaryExpr(operator="!", operand=expr, line=line, column=column)


def _clone_statement(statement: Statement) -> Statement:
    if isinstance(statement, Condition):
        return Condition(
            quantifier=statement.quantifier,
            body=[_clone_statement(item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, Premise):
        return Premise(
            expression=statement.expression,
            body=[_clone_statement(item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, Branch):
        return Branch(
            expression=statement.expression,
            body=[_clone_statement(item) for item in statement.body],
            line=statement.line,
            column=statement.column,
            trailing_comment=statement.trailing_comment,
        )

    if isinstance(statement, (ExpressionStatement, Declaration, Heading, Import, Comment)):
        if hasattr(statement, "body"):
            return replace(
                statement,
                body=[_clone_statement(item) for item in statement.body],
            )
        return replace(statement)

    return statement


def parse_program_text(
    program_text: str,
    *,
    source_name: str = "<program>",
) -> Program:
    token_stream = tokenize_text(program_text, source_name=source_name)
    return semantic_parser(token_stream)


def source_to_program(
    logic_program: str | Path,
    *,
    force_file: bool = False,
) -> Program:
    if isinstance(logic_program, Path):
        source_path = logic_program
        source_text = source_path.read_text(encoding="utf-8")
        return parse_program_text(source_text, source_name=str(source_path))

    if not force_file and ("\n" in logic_program or "\r" in logic_program):
        return parse_program_text(logic_program)

    source_path = Path(logic_program)
    if force_file:
        source_text = source_path.read_text(encoding="utf-8")
        return parse_program_text(source_text, source_name=str(source_path))

    try:
        if source_path.exists():
            source_text = source_path.read_text(encoding="utf-8")
            return parse_program_text(source_text, source_name=str(source_path))
    except OSError:
        pass

    return parse_program_text(logic_program)


def parse_condition_text(condition_text: str) -> Condition:
    token_stream = tokenize_text(condition_text, source_name="<condition>")
    root = semantic_parser(token_stream)
    if len(root.items) != 1:
        raise ParserError("condition text must contain exactly one top-level statement")

    statement = root.items[0]
    if isinstance(statement, Condition):
        return statement

    if isinstance(statement, ExpressionStatement) and isinstance(
        statement.expression, QuantifiedExpr
    ):
        return _condition_from_quantified_expr(statement.expression)

    raise ParserError("top-level statement is not a condition")


def _build_semantic_index(root_node: Node) -> SemanticIndex:
    semantic_index = SemanticIndex()
    _seed_declared_entities(root_node, semantic_index, current_class=None)
    _scan_semantic_relations(root_node, semantic_index, current_class=None)
    return semantic_index


def _seed_declared_entities(
    node: Node,
    semantic_index: SemanticIndex,
    *,
    current_class: str | None,
) -> None:
    if isinstance(node, Program):
        items = node.items
    elif isinstance(node, Statement):
        items = node.body
    else:
        return

    for item in items:
        scoped_class = current_class

        if isinstance(item, Declaration):
            owner_class = _declaration_owner_class(item, current_class=current_class)
            if owner_class is not None:
                semantic_index.class_names.add(owner_class)
                member_name = _extract_member_name(item.head)
                if member_name is not None:
                    _register_member_name(
                        semantic_index,
                        owner_class,
                        member_name,
                    )
                elif item.head is None:
                    _register_member_name(
                        semantic_index,
                        owner_class,
                        "call",
                    )
            elif isinstance(item.head, IdentifierExpr):
                semantic_index.function_names.add(item.head.name)
                alias_name = _extract_alias_name(item.alias)
                if alias_name is not None:
                    semantic_index.function_names.add(alias_name)
            elif isinstance(item.head, SymbolExpr):
                semantic_index.function_names.add(item.head.value)
                alias_name = _extract_alias_name(item.alias)
                if alias_name is not None:
                    semantic_index.function_names.add(alias_name)

            _seed_signature_class_candidates(item.input_expr, semantic_index)
            _seed_signature_class_candidates(item.output_expr, semantic_index)

        if isinstance(item, ExpressionStatement):
            if isinstance(item.expression, IdentifierExpr):
                semantic_index.class_names.add(item.expression.name)
            if isinstance(item.expression, BinaryExpr):
                semantic_index.class_names.update(
                    _extract_enum_class_names(item.expression)
                )
                semantic_index.symbol_inheritance_relations.update(
                    _extract_enum_class_relations(item.expression)
                )
                if item.expression.operator == "~":
                    left_name = _extract_relation_name(item.expression.left)
                    if left_name is not None and left_name not in semantic_index.function_names:
                        semantic_index.class_names.add(left_name)

            if current_class is not None and isinstance(item.expression, AttributeExpr):
                if item.expression.base is None:
                    _register_member_name(
                        semantic_index,
                        current_class,
                        item.expression.attribute,
                    )

            scoped_owner = _scoped_block_owner_class(
                item.expression,
                item.body,
                semantic_index,
            )
            if scoped_owner is not None:
                scoped_class = scoped_owner
                semantic_index.class_names.add(scoped_owner)
                if isinstance(item.expression, BinaryExpr) and item.expression.operator in {"::", "~"}:
                    left_name = _extract_relation_name(item.expression.left)
                    right_name = _extract_relation_name(item.expression.right)
                    if left_name is not None:
                        semantic_index.class_names.add(left_name)
                    if right_name is not None:
                        semantic_index.class_names.add(right_name)
                    alias_symbol = _extract_relation_symbol_alias(item.expression.right)
                    if right_name is not None and alias_symbol is not None:
                        semantic_index.symbol_inheritance_relations.add(
                            (right_name, alias_symbol)
                        )

        if isinstance(item, Statement) and item.body:
            _seed_declared_entities(
                item,
                semantic_index,
                current_class=scoped_class,
            )


def _scan_semantic_relations(
    node: Node,
    semantic_index: SemanticIndex,
    *,
    current_class: str | None,
    inside_declaration_body: bool = False,
) -> None:
    if isinstance(node, Program):
        items = node.items
    elif isinstance(node, Statement):
        items = node.body
    else:
        return

    for item in items:
        scoped_class = current_class

        if isinstance(item, Declaration):
            owner_class = _declaration_owner_class(item, current_class=current_class)
            signature = _build_signature_spec(
                item,
                semantic_index=semantic_index,
                owner_class=owner_class,
            )
            if signature is not None:
                if owner_class is None:
                    semantic_index.function_signatures_by_name.setdefault(
                        signature.name, []
                    ).append(signature)
                else:
                    semantic_index.member_signatures_by_key.setdefault(
                        (owner_class, signature.name), []
                    ).append(signature)
                if _is_operator_alias(signature.name):
                    semantic_index.operator_aliases.setdefault(
                        signature.name, []
                    ).append(signature)
                if signature.alias is not None and _is_operator_alias(signature.alias):
                    semantic_index.operator_aliases.setdefault(
                        signature.alias, []
                    ).append(signature)

        if isinstance(item, ExpressionStatement) and isinstance(item.expression, BinaryExpr):
            resolved = _resolve_relation_expression(item.expression, semantic_index)
            if resolved is not None:
                relation_kind, left_name, right_name = resolved
                if (
                    inside_declaration_body
                    and item.expression.operator == "~"
                    and not item.body
                    and relation_kind == "class_inheritance"
                ):
                    relation_kind = "symbol_inheritance"
                if relation_kind == "class_inheritance":
                    semantic_index.class_inheritance_relations.add(
                        (left_name, right_name)
                    )
                elif relation_kind == "function_inheritance":
                    semantic_index.function_inheritance_relations.add(
                        (left_name, right_name)
                    )
                elif relation_kind == "symbol_inheritance":
                    semantic_index.symbol_inheritance_relations.add(
                        (left_name, right_name)
                    )
                elif relation_kind == "function_to_class":
                    semantic_index.function_class_relations.add(
                        (left_name, right_name)
                    )

            semantic_index.symbol_inheritance_relations.update(
                _extract_enum_class_relations(item.expression)
            )

            scoped_owner = _scoped_block_owner_class(
                item.expression,
                item.body,
                semantic_index,
            )
            if scoped_owner is not None:
                scoped_class = scoped_owner

        elif isinstance(item, ExpressionStatement):
            scoped_owner = _scoped_block_owner_class(
                item.expression,
                item.body,
                semantic_index,
            )
            if scoped_owner is not None:
                scoped_class = scoped_owner

        if isinstance(item, Statement) and item.body:
            _scan_semantic_relations(
                item,
                semantic_index,
                current_class=scoped_class,
                inside_declaration_body=inside_declaration_body
                or isinstance(item, Declaration),
            )


def _seed_signature_class_candidates(
    expr: Expr | None,
    semantic_index: SemanticIndex,
) -> None:
    for item in _signature_expr_items(expr):
        if not isinstance(item, IdentifierExpr):
            continue
        class_name = _infer_symbol_class_name(
            item.name,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        if class_name is not None:
            semantic_index.class_names.add(class_name)


def _scoped_block_owner_class(
    expr: Expr,
    body: list[Statement],
    semantic_index: SemanticIndex,
) -> str | None:
    if not body:
        return None

    if isinstance(expr, IdentifierExpr):
        return expr.name

    if isinstance(expr, BinaryExpr) and expr.operator in {"::", "~"}:
        left_name = _extract_relation_name(expr.left)
        right_name = _extract_relation_name(expr.right)
        if left_name is None or right_name is None:
            return None
        if _body_declares_members(body):
            return right_name
        resolved = _resolve_relation_expression(expr, semantic_index)
        if resolved is not None and resolved[0] == "class_inheritance":
            return right_name

    return None


def _body_declares_members(body: list[Statement]) -> bool:
    for item in body:
        if isinstance(item, Declaration):
            owner_class = _declaration_owner_class(item, current_class=None)
            if owner_class is not None:
                return True
        if isinstance(item, ExpressionStatement):
            if isinstance(item.expression, AttributeExpr) and item.expression.base is None:
                return True
    return False


def _register_member_name(
    semantic_index: SemanticIndex,
    owner_class: str,
    member_name: str,
) -> None:
    semantic_index.member_names_by_class.setdefault(owner_class, set()).add(member_name)


def _declaration_owner_class(
    statement: Declaration,
    *,
    current_class: str | None,
) -> str | None:
    if statement.head is None:
        return current_class
    owner_class, _ = _extract_member_owner_and_name(
        statement.head,
        current_class=current_class,
    )
    return owner_class


def _build_signature_spec(
    statement: Declaration,
    *,
    semantic_index: SemanticIndex,
    owner_class: str | None,
) -> SignatureSpec | None:
    if statement.head is None:
        if owner_class is None:
            return None
        name = "call"
    elif owner_class is not None:
        _, member_name = _extract_member_owner_and_name(
            statement.head,
            current_class=owner_class,
        )
        if member_name is None:
            return None
        name = member_name
    elif isinstance(statement.head, IdentifierExpr):
        name = statement.head.name
    elif isinstance(statement.head, SymbolExpr):
        name = statement.head.value
    else:
        return None

    alias = _extract_alias_name(statement.alias)
    return SignatureSpec(
        name=name,
        input_shape=_format_expr(statement.input_expr),
        output_shape=_format_expr(statement.output_expr),
        arity=_signature_expr_arity(statement.input_expr),
        arg_classes=_signature_expr_classes(
            statement.input_expr,
            semantic_index=semantic_index,
        ),
        owner_class=owner_class,
        alias=alias,
        line=statement.line,
        column=statement.column,
    )


def _extract_alias_name(expr: Expr | None) -> str | None:
    if isinstance(expr, IdentifierExpr):
        return expr.name
    if isinstance(expr, SymbolExpr):
        return expr.value
    return None


def _is_operator_alias(alias: str) -> bool:
    return (
        alias in _LineExpressionParser._INFIX_PRECEDENCE
        or _is_custom_operator_alias(alias)
        or _is_latex_name(alias)
    )


def _signature_expr_arity(expr: Expr | None) -> int:
    return len(_signature_expr_items(expr))


def _signature_expr_classes(
    expr: Expr | None,
    *,
    semantic_index: SemanticIndex,
) -> tuple[str | None, ...]:
    return tuple(
        _infer_expr_class(
            item,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        for item in _signature_expr_items(expr)
    )


def _signature_expr_items(expr: Expr | None) -> list[Expr]:
    if expr is None:
        return []
    if isinstance(expr, (DelimitedExpr, SequenceExpr)):
        return [item for item in expr.items if item is not None]
    return [expr]


def _extract_enum_class_names(expr: BinaryExpr) -> set[str]:
    definition = _extract_enum_definition(expr)
    if definition is None:
        return set()
    enum_class_name, _ = definition
    return {enum_class_name}


def _resolve_relation_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    if expr.operator == "::":
        return _resolve_double_colon_expression(expr, semantic_index)
    if expr.operator == "~":
        return _resolve_tilde_expression(expr, semantic_index)
    return None


def _resolve_double_colon_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    if expr.operator != "::":
        return None

    left_name = _extract_relation_name(expr.left)
    right_name = _extract_relation_name(expr.right)
    if left_name is None or right_name is None:
        return None

    if right_name in semantic_index.member_names_by_class.get(left_name, set()):
        return "member_extraction", left_name, right_name

    if (
        left_name in semantic_index.function_names
        and right_name in semantic_index.function_names
    ):
        return "function_inheritance", left_name, right_name

    if _looks_like_class_identifier(left_name, semantic_index) and _looks_like_class_identifier(
        right_name, semantic_index
    ):
        return "class_inheritance", left_name, right_name

    if _looks_like_class_identifier(left_name, semantic_index):
        return "symbol_inheritance", left_name, right_name

    return None


def _resolve_tilde_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    if expr.operator != "~":
        return None

    left_name = _extract_relation_name(expr.left)
    if left_name is None:
        return None

    class_call_owner = _extract_class_call_owner(expr.right)
    if left_name in semantic_index.function_names and class_call_owner is not None:
        return "function_to_class", left_name, class_call_owner

    right_name = _extract_relation_name(expr.right)
    if right_name is None:
        return None

    if (
        left_name in semantic_index.function_names
        and right_name in semantic_index.function_names
    ):
        return "function_inheritance", left_name, right_name

    if _looks_like_class_identifier(left_name, semantic_index):
        if (
            isinstance(expr.right, CallExpr)
            or right_name in semantic_index.class_names
            or left_name in semantic_index.class_names
        ):
            return "class_inheritance", left_name, right_name
        return "symbol_inheritance", left_name, right_name

    return None


def _extract_relation_name(expr: Expr | None) -> str | None:
    if isinstance(expr, IdentifierExpr):
        return expr.name
    if isinstance(expr, SymbolExpr):
        return expr.value
    if isinstance(expr, CallExpr) and isinstance(expr.callee, IdentifierExpr):
        return expr.callee.name
    if isinstance(expr, CallExpr) and isinstance(expr.callee, SymbolExpr):
        return expr.callee.value
    return None


def _extract_member_name(expr: Expr | None) -> str | None:
    if isinstance(expr, AttributeExpr):
        return expr.attribute
    if isinstance(expr, IdentifierExpr):
        return expr.name
    if isinstance(expr, SymbolExpr):
        return expr.value
    if isinstance(expr, CallExpr) and isinstance(expr.callee, IdentifierExpr):
        return expr.callee.name
    if isinstance(expr, CallExpr) and isinstance(expr.callee, SymbolExpr):
        return expr.callee.value
    if isinstance(expr, BinaryExpr) and expr.operator == "::":
        return _extract_member_name(expr.right)
    return None


def _extract_member_owner_and_name(
    expr: Expr | None,
    *,
    current_class: str | None,
) -> tuple[str | None, str | None]:
    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return current_class, expr.attribute
        if isinstance(expr.base, IdentifierExpr):
            return expr.base.name, expr.attribute
        return None, None

    if isinstance(expr, BinaryExpr) and expr.operator == "::":
        owner_class = _extract_relation_name(expr.left)
        member_name = _extract_member_name(expr.right)
        return owner_class, member_name

    return None, None


def _extract_relation_symbol_alias(expr: Expr | None) -> str | None:
    if not isinstance(expr, CallExpr) or not isinstance(expr.callee, IdentifierExpr):
        return None
    args = [arg for arg in expr.args if arg is not None]
    if len(args) != 1 or not isinstance(args[0], IdentifierExpr):
        return None
    return args[0].name


def _extract_class_call_owner(expr: Expr | None) -> str | None:
    if not isinstance(expr, BinaryExpr) or expr.operator != "::":
        return None
    if not isinstance(expr.left, IdentifierExpr):
        return None
    right_name = _extract_relation_name(expr.right)
    if right_name != "call":
        return None
    return expr.left.name


def _looks_like_class_identifier(
    name: str,
    semantic_index: SemanticIndex,
) -> bool:
    if name in semantic_index.class_names:
        return True
    if any(char.isdigit() for char in name) or "_" in name:
        return False
    return bool(name[:1].isupper())


def build_class_inheritance_graph(root_node: Node) -> ClassInheritanceGraph:
    relations = collect_class_inheritance_relations(root_node)
    parents_by_child: dict[str, set[str]] = {}
    children_by_parent: dict[str, set[str]] = {}

    for parent_class, child_class in relations:
        parents_by_child.setdefault(child_class, set()).add(parent_class)
        children_by_parent.setdefault(parent_class, set()).add(child_class)

    return ClassInheritanceGraph(
        parents_by_child={
            child_class: tuple(sorted(parent_classes))
            for child_class, parent_classes in sorted(parents_by_child.items())
        },
        children_by_parent={
            parent_class: tuple(sorted(child_classes))
            for parent_class, child_classes in sorted(children_by_parent.items())
        },
    )


def collect_class_inheritance_relations(root_node: Node) -> tuple[tuple[str, str], ...]:
    semantic_index = _build_semantic_index(root_node)
    return tuple(sorted(semantic_index.class_inheritance_relations))


def _extract_enum_class_relations(expr: BinaryExpr) -> tuple[tuple[str, str], ...]:
    definition = _extract_enum_definition(expr)
    if definition is None:
        return ()
    enum_class_name, member_names = definition
    return tuple(sorted((enum_class_name, member_name) for member_name in member_names))


def _extract_class_name(expr: Expr | None) -> str | None:
    if isinstance(expr, IdentifierExpr):
        return expr.name
    return None


def _extract_enum_definition(expr: BinaryExpr) -> tuple[str, set[str]] | None:
    if expr.operator != "∈":
        return None

    member_names = _extract_enum_member_names(expr.left)
    enum_class_name = _extract_class_name(expr.right)
    if member_names and enum_class_name is not None:
        return enum_class_name, member_names

    enum_class_name = _extract_class_name(expr.left)
    member_names = _extract_enum_member_names(expr.right)
    if member_names and enum_class_name is not None:
        return enum_class_name, member_names

    return None


def _extract_enum_member_names(expr: Expr | None) -> set[str]:
    if not isinstance(expr, DelimitedExpr):
        return set()
    if expr.opener != "{" or expr.closer != "}":
        return set()

    members: set[str] = set()
    for item in expr.items:
        if item is None:
            return set()
        if not isinstance(item, IdentifierExpr):
            return set()
        members.add(item.name)
    return members


def _reachable_class_relations(
    adjacency: dict[str, tuple[str, ...]],
    class_name: str,
    *,
    transitive: bool,
) -> tuple[str, ...]:
    if not transitive:
        return adjacency.get(class_name, ())

    visited: set[str] = set()
    pending = list(adjacency.get(class_name, ()))
    while pending:
        related_class = pending.pop()
        if related_class in visited:
            continue
        visited.add(related_class)
        pending.extend(adjacency.get(related_class, ()))

    return tuple(sorted(visited))


def _condition_from_quantified_expr(expr: QuantifiedExpr) -> Condition:
    segments = _split_condition_segments(expr.body)
    if not segments or not segments[0]:
        raise ParserError("quantified condition must contain at least one target")

    body: list[Statement] = []
    for segment in reversed(segments[1:]):
        premise_expr = _merge_segment_expr(segment)
        body.append(
            Premise(
                expression=premise_expr,
                body=[],
                line=premise_expr.line,
                column=premise_expr.column,
            )
        )

    for target_expr in segments[0]:
        body.append(
            ExpressionStatement(
                expression=target_expr,
                body=[],
                line=target_expr.line,
                column=target_expr.column,
            )
        )

    return Condition(
        quantifier=expr.quantifier,
        body=body,
        line=expr.line,
        column=expr.column,
    )


def _split_condition_segments(body: DelimitedExpr) -> list[list[Expr]]:
    if body.opener != "{" or body.closer != "}":
        raise ParserError("quantified condition body must be delimited by braces")

    if not body.items:
        return [[]]

    segments: list[list[Expr]] = [[]]
    for index, item in enumerate(body.items):
        if item is None:
            raise ParserError("quantified condition contains an empty clause")
        segments[-1].append(item)
        if index >= len(body.separators):
            continue
        separator = body.separators[index]
        if separator == "|":
            segments.append([])
            continue
        if separator != ",":
            raise ParserError(
                f"unsupported quantified-condition separator {separator!r}"
            )

    return segments


def _merge_segment_expr(items: list[Expr]) -> Expr:
    if len(items) == 1:
        return items[0]
    line = items[0].line
    column = items[0].column
    return SequenceExpr(
        items=list(items),
        separators=[","] * (len(items) - 1),
        line=line,
        column=column,
    )


def condition_to_source(condition: Condition) -> str:
    lines = _format_condition_lines(condition, indent=0)
    return "\n".join(lines)


def program_to_source(root_node: Node) -> str:
    if isinstance(root_node, Program):
        return "\n".join(_format_statement_block(root_node.items, indent=0))

    if isinstance(root_node, Condition):
        return condition_to_source(root_node)

    if isinstance(root_node, Statement):
        return "\n".join(_format_statement_lines(root_node, indent=0))

    if isinstance(root_node, Expr):
        return _format_expr(root_node)

    raise TypeError(f"unsupported root node type: {type(root_node).__name__}")


def verify_semantic_parser(lp_path: str | Path) -> str:
    root_node1 = source_to_program(lp_path, force_file=True)
    new_lp_file_content = program_to_source(root_node1)
    root_node2 = source_to_program(new_lp_file_content)
    normalized_root_node1 = _normalize_semantic_tree(root_node1)
    normalized_root_node2 = _normalize_semantic_tree(root_node2)
    assert normalized_root_node1 == normalized_root_node2, (
        "semantic round-trip mismatch after translating the parsed root node"
    )
    return new_lp_file_content


parse = source_to_program
translate = program_to_source


def _format_condition_lines(condition: Condition, *, indent: int) -> list[str]:
    lines = [_indent_text(indent) + condition.quantifier]
    lines.extend(_format_statement_block(condition.body, indent=indent + 4))
    return lines


def _format_statement_block(
    items: list[Statement],
    *,
    indent: int,
) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(_format_statement_lines(item, indent=indent))
    return lines


def _format_statement_lines(statement: Statement, *, indent: int) -> list[str]:
    prefix = _indent_text(indent)
    trailing = _format_trailing_comment(statement.trailing_comment)

    if isinstance(statement, Condition):
        lines = [prefix + statement.quantifier + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Premise):
        lines = [prefix + "| " + _format_expr(statement.expression) + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Branch):
        lines = [prefix + "|- " + _format_expr(statement.expression) + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, ExpressionStatement):
        lines = [prefix + _format_expr(statement.expression) + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Declaration):
        lines = [prefix + _format_declaration(statement) + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Heading):
        lines = [prefix + "@" + statement.title + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Import):
        lines = [prefix + "$import {" + statement.module_path + "}" + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, Comment):
        return [prefix + "#" + (" " + statement.text if statement.text else "")]

    return [prefix + repr(statement)]


def _format_declaration(statement: Declaration) -> str:
    if statement.head is None:
        head = ""
    else:
        head = _format_expr(statement.head)

    if statement.alias is not None:
        head = f"{head}({_format_expr(statement.alias)})" if head else _format_expr(
            statement.alias
        )

    input_expr = _format_expr(statement.input_expr) if statement.input_expr else ""
    output_expr = _format_expr(statement.output_expr) if statement.output_expr else ""
    return f"{head}: {input_expr} => {output_expr}".strip()


def _format_expr(expr: Expr | None) -> str:
    if expr is None:
        return ""

    if isinstance(expr, IdentifierExpr):
        return expr.name

    if isinstance(expr, NumberExpr):
        return expr.value

    if isinstance(expr, StringExpr):
        escaped = (
            expr.value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'

    if isinstance(expr, SymbolExpr):
        return expr.value

    if isinstance(expr, UnaryExpr):
        return f"{expr.operator}{_format_atom(expr.operand)}"

    if isinstance(expr, BinaryExpr):
        return (
            f"{_format_binary_operand(expr.left)} {expr.operator} "
            f"{_format_binary_operand(expr.right)}"
        )

    if isinstance(expr, SequenceExpr):
        parts = [_format_expr(item) for item in expr.items]
        return _join_with_separators(parts, expr.separators)

    if isinstance(expr, DelimitedExpr):
        parts = [_format_expr(item) for item in expr.items]
        inner = _join_with_separators(parts, expr.separators)
        return f"{expr.opener}{inner}{expr.closer}"

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return f"::{expr.attribute}"
        return f"{_format_atom(expr.base)}.{expr.attribute}"

    if isinstance(expr, CallExpr):
        if expr.delimiter == "{}":
            if len(expr.args) == 1 and isinstance(expr.args[0], DelimitedExpr):
                return f"{_format_atom(expr.callee)}{_format_expr(expr.args[0])}"
            args = _join_with_separators(
                [_format_expr(arg) for arg in expr.args],
                expr.separators,
            )
            return f"{_format_atom(expr.callee)}{{{args}}}"

        args = _join_with_separators(
            [_format_expr(arg) for arg in expr.args],
            expr.separators,
        )
        return f"{_format_atom(expr.callee)}({args})"

    if isinstance(expr, IndexExpr):
        return f"{_format_atom(expr.base)}{_format_expr(expr.index)}"

    if isinstance(expr, QuantifiedExpr):
        return f"{expr.quantifier}{_format_expr(expr.body)}"

    return repr(expr)


def _format_atom(expr: Expr) -> str:
    if isinstance(
        expr,
        (
            IdentifierExpr,
            NumberExpr,
            StringExpr,
            SymbolExpr,
            AttributeExpr,
            CallExpr,
            IndexExpr,
            QuantifiedExpr,
            DelimitedExpr,
        ),
    ):
        return _format_expr(expr)
    return f"({_format_expr(expr)})"


def _format_binary_operand(expr: Expr) -> str:
    if isinstance(expr, BinaryExpr) and expr.operator == "->":
        return _format_expr(expr)
    if isinstance(expr, UnaryExpr):
        return _format_expr(expr)
    return _format_atom(expr)


def _join_with_separators(parts: list[str], separators: list[str]) -> str:
    if not parts:
        return ""

    text = parts[0]
    for index, part in enumerate(parts[1:], start=1):
        separator = separators[index - 1]
        text += _format_separator_text(
            separator,
            has_left=bool(text),
            has_right=bool(part),
        )
        text += part

    if len(separators) >= len(parts):
        for separator in separators[len(parts) - 1 :]:
            text += _format_separator_text(
                separator,
                has_left=bool(text),
                has_right=False,
            )

    return text


def _format_separator_text(
    separator: str,
    *,
    has_left: bool,
    has_right: bool,
) -> str:
    if separator == ",":
        return ", " if has_right else ","

    if separator in {":", ";"}:
        return f"{separator} " if has_right else separator

    if separator == "|":
        if has_left and has_right:
            return " | "
        if has_left:
            return " |"
        if has_right:
            return "| "
        return "|"

    if has_left and has_right:
        return f" {separator} "
    if has_left:
        return f" {separator}"
    if has_right:
        return f"{separator} "
    return separator


def _format_trailing_comment(comment: str | None) -> str:
    if comment is None:
        return ""
    if not comment:
        return " #"
    return f"  # {comment}"


def _indent_text(indent: int) -> str:
    return " " * indent


def _normalize_semantic_tree(node: Node | None) -> Node | None:
    if node is None:
        return None

    if isinstance(node, Program):
        return Program(
            items=_normalize_statement_block(node.items),
            line=0,
            column=0,
        )

    if isinstance(node, Comment):
        return None

    if isinstance(node, IdentifierExpr):
        return IdentifierExpr(name=node.name, line=0, column=0)

    if isinstance(node, NumberExpr):
        return NumberExpr(value=node.value, line=0, column=0)

    if isinstance(node, StringExpr):
        return StringExpr(value=node.value, line=0, column=0)

    if isinstance(node, SymbolExpr):
        return SymbolExpr(value=node.value, line=0, column=0)

    if isinstance(node, UnaryExpr):
        return UnaryExpr(
            operator=node.operator,
            operand=_normalize_expr(node.operand),
            line=0,
            column=0,
        )

    if isinstance(node, BinaryExpr):
        return BinaryExpr(
            left=_normalize_expr(node.left),
            operator=node.operator,
            right=_normalize_expr(node.right),
            line=0,
            column=0,
        )

    if isinstance(node, SequenceExpr):
        return SequenceExpr(
            items=_normalize_expr_items(node.items),
            separators=list(node.separators),
            line=0,
            column=0,
        )

    if isinstance(node, DelimitedExpr):
        return DelimitedExpr(
            opener=node.opener,
            items=_normalize_expr_items(node.items),
            separators=list(node.separators),
            closer=node.closer,
            line=0,
            column=0,
        )

    if isinstance(node, AttributeExpr):
        return AttributeExpr(
            base=_normalize_expr(node.base) if node.base is not None else None,
            attribute=node.attribute,
            line=0,
            column=0,
        )

    if isinstance(node, CallExpr):
        return CallExpr(
            callee=_normalize_expr(node.callee),
            args=_normalize_expr_items(node.args),
            separators=list(node.separators),
            delimiter=node.delimiter,
            line=0,
            column=0,
        )

    if isinstance(node, IndexExpr):
        return IndexExpr(
            base=_normalize_expr(node.base),
            index=_normalize_delimited_expr(node.index),
            line=0,
            column=0,
        )

    if isinstance(node, QuantifiedExpr):
        return QuantifiedExpr(
            quantifier=node.quantifier,
            body=_normalize_delimited_expr(node.body),
            line=0,
            column=0,
        )

    if isinstance(node, Heading):
        return Heading(
            title=node.title,
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )

    if isinstance(node, Import):
        return Import(
            module_path=node.module_path,
            line=0,
            column=0,
            body=_normalize_statement_block(node.body),
            trailing_comment=None,
        )

    if isinstance(node, ExpressionStatement):
        return ExpressionStatement(
            expression=_normalize_expr(node.expression),
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )

    if isinstance(node, Declaration):
        return Declaration(
            head=_normalize_expr(node.head) if node.head is not None else None,
            input_expr=(
                _normalize_expr(node.input_expr) if node.input_expr is not None else None
            ),
            output_expr=(
                _normalize_expr(node.output_expr)
                if node.output_expr is not None
                else None
            ),
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            alias=_normalize_expr(node.alias) if node.alias is not None else None,
            trailing_comment=None,
        )

    if isinstance(node, Condition):
        return Condition(
            quantifier=node.quantifier,
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )

    if isinstance(node, Premise):
        return Premise(
            expression=_normalize_expr(node.expression),
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )

    if isinstance(node, Branch):
        return Branch(
            expression=_normalize_expr(node.expression),
            body=_normalize_statement_block(node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )

    raise TypeError(f"unsupported node type: {type(node).__name__}")


def _normalize_statement_block(items: list[Statement]) -> list[Statement]:
    normalized_items: list[Statement] = []
    for item in items:
        normalized_item = _normalize_semantic_tree(item)
        if isinstance(normalized_item, Statement):
            normalized_items.append(normalized_item)
    return normalized_items


def _normalize_expr_items(items: list[Expr | None]) -> list[Expr | None]:
    normalized_items: list[Expr | None] = []
    for item in items:
        normalized_items.append(_normalize_expr(item) if item is not None else None)
    return normalized_items


def _normalize_expr(expr: Expr) -> Expr:
    normalized_expr = _normalize_semantic_tree(expr)
    assert isinstance(normalized_expr, Expr)
    if _is_redundant_grouped_expr(normalized_expr):
        inner_expr = normalized_expr.items[0]
        assert isinstance(inner_expr, Expr)
        return inner_expr
    return normalized_expr


def _normalize_delimited_expr(expr: DelimitedExpr) -> DelimitedExpr:
    normalized_expr = _normalize_semantic_tree(expr)
    assert isinstance(normalized_expr, DelimitedExpr)
    return normalized_expr


def _is_redundant_grouped_expr(expr: Expr) -> bool:
    return (
        isinstance(expr, DelimitedExpr)
        and expr.opener == "("
        and expr.closer == ")"
        and len(expr.items) == 1
        and not expr.separators
        and expr.items[0] is not None
    )


@dataclass(slots=True)
class Premise(Statement):
    expression: Expr
    body: list[Statement]
    line: int
    column: int
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        return [self.expression, *self.body]


@dataclass(slots=True)
class Branch(Statement):
    expression: Expr
    body: list[Statement]
    line: int
    column: int
    trailing_comment: str | None = None

    def children(self) -> list[Node]:
        return [self.expression, *self.body]


class ParserError(SyntaxError):
    """Raised when a token stream cannot be parsed into the `.lp` AST."""


class SemanticParser:
    """
    Explicit grammar used by this parser.

    program            ::= block EOF
    block              ::= { item }
    item               ::= heading
                         | import
                         | scoped_statement
                         | statement

    heading            ::= HEADING NEWLINE INDENT block DEDENT
    import             ::= IMPORT NEWLINE
    scoped_statement   ::= statement NEWLINE INDENT block DEDENT

    statement          ::= comment
                         | expanded_condition
                         | branch
                         | premise
                         | declaration
                         | expression_statement

    comment            ::= COMMENT
    expanded_condition ::= ("∀" | "∃") [inline_condition]
                         | ("∀" | "∃") NEWLINE INDENT condition_block DEDENT
    branch             ::= "|-" expression
    premise            ::= "|" expression
    declaration        ::= declaration_head ":" signature
    declaration_head   ::= ε | expression [ "(" expression ")" ]  # alias form
    signature          ::= expression "=>" expression
    expression_statement ::= expression

    condition_block    ::= { premise | branch | statement }

    expression         ::= sequence_expr
    sequence_expr      ::= infix_expr { "," infix_expr }
    infix_expr         ::= unary_expr { infix_op unary_expr }
    unary_expr         ::= [ "!" | "-" | "*" ] postfix_expr
    postfix_expr       ::= primary_expr { "." IDENT | call | index | brace_call }
    primary_expr       ::= IDENT
                         | NUMBER
                         | STRING
                         | SYMBOL_ATOM
                         | grouped_expr
                         | quantified_expr

    grouped_expr       ::= "(" [ expression { ("," | ":" | ";" | "|") expression } ] ")"
                         | "[" [ expression { ("," | ":" | ";" | "|") expression } ] "]"
                         | "{" [ expression { ("," | "|" ) expression } ] "}"
    quantified_expr    ::= ("∀" | "∃") "{" [ expression { ("," | "|" ) expression } ] "}"
    call               ::= "(" [ expression { ("," | ":" | ";" | "|") expression } ] ")"
    index              ::= "[" [ expression { ("," | ":" | ";" | "|") expression } ] "]"
    brace_call         ::= "{" [ expression { ("," | "|" ) expression } ] "}"
    infix_op           ::= "->" | "is"
                         | "=" | "==" | "!=" | "≠"
                         | "<" | ">" | "<=" | ">=" | "≤" | "≥"
                         | "∈" | "∉" | "!∈" | "!∉"
                         | "::" | "~"
                         | "+" | "-" | "∪" | "∩"
                         | "*" | "/" | "^"
    """

    def __init__(self, token_stream: TokenStream):
        self.tokens = token_stream
        self.index = 0

    def parse(self) -> Program:
        items = self._parse_block(stop_kinds={"EOF"})
        self._expect(kind="EOF")
        return Program(items=items)

    def _parse_block(self, *, stop_kinds: set[str]) -> list[Statement]:
        items: list[Statement] = []
        while True:
            token = self._peek()
            if token is None or token.kind in stop_kinds:
                return items
            if token.kind == "NEWLINE":
                self._consume()
                continue
            items.append(self._parse_item())

    def _parse_item(self) -> Statement:
        token = self._peek()
        if token is None:
            self._raise_error(None, "unexpected end of token stream")

        if token.kind == "HEADING":
            return self._parse_heading()
        if token.kind == "IMPORT":
            return self._parse_import()
        if token.kind in {"DEDENT", "EOF"}:
            self._raise_error(token, f"unexpected {token.kind.lower()} in block")

        line_tokens = self._read_line_tokens()
        body = self._parse_optional_body()
        return self._parse_line_statement(line_tokens, body)

    def _parse_heading(self) -> Heading:
        token = self._expect(kind="HEADING")
        self._expect(kind="NEWLINE")
        body = self._parse_optional_body()
        return Heading(
            title=token.value,
            body=body,
            line=token.line,
            column=token.column,
        )

    def _parse_import(self) -> Import:
        token = self._expect(kind="IMPORT")
        self._expect(kind="NEWLINE")
        body = self._parse_optional_body()
        return Import(
            module_path=token.value,
            line=token.line,
            column=token.column,
            body=body,
        )

    def _parse_optional_body(self) -> list[Statement]:
        if not self._match(kind="INDENT"):
            return []
        body = self._parse_block(stop_kinds={"DEDENT", "EOF"})
        self._expect(kind="DEDENT")
        return body

    def _read_line_tokens(self) -> list[Token]:
        tokens: list[Token] = []
        depth = 0
        soft_indent_balance = 0
        saw_physical_newline = False
        while True:
            token = self._peek()
            if token is None:
                if tokens and depth == 0 and soft_indent_balance == 0:
                    return tokens
                self._raise_error(None, "unexpected end of token stream in line")
            if (
                saw_physical_newline
                and depth == 0
                and soft_indent_balance == 0
                and token.kind != "NEWLINE"
            ):
                return tokens
            if token.kind == "NEWLINE":
                self._consume()
                saw_physical_newline = True
                if depth == 0 and soft_indent_balance == 0:
                    return tokens
                continue
            if token.kind == "EOF":
                if tokens and depth == 0 and soft_indent_balance == 0:
                    return tokens
                self._raise_error(token, f"unexpected {token.kind.lower()} in line")
            if token.kind in {"INDENT", "DEDENT"}:
                if token.kind == "INDENT" and depth > 0:
                    self._consume()
                    soft_indent_balance += 1
                    continue
                if token.kind == "DEDENT" and (depth > 0 or soft_indent_balance > 0):
                    self._consume()
                    if soft_indent_balance > 0:
                        soft_indent_balance -= 1
                    continue
                self._raise_error(token, f"unexpected {token.kind.lower()} in line")

            if token.kind == "SYMBOL":
                if token.value in {"(", "[", "{"}:
                    depth += 1
                elif token.value in {")", "]", "}"}:
                    depth = max(0, depth - 1)
            tokens.append(self._consume())

    def _parse_line_statement(
        self,
        line_tokens: list[Token],
        body: list[Statement],
    ) -> Statement:
        if not line_tokens:
            token = self._peek(-1)
            return Comment(
                text="",
                line=token.line if token else 1,
                column=token.column if token else 1,
            )

        trailing_comment: str | None = None
        if line_tokens[-1].kind == "COMMENT":
            trailing_comment = line_tokens[-1].value
            if len(line_tokens) == 1:
                token = line_tokens[0]
                return Comment(text=token.value, line=token.line, column=token.column)
            line_tokens = line_tokens[:-1]

        start = line_tokens[0]

        if start.kind == "SYMBOL" and start.value in {"∀", "∃"} and len(line_tokens) == 1:
            return ExpandedCondition(
                quantifier=start.value,
                body=body,
                line=start.line,
                column=start.column,
                trailing_comment=trailing_comment,
            )

        if start.kind == "SYMBOL" and start.value == "|-":
            expr = _LineExpressionParser(line_tokens[1:]).parse_complete()
            return Branch(
                expression=expr,
                body=body,
                line=start.line,
                column=start.column,
                trailing_comment=trailing_comment,
            )

        if start.kind == "SYMBOL" and start.value == "|":
            expr = _LineExpressionParser(line_tokens[1:]).parse_complete()
            return Premise(
                expression=expr,
                body=body,
                line=start.line,
                column=start.column,
                trailing_comment=trailing_comment,
            )

        declaration = self._try_parse_declaration(line_tokens, body, trailing_comment)
        if declaration is not None:
            return declaration

        expr = _LineExpressionParser(line_tokens).parse_complete()
        return ExpressionStatement(
            expression=expr,
            body=body,
            line=start.line,
            column=start.column,
            trailing_comment=trailing_comment,
        )

    def _try_parse_declaration(
        self,
        line_tokens: list[Token],
        body: list[Statement],
        trailing_comment: str | None,
    ) -> Declaration | None:
        colon_index = _find_top_level_symbol(line_tokens, ":")
        if colon_index is None:
            return None

        arrow_index = _find_top_level_symbol(line_tokens[colon_index + 1 :], "=>")
        if arrow_index is None:
            return None
        arrow_index += colon_index + 1

        head_tokens = line_tokens[:colon_index]
        input_tokens = line_tokens[colon_index + 1 : arrow_index]
        output_tokens = line_tokens[arrow_index + 1 :]
        if (
            output_tokens
            and output_tokens[-1].kind == "SYMBOL"
            and output_tokens[-1].value == ":"
            and _find_top_level_symbol(output_tokens[:-1], ":") is None
        ):
            output_tokens = output_tokens[:-1]
        start = line_tokens[0]

        head_expr = _LineExpressionParser(head_tokens).parse_optional()
        input_expr = _LineExpressionParser(input_tokens).parse_optional()
        output_expr = _LineExpressionParser(output_tokens).parse_optional()
        base_head, alias = _split_declaration_head(head_expr)

        return Declaration(
            head=base_head,
            input_expr=input_expr,
            output_expr=output_expr,
            body=body,
            line=start.line,
            column=start.column,
            alias=alias,
            trailing_comment=trailing_comment,
        )

    def _peek(self, offset: int = 0) -> Token | None:
        index = self.index + offset
        if 0 <= index < len(self.tokens):
            return self.tokens[index]
        return None

    def _consume(self) -> Token:
        token = self._peek()
        if token is None:
            self._raise_error(None, "unexpected end of token stream")
        self.index += 1
        return token

    def _match(self, *, kind: str | None = None, value: str | None = None) -> Token | None:
        token = self._peek()
        if token is None:
            return None
        if kind is not None and token.kind != kind:
            return None
        if value is not None and token.value != value:
            return None
        self.index += 1
        return token

    def _expect(self, *, kind: str | None = None, value: str | None = None) -> Token:
        token = self._peek()
        if token is None:
            self._raise_error(None, "unexpected end of token stream")
        if kind is not None and token.kind != kind:
            self._raise_error(token, f"expected {kind}, got {token.kind}")
        if value is not None and token.value != value:
            self._raise_error(token, f"expected {value!r}, got {token.value!r}")
        return self._consume()

    def _raise_error(self, token: Token | None, message: str) -> None:
        if token is None:
            raise ParserError(message)
        raise ParserError(f"{token.line}:{token.column}: {message}")


class _LineExpressionParser:
    _INFIX_PRECEDENCE: Final[dict[str, int]] = {
        "->": 21,
        "is": 15,
        "=": 20,
        "==": 20,
        "!=": 20,
        "≠": 20,
        "<": 20,
        ">": 20,
        "<=": 20,
        ">=": 20,
        "≤": 20,
        "≥": 20,
        "∈": 20,
        "∉": 20,
        "!∈": 20,
        "!∉": 20,
        "::": 25,
        "~": 25,
        "+": 30,
        "-": 30,
        "∪": 30,
        "∩": 30,
        "*": 40,
        "/": 40,
        "^": 50,
    }
    _CUSTOM_INFIX_PRECEDENCE: Final[int] = 30
    _RIGHT_ASSOCIATIVE: Final[set[str]] = {"->", "^"}
    _PREFIX_OPERATORS: Final[set[str]] = {"!", "-", "*"}
    _STOP_VALUES: Final[set[str]] = {",", ":", ";", "|", "=>", ")", "]", "}"}

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def parse_complete(self) -> Expr:
        expr = self.parse_expression()
        token = self._peek()
        if token is None:
            return expr
        if token.kind == "SYMBOL" and token.value == ",":
            return self._parse_sequence(expr)
        self._raise_error(token, f"unexpected token {token.value!r}")

    def parse_optional(self) -> Expr | None:
        if not self.tokens:
            return None
        return self.parse_complete()

    def parse_expression(self, min_precedence: int = 0) -> Expr:
        expr = self._parse_unary()
        while True:
            operator_info = self._peek_infix_operator()
            if operator_info is None:
                return expr

            operator_value, operator_line, operator_column, token_count = operator_info

            precedence = self._operator_precedence(operator_value)
            if precedence < min_precedence:
                return expr

            for _ in range(token_count):
                self._consume()
            next_min_precedence = (
                precedence
                if operator_value in self._RIGHT_ASSOCIATIVE
                else precedence + 1
            )
            right = self.parse_expression(next_min_precedence)
            expr = BinaryExpr(
                left=expr,
                operator=operator_value,
                right=right,
                line=operator_line,
                column=operator_column,
            )

    def _parse_unary(self) -> Expr:
        token = self._peek()
        if token is None:
            self._raise_error(None, "expected expression")
        if (
            token.kind == "SYMBOL"
            and token.value in self._PREFIX_OPERATORS
            and self._can_start_expression(self._peek(1))
        ):
            operator = self._consume()
            operand = self._parse_unary()
            return UnaryExpr(
                operator=operator.value,
                operand=operand,
                line=operator.line,
                column=operator.column,
            )
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            token = self._peek()
            if token is None or token.kind != "SYMBOL":
                return expr

            if token.value == ".":
                dot = self._consume()
                attribute = self._expect_member_name_token()
                expr = AttributeExpr(
                    base=expr,
                    attribute=attribute.value,
                    line=dot.line,
                    column=dot.column,
                )
                continue

            if token.value == "(":
                group = self._parse_delimited("(", ")", {",", ":", ";", "|"})
                expr = CallExpr(
                    callee=expr,
                    args=group.items,
                    separators=group.separators,
                    delimiter="()",
                    line=group.line,
                    column=group.column,
                )
                continue

            if token.value == "[":
                group = self._parse_delimited("[", "]", {",", ":", ";", "|"})
                expr = IndexExpr(
                    base=expr,
                    index=group,
                    line=group.line,
                    column=group.column,
                )
                continue

            if token.value == "{":
                group = self._parse_delimited("{", "}", {",", "|"})
                expr = CallExpr(
                    callee=expr,
                    args=[group],
                    separators=[],
                    delimiter="{}",
                    line=group.line,
                    column=group.column,
                )
                continue

            return expr

    def _parse_primary(self) -> Expr:
        token = self._peek()
        if token is None:
            self._raise_error(None, "expected expression")

        if token.kind == "IDENT":
            ident = self._consume()
            return IdentifierExpr(name=ident.value, line=ident.line, column=ident.column)

        if token.kind == "NUMBER":
            number = self._consume()
            return NumberExpr(value=number.value, line=number.line, column=number.column)

        if token.kind == "STRING":
            literal = self._consume()
            return StringExpr(value=literal.value, line=literal.line, column=literal.column)

        if token.kind != "SYMBOL":
            self._raise_error(token, f"unexpected token {token.kind}")

        if token.value in {".", "::"}:
            punct = self._consume()
            attribute = self._expect_member_name_token()
            return AttributeExpr(
                base=None,
                attribute=attribute.value,
                line=punct.line,
                column=punct.column,
            )

        if token.value in {"∀", "∃"} and self._peek(1) is not None and self._peek(1).kind == "SYMBOL" and self._peek(1).value == "{":
            quantifier = self._consume()
            body = self._parse_delimited("{", "}", {",", "|"})
            return QuantifiedExpr(
                quantifier=quantifier.value,
                body=body,
                line=quantifier.line,
                column=quantifier.column,
            )

        if token.value == "(":
            return self._parse_delimited("(", ")", {",", ":", ";", "|"})

        if token.value == "[":
            return self._parse_delimited("[", "]", {",", ":", ";", "|"})

        if token.value == "{":
            return self._parse_delimited("{", "}", {",", "|"})

        symbol = self._consume()
        return SymbolExpr(value=symbol.value, line=symbol.line, column=symbol.column)

    def _parse_delimited(
        self,
        opener: str,
        closer: str,
        separators: set[str],
    ) -> DelimitedExpr:
        opening = self._expect(kind="SYMBOL", value=opener)
        items: list[Expr | None] = []
        seen_separators: list[str] = []
        expecting_item = True

        while True:
            token = self._peek()
            if token is None:
                self._raise_error(None, f"expected closing {closer!r}")
            if token.kind == "SYMBOL" and token.value == closer:
                self._consume()
                return DelimitedExpr(
                    opener=opener,
                    items=items,
                    separators=seen_separators,
                    closer=closer,
                    line=opening.line,
                    column=opening.column,
                )

            if token.kind == "SYMBOL" and token.value in separators:
                if expecting_item:
                    items.append(None)
                seen_separators.append(self._consume().value)
                expecting_item = True
                continue

            items.append(self.parse_expression())
            expecting_item = False
            token = self._peek()
            if token is None:
                self._raise_error(None, f"expected closing {closer!r}")
            if token.kind == "SYMBOL" and token.value in separators:
                seen_separators.append(self._consume().value)
                expecting_item = True
                continue
            if token.kind == "SYMBOL" and token.value == closer:
                continue
            self._raise_error(token, f"expected separator or closing {closer!r}")

    def _parse_sequence(self, first: Expr) -> SequenceExpr:
        items: list[Expr | None] = [first]
        separators: list[str] = []

        while True:
            token = self._peek()
            if token is None or token.kind != "SYMBOL" or token.value != ",":
                return SequenceExpr(
                    items=items,
                    separators=separators,
                    line=first.line,
                    column=first.column,
                )

            separators.append(self._consume().value)
            next_token = self._peek()
            if next_token is None:
                items.append(None)
                return SequenceExpr(
                    items=items,
                    separators=separators,
                    line=first.line,
                    column=first.column,
                )
            items.append(self.parse_expression())

    def _peek_infix_operator(self) -> tuple[str, int, int, int] | None:
        token = self._peek()
        if token is None:
            return None

        if token.kind == "SYMBOL" and token.value == "!":
            next_token = self._peek(1)
            if next_token is not None and next_token.kind in {"SYMBOL", "IDENT"}:
                combined = f"{token.value}{next_token.value}"
                if combined in self._INFIX_PRECEDENCE:
                    return combined, token.line, token.column, 2

        if token.kind == "SYMBOL" and token.value in self._INFIX_PRECEDENCE:
            return token.value, token.line, token.column, 1

        if token.kind == "IDENT" and token.value in self._INFIX_PRECEDENCE:
            return token.value, token.line, token.column, 1

        if token.kind == "IDENT" and _is_latex_name(token.value):
            return token.value, token.line, token.column, 1

        if token.kind == "SYMBOL" and _is_custom_operator_alias(token.value):
            return token.value, token.line, token.column, 1

        return None

    def _operator_precedence(self, operator_value: str) -> int:
        return self._INFIX_PRECEDENCE.get(
            operator_value,
            self._CUSTOM_INFIX_PRECEDENCE,
        )

    def _can_start_expression(self, token: Token | None) -> bool:
        if token is None:
            return False
        if token.kind in {"IDENT", "NUMBER", "STRING"}:
            return True
        if token.kind != "SYMBOL":
            return False
        return token.value not in self._STOP_VALUES

    def _peek(self, offset: int = 0) -> Token | None:
        index = self.index + offset
        if 0 <= index < len(self.tokens):
            return self.tokens[index]
        return None

    def _consume(self) -> Token:
        token = self._peek()
        if token is None:
            self._raise_error(None, "unexpected end of expression")
        self.index += 1
        return token

    def _expect(self, *, kind: str | None = None, value: str | None = None) -> Token:
        token = self._peek()
        if token is None:
            self._raise_error(None, "unexpected end of expression")
        if kind is not None and token.kind != kind:
            self._raise_error(token, f"expected {kind}, got {token.kind}")
        if value is not None and token.value != value:
            self._raise_error(token, f"expected {value!r}, got {token.value!r}")
        return self._consume()

    def _raise_error(self, token: Token | None, message: str) -> None:
        if token is None:
            raise ParserError(message)
        raise ParserError(f"{token.line}:{token.column}: {message}")

    def _expect_member_name_token(self) -> Token:
        token = self._peek()
        if token is None:
            self._raise_error(None, "expected member name")
        if token.kind == "IDENT":
            return self._consume()
        if token.kind == "SYMBOL" and token.value not in {"(", ")", "[", "]", "{", "}", ",", ".", ":", ";", "|", "=>", "|-"}:
            return self._consume()
        self._raise_error(token, f"expected member name, got {token.kind}")


def _is_custom_operator_alias(value: str) -> bool:
    if len(value) != 1 or value.isascii():
        return False
    if value in _LineExpressionParser._INFIX_PRECEDENCE:
        return False
    if value in _LineExpressionParser._STOP_VALUES:
        return False
    return not value.isalpha() and not value.isdigit() and value != "_"


def _is_latex_name(value: str) -> bool:
    return len(value) > 1 and value[0] == "\\" and all(
        char.isalnum() or char == "_" or char == "'" for char in value[1:]
    )


def _find_top_level_symbol(tokens: list[Token], value: str) -> int | None:
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind != "SYMBOL":
            continue
        if token.value in {"(", "[", "{"}:
            depth += 1
            continue
        if token.value in {")", "]", "}"}:
            depth -= 1
            continue
        if depth == 0 and token.value == value:
            return index
    return None


def _split_declaration_head(head: Expr | None) -> tuple[Expr | None, Expr | None]:
    if not isinstance(head, CallExpr):
        return head, None
    if head.delimiter != "()":
        return head, None
    if len(head.args) != 1:
        return head, None
    if not isinstance(head.callee, (IdentifierExpr, AttributeExpr, SymbolExpr)):
        return head, None
    return head.callee, head.args[0]


def _collect_lambda_bound_symbols(expr: Expr | None) -> frozenset[str]:
    if expr is None:
        return frozenset()

    bound_symbols: set[str] = set()

    if isinstance(expr, IdentifierExpr):
        return frozenset({expr.name})

    if isinstance(expr, SequenceExpr):
        for item in expr.items:
            bound_symbols.update(_collect_lambda_bound_symbols(item))
        return frozenset(bound_symbols)

    if isinstance(expr, DelimitedExpr):
        for item in expr.items:
            bound_symbols.update(_collect_lambda_bound_symbols(item))
        return frozenset(bound_symbols)

    if isinstance(expr, UnaryExpr):
        return _collect_lambda_bound_symbols(expr.operand)

    return frozenset()


def _validate_block(
    items: list[Node],
    issues: list[SemanticIssue],
    *,
    allow_condition_clauses: bool,
    available_symbols: frozenset[str],
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
) -> None:
    current_symbols = set(available_symbols)

    for item in items:
        if isinstance(item, Heading):
            if not item.body:
                issues.append(
                    SemanticIssue(
                        message="heading must contain an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_block(
                item.body,
                issues,
                allow_condition_clauses=False,
                available_symbols=frozenset(current_symbols),
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            continue

        if isinstance(item, Import):
            if not item.module_path.strip():
                issues.append(
                    SemanticIssue(
                        message="import path must not be empty",
                        line=item.line,
                        column=item.column,
                    )
                )
            if item.body:
                issues.append(
                    SemanticIssue(
                        message="import cannot have an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            continue

        if isinstance(item, ExpandedCondition):
            if not item.body:
                issues.append(
                    SemanticIssue(
                        message="expanded condition must contain an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(current_symbols),
                enforce_target_symbol_flow=item.quantifier == "∀",
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            continue

        if isinstance(item, Branch):
            if not allow_condition_clauses:
                issues.append(
                    SemanticIssue(
                        message="branch clause '|-' is only valid inside an expanded condition",
                        line=item.line,
                        column=item.column,
                    )
                )
            if not item.body:
                issues.append(
                    SemanticIssue(
                        message="branch clause must contain an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(
                    current_symbols
                    | _statement_exposed_symbols(
                        item, non_premise_symbols=non_premise_symbols
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            continue

        if isinstance(item, Premise):
            if not allow_condition_clauses:
                issues.append(
                    SemanticIssue(
                        message="premise clause '|' is only valid inside an expanded condition",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(
                    current_symbols
                    | _statement_exposed_symbols(
                        item, non_premise_symbols=non_premise_symbols
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            continue

        if isinstance(item, Declaration):
            if item.input_expr is None or item.output_expr is None:
                issues.append(
                    SemanticIssue(
                        message="declaration signature must contain both input and output expressions",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(
                    current_symbols
                    | _statement_exposed_symbols(
                        item, non_premise_symbols=non_premise_symbols
                    )
                ),
                enforce_target_symbol_flow=False,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            current_symbols.update(
                _statement_exposed_symbols(item, non_premise_symbols=non_premise_symbols)
            )
            continue

        if isinstance(item, ExpressionStatement):
            _validate_block(
                item.body,
                issues,
                allow_condition_clauses=False,
                available_symbols=frozenset(
                    current_symbols
                    | _statement_exposed_symbols(
                        item, non_premise_symbols=non_premise_symbols
                    )
                ),
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
            current_symbols.update(
                _statement_exposed_symbols(item, non_premise_symbols=non_premise_symbols)
            )
            continue

        if isinstance(item, Comment):
            if item.body:
                issues.append(
                    SemanticIssue(
                        message="comment cannot have an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            continue

        if isinstance(item, Statement):
            current_symbols.update(
                _statement_exposed_symbols(item, non_premise_symbols=non_premise_symbols)
            )


def _validate_condition_body(
    items: list[Statement],
    issues: list[SemanticIssue],
    *,
    available_symbols: frozenset[str],
    enforce_target_symbol_flow: bool,
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
) -> frozenset[str]:
    current_symbols = set(available_symbols)
    branch_end_symbols: list[frozenset[str]] = []
    index = 0

    while index < len(items):
        item = items[index]
        if isinstance(item, Comment):
            if item.body:
                issues.append(
                    SemanticIssue(
                        message="comment cannot have an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            index += 1
            continue

        if isinstance(item, Branch):
            branches: list[Branch] = []
            while index < len(items) and isinstance(items[index], Branch):
                branches.append(items[index])
                index += 1

            _validate_branch_group(branches, issues)

            prior_branch_exprs: list[Expr] = []
            for branch in branches:
                if not branch.body:
                    issues.append(
                        SemanticIssue(
                            message="branch clause must contain an indented body",
                            line=branch.line,
                            column=branch.column,
                        )
                    )
                branch_expr = _resolve_branch_premise_expr(branch, prior_branch_exprs)
                branch_symbols = set(current_symbols) | _collect_expr_exposed_symbols(
                    branch_expr,
                    non_premise_symbols=non_premise_symbols,
                )
                branch_end_symbols.append(
                    _validate_condition_body(
                        branch.body,
                        issues,
                        available_symbols=frozenset(branch_symbols),
                        enforce_target_symbol_flow=enforce_target_symbol_flow,
                        non_premise_symbols=non_premise_symbols,
                        semantic_index=semantic_index,
                    )
                )
                if not _is_else_identifier(branch.expression):
                    prior_branch_exprs.append(branch.expression)
            continue

        if branch_end_symbols:
            current_symbols = _merge_branch_symbol_sets(
                branch_end_symbols,
                fallback=current_symbols,
                )
            branch_end_symbols.clear()

        if isinstance(item, Premise):
            if _statement_contains_reserved_else(item):
                _append_reserved_else_issue(item, issues)
            premise_symbols = set(current_symbols) | _statement_exposed_symbols(
                item, non_premise_symbols=non_premise_symbols
            )
            if item.body:
                _validate_condition_body(
                    item.body,
                    issues,
                    available_symbols=frozenset(premise_symbols),
                    enforce_target_symbol_flow=enforce_target_symbol_flow,
                    non_premise_symbols=non_premise_symbols,
                    semantic_index=semantic_index,
                )
            current_symbols = premise_symbols
            index += 1
            continue

        if _statement_contains_reserved_else(item):
            _append_reserved_else_issue(item, issues)

        target_exprs = (
            _split_expanded_target_exprs(item.expression)
            if isinstance(item, ExpressionStatement)
            else None
        )

        if enforce_target_symbol_flow:
            if target_exprs is not None:
                for target_expr in target_exprs:
                    missing_symbols = (
                        _collect_expanded_target_required_symbols(
                            target_expr,
                            non_premise_symbols=non_premise_symbols,
                        )
                        - current_symbols
                    )
                    if missing_symbols:
                        issues.append(
                            SemanticIssue(
                                message=(
                                    "expanded ∀ target uses symbols not available from prior premises: "
                                    + ", ".join(sorted(missing_symbols))
                                ),
                                line=target_expr.line,
                                column=target_expr.column,
                            )
                        )
            else:
                missing_symbols = (
                    _statement_required_symbols(
                        item, non_premise_symbols=non_premise_symbols
                    )
                    - current_symbols
                )
                if missing_symbols:
                    issues.append(
                        SemanticIssue(
                            message=(
                                "expanded ∀ target uses symbols not available from prior premises: "
                                + ", ".join(sorted(missing_symbols))
                            ),
                            line=item.line,
                            column=item.column,
                        )
                    )

        next_symbols = set(current_symbols)
        if target_exprs is None:
            next_symbols.update(
                _statement_exposed_symbols(item, non_premise_symbols=non_premise_symbols)
            )
        else:
            for target_expr in target_exprs:
                next_symbols.update(
                    _collect_expr_exposed_symbols(
                        target_expr,
                        non_premise_symbols=non_premise_symbols,
                    )
                )

        if isinstance(item, ExpandedCondition):
            if not item.body:
                issues.append(
                    SemanticIssue(
                        message="expanded condition must contain an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=item.quantifier == "∀",
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
        elif isinstance(item, Declaration):
            if item.input_expr is None or item.output_expr is None:
                issues.append(
                    SemanticIssue(
                        message="declaration signature must contain both input and output expressions",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=False,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
        elif isinstance(item, ExpressionStatement):
            _validate_condition_body(
                item.body,
                issues,
                available_symbols=frozenset(next_symbols),
                enforce_target_symbol_flow=enforce_target_symbol_flow,
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
        elif isinstance(item, Heading):
            if not item.body:
                issues.append(
                    SemanticIssue(
                        message="heading must contain an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )
            _validate_block(
                item.body,
                issues,
                allow_condition_clauses=False,
                available_symbols=frozenset(next_symbols),
                non_premise_symbols=non_premise_symbols,
                semantic_index=semantic_index,
            )
        elif isinstance(item, Import):
            if not item.module_path.strip():
                issues.append(
                    SemanticIssue(
                        message="import path must not be empty",
                        line=item.line,
                        column=item.column,
                    )
                )
            if item.body:
                issues.append(
                    SemanticIssue(
                        message="import cannot have an indented body",
                        line=item.line,
                        column=item.column,
                    )
                )

        current_symbols = next_symbols
        index += 1

    if branch_end_symbols:
        current_symbols = _merge_branch_symbol_sets(
            branch_end_symbols,
            fallback=current_symbols,
        )

    return frozenset(current_symbols)


def _merge_branch_symbol_sets(
    branch_sets: list[frozenset[str]],
    *,
    fallback: set[str],
) -> set[str]:
    if not branch_sets:
        return set(fallback)
    merged = set(branch_sets[0])
    for branch_set in branch_sets[1:]:
        merged.intersection_update(branch_set)
    return merged


def _validate_branch_group(branches: list[Branch], issues: list[SemanticIssue]) -> None:
    else_indexes = [
        index for index, branch in enumerate(branches) if _is_else_identifier(branch.expression)
    ]
    if else_indexes:
        if len(branches) == 1:
            issues.append(
                SemanticIssue(
                    message="'else' branch requires at least one preceding branch",
                    line=branches[0].line,
                    column=branches[0].column,
                )
            )
        first_else = else_indexes[0]
        if first_else != len(branches) - 1:
            issues.append(
                SemanticIssue(
                    message="'else' branch must be the final branch in its group",
                    line=branches[first_else].line,
                    column=branches[first_else].column,
                )
            )
        for extra_else in else_indexes[1:]:
            issues.append(
                SemanticIssue(
                    message="only one 'else' branch is allowed in a branch group",
                    line=branches[extra_else].line,
                    column=branches[extra_else].column,
                )
            )

    for branch in branches:
        if _statement_contains_reserved_else(branch):
            if not _is_else_identifier(branch.expression):
                _append_reserved_else_issue(branch, issues)


def _statement_contains_reserved_else(statement: Statement) -> bool:
    if isinstance(statement, Branch):
        return _expr_contains_identifier(statement.expression, "else") and not _is_else_identifier(
            statement.expression
        )
    if isinstance(statement, (ExpressionStatement, Premise)):
        return _expr_contains_identifier(statement.expression, "else")
    if isinstance(statement, Declaration):
        return any(
            _expr_contains_identifier(expr, "else")
            for expr in (
                statement.head,
                statement.alias,
                statement.input_expr,
                statement.output_expr,
            )
        )
    return False


def _append_reserved_else_issue(statement: Statement, issues: list[SemanticIssue]) -> None:
    issues.append(
        SemanticIssue(
            message="'else' is reserved for the final branch guard '|- else'",
            line=statement.line,
            column=statement.column,
        )
    )


def _expr_contains_identifier(expr: Expr | None, name: str) -> bool:
    if expr is None:
        return False
    if isinstance(expr, IdentifierExpr):
        return expr.name == name
    if isinstance(expr, UnaryExpr):
        return _expr_contains_identifier(expr.operand, name)
    if isinstance(expr, BinaryExpr):
        return _expr_contains_identifier(expr.left, name) or _expr_contains_identifier(
            expr.right, name
        )
    if isinstance(expr, (SequenceExpr, DelimitedExpr)):
        return any(_expr_contains_identifier(item, name) for item in expr.items)
    if isinstance(expr, AttributeExpr):
        return _expr_contains_identifier(expr.base, name)
    if isinstance(expr, CallExpr):
        return _expr_contains_identifier(expr.callee, name) or any(
            _expr_contains_identifier(arg, name) for arg in expr.args
        )
    if isinstance(expr, IndexExpr):
        return _expr_contains_identifier(expr.base, name) or _expr_contains_identifier(
            expr.index, name
        )
    if isinstance(expr, QuantifiedExpr):
        return _expr_contains_identifier(expr.body, name)
    return False


def _is_else_identifier(expr: Expr) -> bool:
    return isinstance(expr, IdentifierExpr) and expr.name == "else"


def _collect_expanded_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(expr, IdentifierExpr):
        return set()
    return _collect_expr_required_symbols(
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _statement_required_symbols(
    statement: Statement,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(statement, (ExpressionStatement, Premise, Branch)):
        return _collect_expr_required_symbols(
            statement.expression,
            non_premise_symbols=non_premise_symbols,
        )

    if isinstance(statement, Declaration):
        symbols: set[str] = set()
        symbols.update(
            _collect_expr_required_symbols(
                statement.alias, non_premise_symbols=non_premise_symbols
            )
        )
        symbols.update(
            _collect_expr_required_symbols(
                statement.input_expr, non_premise_symbols=non_premise_symbols
            )
        )
        symbols.update(
            _collect_expr_required_symbols(
                statement.output_expr, non_premise_symbols=non_premise_symbols
            )
        )
        return symbols

    return set()


def _statement_exposed_symbols(
    statement: Statement,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(statement, (ExpressionStatement, Premise, Branch)):
        return _collect_expr_exposed_symbols(
            statement.expression,
            non_premise_symbols=non_premise_symbols,
        )

    if isinstance(statement, Declaration):
        symbols: set[str] = set()
        symbols.update(
            _collect_expr_exposed_symbols(
                statement.head, non_premise_symbols=non_premise_symbols
            )
        )
        symbols.update(
            _collect_expr_exposed_symbols(
                statement.alias, non_premise_symbols=non_premise_symbols
            )
        )
        symbols.update(
            _collect_expr_exposed_symbols(
                statement.input_expr, non_premise_symbols=non_premise_symbols
            )
        )
        symbols.update(
            _collect_expr_exposed_symbols(
                statement.output_expr, non_premise_symbols=non_premise_symbols
            )
        )
        return symbols

    return set()


_STATIC_NON_PREMISE_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "null",
        "true",
        "false",
        "else",
        "identity_function",
    }
)

_OPAQUE_FUNCTION_NAMES: Final[frozenset[str]] = frozenset({"sum", "condition"})


def _validate_program_semantics(
    root_node: Node,
    issues: list[SemanticIssue],
    *,
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
) -> None:
    _validate_function_inheritance_relations(issues, semantic_index=semantic_index)

    for statement, in_condition in _walk_statements(root_node, in_condition=False):
        if not in_condition and _statement_contains_reserved_else(statement):
            _append_reserved_else_issue(statement, issues)

        for expr in _walk_exprs(statement):
            if isinstance(expr, BinaryExpr) and _is_custom_operator_alias(expr.operator):
                _validate_custom_operator_usage(
                    expr,
                    issues,
                    semantic_index=semantic_index,
                )
            if isinstance(expr, CallExpr):
                _validate_call_expression(
                    expr,
                    issues,
                    semantic_index=semantic_index,
                )


def _walk_statements(
    node: Node,
    *,
    in_condition: bool,
) -> Iterator[tuple[Statement, bool]]:
    if isinstance(node, Program):
        for item in node.items:
            yield from _walk_statements(item, in_condition=in_condition)
        return

    if not isinstance(node, Statement):
        return

    yield node, in_condition

    child_in_condition = in_condition or isinstance(node, (Condition, Premise, Branch))
    for child in node.body:
        yield from _walk_statements(child, in_condition=child_in_condition)


def _walk_exprs(node: Node) -> Iterator[Expr]:
    if isinstance(node, Expr):
        yield node
    for child in node.children():
        yield from _walk_exprs(child)


def _validate_function_inheritance_relations(
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
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
        issues.append(
            SemanticIssue(
                message=(
                    "function inheritance requires matching signatures between "
                    f"{parent_name} and {child_name}"
                ),
                line=line,
                column=column,
            )
        )


def _validate_custom_operator_usage(
    expr: BinaryExpr,
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
    alias_specs = semantic_index.operator_aliases.get(expr.operator, [])
    if any(signature.call_arity() == 1 or signature.arity == 2 for signature in alias_specs):
        return
    issues.append(
        SemanticIssue(
            message=f"custom operator {expr.operator!r} has no matching alias declaration",
            line=expr.line,
            column=expr.column,
        )
    )


def _validate_call_expression(
    expr: CallExpr,
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
    signatures = _candidate_call_signatures(expr.callee, semantic_index=semantic_index)
    if not signatures:
        return

    arg_counts = _call_arg_count_options(expr)
    if arg_counts is None:
        matching_signatures = list(signatures)
    else:
        matching_signatures = [
            signature
            for signature in signatures
            if signature.call_arity() in arg_counts
        ]
    if not matching_signatures:
        if isinstance(expr.callee, AttributeExpr) and any(
            signature.call_arity() == 0 for signature in signatures
        ):
            return
        actual_count = len([arg for arg in expr.args if arg is not None])
        issues.append(
            SemanticIssue(
                message=(
                    f"call arity mismatch: expected "
                    f"{_format_expected_arities(signatures)}, got {actual_count}"
                ),
                line=expr.line,
                column=expr.column,
            )
        )
        return

    if arg_counts is None:
        return

    for signature in matching_signatures:
        violation = _find_subclass_dispatch_violation(
            expr,
            signature=signature,
            semantic_index=semantic_index,
        )
        if violation is None:
            return

    expected_parent_class, actual_child_class = _find_subclass_dispatch_violation(
        expr,
        signature=matching_signatures[0],
        semantic_index=semantic_index,
    ) or (None, None)
    if expected_parent_class is None or actual_child_class is None:
        return

    issues.append(
        SemanticIssue(
            message=(
                "direct subclass-to-parent call dispatch is not allowed; "
                f"rebind {actual_child_class}-typed symbols to {expected_parent_class}-typed "
                "symbols before the call"
            ),
            line=expr.line,
            column=expr.column,
        )
    )


def _call_arg_count_options(expr: CallExpr) -> set[int] | None:
    total = 0
    for arg in expr.args:
        if arg is None:
            continue
        expanded = _expanded_arg_width(arg)
        if expanded is None:
            return None
        total += expanded
    return {total}


def _expanded_arg_width(expr: Expr) -> int | None:
    if (
        isinstance(expr, UnaryExpr)
        and expr.operator == "*"
    ):
        operand = expr.operand
        if isinstance(operand, (DelimitedExpr, SequenceExpr)):
            return len([item for item in operand.items if item is not None])
        return None
    return 1


def _candidate_call_signatures(
    callee: Expr,
    *,
    semantic_index: SemanticIndex,
) -> list[SignatureSpec]:
    if isinstance(callee, IdentifierExpr):
        if callee.name in _OPAQUE_FUNCTION_NAMES:
            return []
        signatures = list(semantic_index.function_signatures_by_name.get(callee.name, []))
        if _looks_like_class_identifier(callee.name, semantic_index):
            owner_candidates = [
                callee.name,
                *_parent_classes_for(callee.name, semantic_index),
            ]
            for owner_class in owner_candidates:
                signatures.extend(
                    semantic_index.member_signatures_by_key.get(
                        (owner_class, "call"),
                        [],
                    )
                )
        return signatures

    if isinstance(callee, AttributeExpr):
        receiver_class = _infer_expr_class(
            callee.base,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        if receiver_class is not None:
            signatures: list[SignatureSpec] = []
            owner_candidates = [receiver_class, *_parent_classes_for(receiver_class, semantic_index)]
            for owner_class in owner_candidates:
                signatures.extend(
                    semantic_index.member_signatures_by_key.get(
                        (owner_class, callee.attribute),
                        [],
                    )
                )
            if signatures:
                return signatures

        fallback_signatures: list[SignatureSpec] = []
        for (owner_class, member_name), member_signatures in (
            semantic_index.member_signatures_by_key.items()
        ):
            if member_name != callee.attribute:
                continue
            fallback_signatures.extend(member_signatures)
        return fallback_signatures

    return []


def _format_expected_arities(signatures: list[SignatureSpec]) -> str:
    return ", ".join(str(arity) for arity in sorted({sig.call_arity() for sig in signatures}))


def _find_subclass_dispatch_violation(
    expr: CallExpr,
    *,
    signature: SignatureSpec,
    semantic_index: SemanticIndex,
) -> tuple[str, str] | None:
    expected_classes = signature.call_arg_classes()
    call_args = [arg for arg in expr.args if arg is not None]
    for expected_class, arg in zip(expected_classes, call_args):
        if expected_class is None:
            continue
        actual_class = _infer_expr_class(
            arg,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        if actual_class is None or actual_class == expected_class:
            continue
        if _is_subclass_of(
            expected_class,
            actual_class,
            semantic_index=semantic_index,
        ):
            return expected_class, actual_class
    return None


def _parent_classes_for(
    class_name: str,
    semantic_index: SemanticIndex,
) -> tuple[str, ...]:
    parents_by_child: dict[str, tuple[str, ...]] = {}
    for parent_class, child_class in semantic_index.class_inheritance_relations:
        parents_by_child.setdefault(child_class, ())
        parents_by_child[child_class] = tuple(
            sorted(set(parents_by_child[child_class]) | {parent_class})
        )
    return _reachable_class_relations(
        parents_by_child,
        class_name,
        transitive=True,
    )


def _is_subclass_of(
    parent_class: str,
    child_class: str,
    *,
    semantic_index: SemanticIndex,
) -> bool:
    if parent_class == child_class:
        return False
    return parent_class in _parent_classes_for(child_class, semantic_index)


def _infer_expr_class(
    expr: Expr | None,
    *,
    semantic_index: SemanticIndex,
    allow_uppercase_fallback: bool,
) -> str | None:
    if isinstance(expr, IdentifierExpr):
        return _infer_symbol_class_name(
            expr.name,
            semantic_index=semantic_index,
            allow_uppercase_fallback=allow_uppercase_fallback,
        )
    return None


def _infer_symbol_class_name(
    name: str,
    *,
    semantic_index: SemanticIndex,
    allow_uppercase_fallback: bool,
) -> str | None:
    explicit_classes = {
        parent_class
        for parent_class, symbol_name in semantic_index.symbol_inheritance_relations
        if symbol_name == name
    }
    if len(explicit_classes) == 1:
        return next(iter(explicit_classes))

    candidates = _class_candidates_from_name(name)
    for candidate in candidates:
        if candidate in semantic_index.class_names:
            return candidate

    if allow_uppercase_fallback:
        for candidate in candidates:
            if _looks_like_class_identifier(candidate, semantic_index):
                return candidate

    return None


def _class_candidates_from_name(name: str) -> tuple[str, ...]:
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


def _collect_expr_required_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if expr is None:
        return set()

    if isinstance(expr, IdentifierExpr):
        if expr.name in non_premise_symbols:
            return set()
        return {expr.name}

    if isinstance(expr, (NumberExpr, StringExpr, SymbolExpr)):
        return set()

    if isinstance(expr, UnaryExpr):
        return _collect_expr_required_symbols(
            expr.operand, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr):
        if expr.operator == "->":
            bound_symbols = _collect_lambda_bound_symbols(expr.left)
            return (
                _collect_expr_required_symbols(
                    expr.left, non_premise_symbols=non_premise_symbols
                )
                - bound_symbols
            ) | (
                _collect_expr_required_symbols(
                    expr.right,
                    non_premise_symbols=non_premise_symbols | bound_symbols,
                )
                - bound_symbols
            )
        if expr.operator == "=":
            return _collect_assignment_target_required_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            ) | _collect_expr_required_symbols(
                expr.right, non_premise_symbols=non_premise_symbols
            )
        return _collect_expr_required_symbols(
            expr.left, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_required_symbols(
            expr.right, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, SequenceExpr):
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_expr_required_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, DelimitedExpr):
        if "|" in expr.separators:
            return _collect_pipe_delimited_required_symbols(
                expr, non_premise_symbols=non_premise_symbols
            )
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_expr_required_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_expr_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if not isinstance(expr.callee, IdentifierExpr):
            symbols.update(
                _collect_expr_required_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_expr_required_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_expr_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_required_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, QuantifiedExpr):
        return _collect_expr_required_symbols(
            expr.body, non_premise_symbols=non_premise_symbols
        )

    return set()


def _collect_expr_exposed_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if expr is None:
        return set()

    if isinstance(expr, IdentifierExpr):
        if expr.name in non_premise_symbols:
            return set()
        return {expr.name}

    if isinstance(expr, (NumberExpr, StringExpr, SymbolExpr)):
        return set()

    if isinstance(expr, UnaryExpr):
        return _collect_expr_exposed_symbols(
            expr.operand, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr):
        if expr.operator == "->":
            bound_symbols = _collect_lambda_bound_symbols(expr.left)
            return (
                _collect_expr_exposed_symbols(
                    expr.left, non_premise_symbols=non_premise_symbols
                )
                - bound_symbols
            ) | (
                _collect_expr_exposed_symbols(
                    expr.right,
                    non_premise_symbols=non_premise_symbols | bound_symbols,
                )
                - bound_symbols
            )
        if expr.operator == "=":
            return _collect_assignment_target_exposed_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            ) | _collect_expr_exposed_symbols(
                expr.right, non_premise_symbols=non_premise_symbols
            )
        return _collect_expr_exposed_symbols(
            expr.left, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_exposed_symbols(
            expr.right, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, SequenceExpr):
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_expr_exposed_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, DelimitedExpr):
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_expr_exposed_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_expr_exposed_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if isinstance(expr.callee, IdentifierExpr):
            symbols.add(expr.callee.name)
        else:
            symbols.update(
                _collect_expr_exposed_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_expr_exposed_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_expr_exposed_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_exposed_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, QuantifiedExpr):
        return _collect_expr_exposed_symbols(
            expr.body, non_premise_symbols=non_premise_symbols
        )

    return set()


def _collect_assignment_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(expr, IdentifierExpr):
        return set()

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_expr_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if not isinstance(expr.callee, IdentifierExpr):
            symbols.update(
                _collect_expr_required_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_expr_required_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_expr_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_required_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr) and expr.operator == "->":
        bound_symbols = _collect_lambda_bound_symbols(expr.left)
        return (
            _collect_assignment_target_required_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            )
            - bound_symbols
        ) | (
            _collect_expr_required_symbols(
                expr.right,
                non_premise_symbols=non_premise_symbols | bound_symbols,
            )
            - bound_symbols
        )

    return _collect_expr_required_symbols(expr, non_premise_symbols=non_premise_symbols)


def _collect_assignment_target_exposed_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(expr, IdentifierExpr):
        if expr.name in non_premise_symbols:
            return set()
        return {expr.name}

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_expr_exposed_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if isinstance(expr.callee, IdentifierExpr):
            symbols.add(expr.callee.name)
        else:
            symbols.update(
                _collect_expr_exposed_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_expr_exposed_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_expr_exposed_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_expr_exposed_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr) and expr.operator == "->":
        bound_symbols = _collect_lambda_bound_symbols(expr.left)
        return (
            _collect_assignment_target_exposed_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            )
            - bound_symbols
        ) | (
            _collect_expr_exposed_symbols(
                expr.right,
                non_premise_symbols=non_premise_symbols | bound_symbols,
            )
            - bound_symbols
        )

    return _collect_expr_exposed_symbols(expr, non_premise_symbols=non_premise_symbols)


def _collect_pipe_delimited_required_symbols(
    expr: DelimitedExpr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    required: set[str] = set()
    available_to_left: set[str] = set()

    for item in reversed(expr.items):
        if item is None:
            continue
        required.update(
            _collect_premise_required_symbols(
                item, non_premise_symbols=non_premise_symbols
            )
            - available_to_left
        )
        available_to_left.update(
            _collect_expr_exposed_symbols(
                item, non_premise_symbols=non_premise_symbols
            )
        )

    return required


def _collect_premise_required_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if expr is None:
        return set()

    if isinstance(expr, IdentifierExpr):
        return set()

    if isinstance(expr, (NumberExpr, StringExpr, SymbolExpr)):
        return set()

    if isinstance(expr, UnaryExpr):
        return _collect_premise_required_symbols(
            expr.operand, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr):
        if expr.operator == "->":
            bound_symbols = _collect_lambda_bound_symbols(expr.left)
            return (
                _collect_premise_target_required_symbols(
                    expr.left, non_premise_symbols=non_premise_symbols
                )
                - bound_symbols
            ) | (
                _collect_premise_required_symbols(
                    expr.right,
                    non_premise_symbols=non_premise_symbols | bound_symbols,
                )
                - bound_symbols
            )
        if expr.operator in {"=", "∈", "∉", "!∈", "!∉", "is", "~"}:
            return _collect_premise_target_required_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            ) | _collect_premise_required_symbols(
                expr.right, non_premise_symbols=non_premise_symbols
            )
        return _collect_premise_required_symbols(
            expr.left, non_premise_symbols=non_premise_symbols
        ) | _collect_premise_required_symbols(
            expr.right, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, SequenceExpr):
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_premise_required_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, DelimitedExpr):
        if "|" in expr.separators:
            return _collect_pipe_delimited_required_symbols(
                expr, non_premise_symbols=non_premise_symbols
            )
        symbols: set[str] = set()
        for item in expr.items:
            symbols.update(
                _collect_premise_required_symbols(
                    item, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_premise_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if not isinstance(expr.callee, IdentifierExpr):
            symbols.update(
                _collect_premise_required_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_premise_required_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_premise_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_premise_required_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, QuantifiedExpr):
        return _collect_premise_required_symbols(
            expr.body, non_premise_symbols=non_premise_symbols
        )

    return set()


def _collect_premise_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    if isinstance(expr, IdentifierExpr):
        return set()

    if isinstance(expr, AttributeExpr):
        if expr.base is None:
            return set()
        return _collect_premise_target_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, CallExpr):
        symbols: set[str] = set()
        if not isinstance(expr.callee, IdentifierExpr):
            symbols.update(
                _collect_premise_target_required_symbols(
                    expr.callee, non_premise_symbols=non_premise_symbols
                )
            )
        for arg in expr.args:
            symbols.update(
                _collect_premise_required_symbols(
                    arg, non_premise_symbols=non_premise_symbols
                )
            )
        return symbols

    if isinstance(expr, IndexExpr):
        return _collect_premise_target_required_symbols(
            expr.base, non_premise_symbols=non_premise_symbols
        ) | _collect_premise_required_symbols(
            expr.index, non_premise_symbols=non_premise_symbols
        )

    if isinstance(expr, BinaryExpr) and expr.operator == "->":
        bound_symbols = _collect_lambda_bound_symbols(expr.left)
        return (
            _collect_premise_target_required_symbols(
                expr.left, non_premise_symbols=non_premise_symbols
            )
            - bound_symbols
        ) | (
            _collect_premise_required_symbols(
                expr.right,
                non_premise_symbols=non_premise_symbols | bound_symbols,
            )
            - bound_symbols
        )

    return _collect_premise_required_symbols(
        expr, non_premise_symbols=non_premise_symbols
    )


def _collect_enum_symbols(items: list[Node]) -> frozenset[str]:
    enum_symbols: set[str] = set()
    for item in items:
        enum_symbols.update(_collect_node_enum_symbols(item))
    return frozenset(enum_symbols)


def _collect_node_enum_symbols(node: Node) -> set[str]:
    enum_symbols: set[str] = set()

    if isinstance(node, ExpressionStatement):
        enum_symbols.update(_extract_enum_members(node.expression))

    for child in node.children():
        enum_symbols.update(_collect_node_enum_symbols(child))

    return enum_symbols


def _extract_enum_members(expr: Expr | None) -> set[str]:
    if not isinstance(expr, BinaryExpr):
        return set()

    definition = _extract_enum_definition(expr)
    if definition is None:
        return set()
    _, member_names = definition
    return member_names


def semantic_parser(token_stream: TokenStream) -> Program:
    return SemanticParser(token_stream).parse()


def check_semantic(root_node: Node) -> bool:
    return root_node.check_semantic()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tokenize, parse, and semantic-check a .lp logic program."
    )
    parser.add_argument("logic_program", help="Path to the input .lp file.")
    args = parser.parse_args(argv)

    try:
        token_stream = tokenizer(args.logic_program)
        root_node = semantic_parser(token_stream)
    except (TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    pprint.pp(root_node)

    issues = root_node.collect_semantic_issues()
    if issues:
        print(f"semantic check: failed ({len(issues)} issues)", file=sys.stderr)
        for issue in issues:
            print(
                f"{issue.line}:{issue.column}: {issue.message}",
                file=sys.stderr,
            )
        return 1

    print("semantic check: ok", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
