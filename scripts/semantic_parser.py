from __future__ import annotations

import argparse
import os
import pprint
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Iterator

try:
    from tokenizer import Token, TokenStream, TokenizerError, tokenize_text, tokenizer
except ImportError:  # pragma: no cover - module execution fallback
    from .tokenizer import Token, TokenStream, TokenizerError, tokenize_text, tokenizer

try:
    import semantic_format as _semantic_format
    import semantic_index_builder as _semantic_index_builder
    import semantic_symbols as _semantic_symbols
    import semantic_validation as _semantic_validation
except ImportError:  # pragma: no cover - module execution fallback
    from . import semantic_format as _semantic_format
    from . import semantic_index_builder as _semantic_index_builder
    from . import semantic_symbols as _semantic_symbols
    from . import semantic_validation as _semantic_validation


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
            _STATIC_NON_PREMISE_SYMBOLS
            | frozenset(semantic_index.class_names)
            | _collect_enum_symbols(self.children())
        )
        _validate_block(
            self.children(),
            issues,
            allow_condition_clauses=False,
            allow_imports=True,
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


@dataclass(frozen=True, slots=True)
class LoadedModule:
    path: Path
    program: Program


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
    return _semantic_validation.decompose_condition(sys.modules[__name__], condition)


def _decompose_condition_items(
    items: list[Statement],
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    return _semantic_validation.decompose_condition_items(
        sys.modules[__name__],
        items,
        states=states,
    )


def _expand_branch_group(
    branches: list[Branch],
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    return _semantic_validation.expand_branch_group(
        sys.modules[__name__],
        branches,
        states=states,
    )


def _advance_premise(
    premise: Premise,
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    return _semantic_validation.advance_premise(
        sys.modules[__name__],
        premise,
        states=states,
    )


def _advance_target(
    target: ExpressionStatement,
    *,
    states: list[list[Statement]],
) -> tuple[list[list[Statement]], list[list[Statement]]]:
    return _semantic_validation.advance_target(
        sys.modules[__name__],
        target,
        states=states,
    )


def _clone_premise(premise: Premise) -> Premise:
    return _semantic_validation.clone_premise(sys.modules[__name__], premise)


def _clone_target(target: ExpressionStatement) -> ExpressionStatement:
    return _semantic_validation.clone_target(sys.modules[__name__], target)


def _branch_to_premise(branch: Branch) -> Premise:
    return _semantic_validation.branch_to_premise(sys.modules[__name__], branch)


def _target_to_premise(target: ExpressionStatement) -> Premise:
    return _semantic_validation.target_to_premise(sys.modules[__name__], target)


def _clone_target_expr(
    expr: Expr,
    *,
    line: int,
    column: int,
    trailing_comment: str | None,
) -> ExpressionStatement:
    return _semantic_validation.clone_target_expr(
        sys.modules[__name__],
        expr,
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
    return _semantic_validation.target_expr_to_premise(
        sys.modules[__name__],
        expr,
        line=line,
        column=column,
        trailing_comment=trailing_comment,
    )


def _split_expanded_target_exprs(expr: Expr) -> list[Expr]:
    return _semantic_validation.split_expanded_target_exprs(sys.modules[__name__], expr)


def _resolve_branch_premise_expr(branch: Branch, prior_branch_exprs: list[Expr]) -> Expr:
    return _semantic_validation.resolve_branch_premise_expr(
        sys.modules[__name__],
        branch,
        prior_branch_exprs,
    )


def _build_residual_else_guard(prior_branch_exprs: list[Expr], branch: Branch) -> Expr:
    return _semantic_validation.build_residual_else_guard(
        sys.modules[__name__],
        prior_branch_exprs,
        branch,
    )


def _negate_expr(expr: Expr, *, line: int, column: int) -> Expr:
    return _semantic_validation.negate_expr(
        sys.modules[__name__],
        expr,
        line=line,
        column=column,
    )


def _clone_statement(statement: Statement) -> Statement:
    return _semantic_validation.clone_statement(sys.modules[__name__], statement)


def _lower_condition_declaration_premise(
    declaration: Declaration,
    *,
    premise_line: int,
    premise_column: int,
    trailing_comment: str | None,
) -> Statement:
    return _semantic_validation.lower_condition_declaration_premise(
        sys.modules[__name__],
        declaration,
        premise_line=premise_line,
        premise_column=premise_column,
        trailing_comment=trailing_comment,
    )


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


_IMPORT_LATEX_ALIASES: Final[dict[str, str]] = {
    "\\in": "∈",
    "\\notin": "∉",
    "\\subseteq": "⊆",
    "\\subset_eq": "⊆",
    "\\subseteqq": "⊆",
    "\\included_in": "⊆",
    "\\nsubseteq": "⊈",
    "\\notincludedin": "⊈",
    "\\not_included_in": "⊈",
    "\\subset": "⊂",
    "\\subsetneq": "⊂",
    "\\nsubset": "⊄",
    "\\notsubset": "⊄",
}

_IMPLICIT_DECLARE_OPERATORS: Final[frozenset[str]] = frozenset(
    {"=", "∈", "∉", "⊆", "⊈", "⊂", "⊄", *_IMPORT_LATEX_ALIASES.keys()}
)


def _normalize_import_path_text(module_path: str) -> str:
    return _semantic_index_builder.normalize_import_path_text(module_path)


def validate_import_path(module_path: str) -> str | None:
    return _semantic_index_builder.validate_import_path(module_path)


def _iter_root_imports(program: Program) -> Iterator[Import]:
    yield from _semantic_index_builder.iter_root_imports(sys.modules[__name__], program)


def resolve_import_path(base_dir: Path, module_path: str) -> Path:
    return _semantic_index_builder.resolve_import_path(
        sys.modules[__name__],
        base_dir,
        module_path,
    )


def render_import_path(module_file: Path, imported_file: Path) -> str:
    return _semantic_index_builder.render_import_path(module_file, imported_file)


def load_module_closure(entry_file: str | Path) -> list[LoadedModule]:
    return _semantic_index_builder.load_module_closure(sys.modules[__name__], entry_file)


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
    return _semantic_index_builder.build_semantic_index(sys.modules[__name__], root_node)


def _seed_declared_entities(
    node: Node,
    semantic_index: SemanticIndex,
    *,
    current_class: str | None,
) -> None:
    _semantic_index_builder.seed_declared_entities(
        sys.modules[__name__],
        node,
        semantic_index,
        current_class=current_class,
    )


def _scan_semantic_relations(
    node: Node,
    semantic_index: SemanticIndex,
    *,
    current_class: str | None,
    inside_declaration_body: bool = False,
) -> None:
    _semantic_index_builder.scan_semantic_relations(
        sys.modules[__name__],
        node,
        semantic_index,
        current_class=current_class,
        inside_declaration_body=inside_declaration_body,
    )


def _seed_signature_class_candidates(
    expr: Expr | None,
    semantic_index: SemanticIndex,
) -> None:
    _semantic_index_builder._seed_signature_class_candidates(
        sys.modules[__name__],
        expr,
        semantic_index,
    )


def _scoped_block_owner_class(
    expr: Expr,
    body: list[Statement],
    semantic_index: SemanticIndex,
) -> str | None:
    return _semantic_index_builder.scoped_block_owner_class(
        sys.modules[__name__],
        expr,
        body,
        semantic_index,
    )


def _body_declares_members(body: list[Statement]) -> bool:
    return _semantic_index_builder.body_declares_members(sys.modules[__name__], body)


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
    return _semantic_index_builder.build_signature_spec(
        sys.modules[__name__],
        statement,
        semantic_index=semantic_index,
        owner_class=owner_class,
    )


def _extract_alias_name(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_alias_name(sys.modules[__name__], expr)


def _is_operator_alias(alias: str) -> bool:
    return _semantic_index_builder.is_operator_alias(sys.modules[__name__], alias)


def _signature_expr_arity(expr: Expr | None) -> int:
    return _semantic_index_builder.signature_expr_arity(sys.modules[__name__], expr)


def _signature_expr_classes(
    expr: Expr | None,
    *,
    semantic_index: SemanticIndex,
) -> tuple[str | None, ...]:
    return _semantic_index_builder.signature_expr_classes(
        sys.modules[__name__],
        expr,
        semantic_index=semantic_index,
    )


def _signature_expr_items(expr: Expr | None) -> list[Expr]:
    return _semantic_index_builder.signature_expr_items(sys.modules[__name__], expr)


def _extract_enum_class_names(expr: BinaryExpr) -> set[str]:
    return _semantic_index_builder.extract_enum_class_names(sys.modules[__name__], expr)


def _resolve_relation_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    return _semantic_index_builder.resolve_relation_expression(
        sys.modules[__name__],
        expr,
        semantic_index,
    )


def _resolve_double_colon_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    return _semantic_index_builder.resolve_double_colon_expression(
        sys.modules[__name__],
        expr,
        semantic_index,
    )


def _resolve_tilde_expression(
    expr: BinaryExpr,
    semantic_index: SemanticIndex,
) -> tuple[str, str, str] | None:
    return _semantic_index_builder.resolve_tilde_expression(
        sys.modules[__name__],
        expr,
        semantic_index,
    )


def _extract_relation_name(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_relation_name(sys.modules[__name__], expr)


def _extract_member_name(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_member_name(sys.modules[__name__], expr)


def _extract_member_owner_and_name(
    expr: Expr | None,
    *,
    current_class: str | None,
) -> tuple[str | None, str | None]:
    return _semantic_index_builder.extract_member_owner_and_name(
        sys.modules[__name__],
        expr,
        current_class=current_class,
    )


def _extract_relation_symbol_alias(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_relation_symbol_alias(sys.modules[__name__], expr)


def _extract_class_call_owner(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_class_call_owner(sys.modules[__name__], expr)


def _looks_like_class_identifier(
    name: str,
    semantic_index: SemanticIndex,
) -> bool:
    return _semantic_index_builder.looks_like_class_identifier(
        sys.modules[__name__],
        name,
        semantic_index,
    )


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
    return _semantic_index_builder.extract_enum_class_relations(sys.modules[__name__], expr)


def _extract_class_name(expr: Expr | None) -> str | None:
    return _semantic_index_builder.extract_class_name(sys.modules[__name__], expr)


def _extract_enum_definition(expr: BinaryExpr) -> tuple[str, set[str]] | None:
    return _semantic_index_builder.extract_enum_definition(sys.modules[__name__], expr)


def _extract_enum_member_names(expr: Expr | None) -> set[str]:
    return _semantic_index_builder.extract_enum_member_names(sys.modules[__name__], expr)


def _reachable_class_relations(
    adjacency: dict[str, tuple[str, ...]],
    class_name: str,
    *,
    transitive: bool,
) -> tuple[str, ...]:
    return _semantic_index_builder.reachable_class_relations(
        sys.modules[__name__],
        adjacency,
        class_name,
        transitive=transitive,
    )


def _condition_from_quantified_expr(expr: QuantifiedExpr) -> Condition:
    return _semantic_index_builder.condition_from_quantified_expr(
        sys.modules[__name__],
        expr,
    )


def _split_condition_segments(body: DelimitedExpr) -> list[list[Expr]]:
    return _semantic_index_builder.split_condition_segments(sys.modules[__name__], body)


def _canonicalize_pipe_segments(
    segments: list[list[Expr]],
) -> tuple[list[list[Expr]], list[Expr] | None]:
    return _semantic_index_builder.canonicalize_pipe_segments(sys.modules[__name__], segments)


def _build_canonical_pipe_delimited_expr(
    condition_segments: list[list[Expr]],
    target_segment: list[Expr] | None,
    *,
    line: int,
    column: int,
) -> DelimitedExpr:
    return _semantic_index_builder.build_canonical_pipe_delimited_expr(
        sys.modules[__name__],
        condition_segments,
        target_segment,
        line=line,
        column=column,
    )


def _merge_segment_expr(items: list[Expr]) -> Expr:
    return _semantic_index_builder.merge_segment_expr(sys.modules[__name__], items)


def condition_to_source(condition: Condition) -> str:
    return _semantic_format.condition_to_source(sys.modules[__name__], condition)


def program_to_source(root_node: Node) -> str:
    return _semantic_format.program_to_source(sys.modules[__name__], root_node)


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
    return _semantic_format._format_condition_lines(sys.modules[__name__], condition, indent=indent)


def _format_statement_block(
    items: list[Statement],
    *,
    indent: int,
) -> list[str]:
    return _semantic_format._format_statement_block(sys.modules[__name__], items, indent=indent)


def _format_statement_lines(statement: Statement, *, indent: int) -> list[str]:
    return _semantic_format._format_statement_lines(sys.modules[__name__], statement, indent=indent)


def _format_declaration(statement: Declaration) -> str:
    return _semantic_format._format_declaration(sys.modules[__name__], statement)


def _format_expr(expr: Expr | None) -> str:
    return _semantic_format._format_expr(sys.modules[__name__], expr)


def _format_pipe_delimited_expr(expr: DelimitedExpr) -> str:
    return _semantic_format._format_pipe_delimited_expr(sys.modules[__name__], expr)


def _format_atom(expr: Expr) -> str:
    return _semantic_format._format_atom(sys.modules[__name__], expr)


def _format_binary_operand(expr: Expr) -> str:
    return _semantic_format._format_binary_operand(sys.modules[__name__], expr)


def _join_with_separators(parts: list[str], separators: list[str]) -> str:
    return _semantic_format._join_with_separators(parts, separators)


def _format_separator_text(
    separator: str,
    *,
    has_left: bool,
    has_right: bool,
) -> str:
    return _semantic_format._format_separator_text(separator, has_left=has_left, has_right=has_right)


def _format_trailing_comment(comment: str | None) -> str:
    return _semantic_format._format_trailing_comment(comment)


def _indent_text(indent: int) -> str:
    return _semantic_format._indent_text(indent)


def _normalize_semantic_tree(node: Node | None) -> Node | None:
    return _semantic_format.normalize_semantic_tree(sys.modules[__name__], node)


def _normalize_statement_block(items: list[Statement]) -> list[Statement]:
    return _semantic_format._normalize_statement_block(sys.modules[__name__], items)


def _normalize_expr_items(items: list[Expr | None]) -> list[Expr | None]:
    return _semantic_format._normalize_expr_items(sys.modules[__name__], items)


def _normalize_expr(expr: Expr) -> Expr:
    return _semantic_format._normalize_expr(sys.modules[__name__], expr)


def _normalize_delimited_expr(expr: DelimitedExpr) -> DelimitedExpr:
    return _semantic_format._normalize_delimited_expr(sys.modules[__name__], expr)


def _is_redundant_grouped_expr(expr: Expr) -> bool:
    return _semantic_format._is_redundant_grouped_expr(sys.modules[__name__], expr)


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
                         | pipe_brace_expr
    quantified_expr    ::= ("∀" | "∃") pipe_brace_expr
    call               ::= "(" [ expression { ("," | ":" | ";" | "|") expression } ] ")"
    index              ::= "[" [ expression { ("," | ":" | ";" | "|") expression } ] "]"
    brace_call         ::= pipe_brace_expr
    pipe_brace_expr    ::= "{" [ expression { ("," | "|" ) expression } ] "}"

    Canonical pipe order uses a leading `|` and places the target last:
    `{| cond1 | cond2 | target}` or `{| cond1 | cond2 |}`.
    The parser still accepts legacy target-first forms for migration.
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
            declaration = self._try_parse_declaration(line_tokens[1:], body, None)
            if declaration is not None:
                return _lower_condition_declaration_premise(
                    declaration,
                    premise_line=start.line,
                    premise_column=start.column,
                    trailing_comment=trailing_comment,
                )
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
            arrow_index = _find_top_level_symbol(line_tokens[colon_index + 1 :], "->")
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
        "||": 10,
        "&&": 11,
        "=": 20,
        ":=:": 20,
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
        "⊆": 20,
        "⊂": 20,
        "⊇": 20,
        "⊃": 20,
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
        pipe_layout_active = False
        next_item_pipe_prefixed = False
        last_item_pipe_prefixed = False

        while True:
            token = self._peek()
            if token is None:
                self._raise_error(None, f"expected closing {closer!r}")
            if token.kind == "SYMBOL" and token.value == closer:
                previous = self._peek(-1)
                if (
                    opener == "{"
                    and "|" in separators
                    and pipe_layout_active
                    and not expecting_item
                    and last_item_pipe_prefixed
                    and previous is not None
                    and token.line > previous.line
                ):
                    seen_separators.append("|")
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
                separator = self._consume().value
                seen_separators.append(separator)
                expecting_item = True
                if separator == "|":
                    pipe_layout_active = True
                    next_item_pipe_prefixed = True
                else:
                    next_item_pipe_prefixed = False
                continue

            items.append(self.parse_expression())
            expecting_item = False
            last_item_pipe_prefixed = next_item_pipe_prefixed
            next_item_pipe_prefixed = False
            previous = self._peek(-1)
            token = self._peek()
            if token is None:
                self._raise_error(None, f"expected closing {closer!r}")
            if token.kind == "SYMBOL" and token.value in separators:
                separator = self._consume().value
                seen_separators.append(separator)
                expecting_item = True
                if separator == "|":
                    pipe_layout_active = True
                    next_item_pipe_prefixed = True
                else:
                    next_item_pipe_prefixed = False
                continue
            if token.kind == "SYMBOL" and token.value == closer:
                continue
            if (
                opener == "{"
                and "|" in separators
                and pipe_layout_active
                and previous is not None
                and token.line > previous.line
            ):
                seen_separators.append("|")
                expecting_item = True
                next_item_pipe_prefixed = False
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
        if (
            token.kind == "SYMBOL"
            and token.value == "["
            and self._peek(1) is not None
            and self._peek(1).kind == "SYMBOL"
            and self._peek(1).value == "]"
        ):
            opening = self._consume()
            self._consume()
            return Token("SYMBOL", "[]", opening.line, opening.column)
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
    allow_imports: bool,
    available_symbols: frozenset[str],
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
    current_class: str | None = None,
) -> None:
    _semantic_validation.validate_block(
        sys.modules[__name__],
        items,
        _semantic_validation.ValidationContext(
            issues=issues,
            allow_condition_clauses=allow_condition_clauses,
            allow_imports=allow_imports,
            available_symbols=available_symbols,
            non_premise_symbols=non_premise_symbols,
            semantic_index=semantic_index,
            current_class=current_class,
        ),
    )


def _validate_condition_body(
    items: list[Statement],
    issues: list[SemanticIssue],
    *,
    available_symbols: frozenset[str],
    enforce_target_symbol_flow: bool,
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
    current_class: str | None = None,
) -> frozenset[str]:
    return _semantic_validation.validate_condition_body(
        sys.modules[__name__],
        items,
        issues=issues,
        available_symbols=available_symbols,
        enforce_target_symbol_flow=enforce_target_symbol_flow,
        non_premise_symbols=non_premise_symbols,
        semantic_index=semantic_index,
        current_class=current_class,
    )


def _merge_branch_symbol_sets(
    branch_sets: list[frozenset[str]],
    *,
    fallback: set[str],
) -> set[str]:
    return _semantic_validation.merge_branch_symbol_sets(branch_sets, fallback=fallback)


def _validate_branch_group(branches: list[Branch], issues: list[SemanticIssue]) -> None:
    _semantic_validation.validate_branch_group(sys.modules[__name__], branches, issues)


def _statement_contains_reserved_else(statement: Statement) -> bool:
    return _semantic_validation.statement_contains_reserved_else(sys.modules[__name__], statement)


def _append_reserved_else_issue(statement: Statement, issues: list[SemanticIssue]) -> None:
    _semantic_validation.append_reserved_else_issue(sys.modules[__name__], statement, issues)


def _expr_contains_identifier(expr: Expr | None, name: str) -> bool:
    return _semantic_validation.expr_contains_identifier(sys.modules[__name__], expr, name)


def _is_else_identifier(expr: Expr) -> bool:
    return _semantic_validation.is_else_identifier(sys.modules[__name__], expr)


def _collect_expanded_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_expanded_target_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _statement_required_symbols(
    statement: Statement,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.statement_required_symbols(
        sys.modules[__name__],
        statement,
        non_premise_symbols=non_premise_symbols,
    )


def _canonical_declared_name(
    expr: Expr | None,
    *,
    current_class: str | None,
) -> str | None:
    return _semantic_symbols.canonical_declared_name(
        sys.modules[__name__],
        expr,
        current_class=current_class,
    )


def _declared_symbols_for_expression(
    expr: Expr,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.declared_symbols_for_expression(
        sys.modules[__name__],
        expr,
        current_class=current_class,
        non_premise_symbols=non_premise_symbols,
    )


def _statement_declared_symbols(
    statement: Statement,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.statement_declared_symbols(
        sys.modules[__name__],
        statement,
        current_class=current_class,
        non_premise_symbols=non_premise_symbols,
    )


def _statement_exposed_symbols(
    statement: Statement,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.statement_exposed_symbols(
        sys.modules[__name__],
        statement,
        non_premise_symbols=non_premise_symbols,
    )


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


def _collect_module_named_symbols(
    items: list[Statement],
    *,
    semantic_index: SemanticIndex,
    non_premise_symbols: frozenset[str],
    current_class: str | None = None,
) -> list[str]:
    return _semantic_symbols.collect_module_named_symbols(
        sys.modules[__name__],
        items,
        semantic_index=semantic_index,
        non_premise_symbols=non_premise_symbols,
        current_class=current_class,
    )


def collect_semantic_issues_for_file(logic_program: str | Path) -> tuple[Program, list[SemanticIssue]]:
    modules = load_module_closure(logic_program)
    non_premise_symbols_by_path: dict[Path, frozenset[str]] = {}
    semantic_index_by_path: dict[Path, SemanticIndex] = {}
    named_symbols_by_path: dict[Path, tuple[str, ...]] = {}

    for module in modules:
        semantic_index = _build_semantic_index(module.program)
        semantic_index_by_path[module.path] = semantic_index
        non_premise_symbols = (
            _STATIC_NON_PREMISE_SYMBOLS
            | frozenset(semantic_index.class_names)
            | _collect_enum_symbols(module.program.children())
        )
        non_premise_symbols_by_path[module.path] = non_premise_symbols
        named_symbols_by_path[module.path] = tuple(
            _collect_module_named_symbols(
                module.program.items,
                semantic_index=semantic_index,
                non_premise_symbols=non_premise_symbols,
            )
        )

    full_named_symbols_by_path: dict[Path, frozenset[str]] = {}
    for module in modules:
        visible = set(named_symbols_by_path[module.path])
        for import_stmt in _iter_root_imports(module.program):
            imported_file = resolve_import_path(module.path.parent, import_stmt.module_path)
            visible.update(full_named_symbols_by_path.get(imported_file, frozenset()))
        full_named_symbols_by_path[module.path] = frozenset(visible)

    all_issues: list[SemanticIssue] = []
    for module in modules:
        semantic_index = semantic_index_by_path[module.path]
        non_premise_symbols = non_premise_symbols_by_path[module.path]
        direct_import_visible: set[str] = set()
        for import_stmt in _iter_root_imports(module.program):
            imported_file = resolve_import_path(module.path.parent, import_stmt.module_path)
            direct_import_visible.update(full_named_symbols_by_path.get(imported_file, frozenset()))

        _validate_block(
            module.program.children(),
            all_issues,
            allow_condition_clauses=False,
            allow_imports=True,
            available_symbols=frozenset(direct_import_visible),
            non_premise_symbols=non_premise_symbols,
            semantic_index=semantic_index,
            current_class=None,
        )
        _validate_program_semantics(
            module.program,
            all_issues,
            non_premise_symbols=non_premise_symbols,
            semantic_index=semantic_index,
        )

    return modules[-1].program, all_issues


def _validate_program_semantics(
    root_node: Node,
    issues: list[SemanticIssue],
    *,
    non_premise_symbols: frozenset[str],
    semantic_index: SemanticIndex,
) -> None:
    _semantic_validation.validate_program_semantics(
        sys.modules[__name__],
        root_node,
        issues,
        non_premise_symbols=non_premise_symbols,
        semantic_index=semantic_index,
    )


def _walk_statements(
    node: Node,
    *,
    in_condition: bool,
) -> Iterator[tuple[Statement, bool]]:
    yield from _semantic_validation.walk_statements(sys.modules[__name__], node, in_condition=in_condition)


def _walk_exprs(node: Node) -> Iterator[Expr]:
    yield from _semantic_validation.walk_exprs(sys.modules[__name__], node)


def _validate_function_inheritance_relations(
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
    _semantic_validation.validate_function_inheritance_relations(
        sys.modules[__name__],
        issues,
        semantic_index=semantic_index,
    )


def _validate_custom_operator_usage(
    expr: BinaryExpr,
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
    _semantic_validation.validate_custom_operator_usage(
        sys.modules[__name__],
        expr,
        issues,
        semantic_index=semantic_index,
    )


def _validate_call_expression(
    expr: CallExpr,
    issues: list[SemanticIssue],
    *,
    semantic_index: SemanticIndex,
) -> None:
    _semantic_validation.validate_call_expression(
        sys.modules[__name__],
        expr,
        issues,
        semantic_index=semantic_index,
    )


def _call_arg_count_options(expr: CallExpr) -> set[int] | None:
    return _semantic_validation.call_arg_count_options(sys.modules[__name__], expr)


def _expanded_arg_width(expr: Expr) -> int | None:
    return _semantic_validation.expanded_arg_width(sys.modules[__name__], expr)


def _candidate_call_signatures(
    callee: Expr,
    *,
    semantic_index: SemanticIndex,
) -> list[SignatureSpec]:
    return _semantic_validation.candidate_call_signatures(
        sys.modules[__name__],
        callee,
        semantic_index=semantic_index,
    )


def _format_expected_arities(signatures: list[SignatureSpec]) -> str:
    return _semantic_validation.format_expected_arities(signatures)


def _find_subclass_dispatch_violation(
    expr: CallExpr,
    *,
    signature: SignatureSpec,
    semantic_index: SemanticIndex,
) -> tuple[str, str] | None:
    return _semantic_validation.find_subclass_dispatch_violation(
        sys.modules[__name__],
        expr,
        signature=signature,
        semantic_index=semantic_index,
    )


def _parent_classes_for(
    class_name: str,
    semantic_index: SemanticIndex,
) -> tuple[str, ...]:
    return _semantic_validation.parent_classes_for(
        sys.modules[__name__],
        class_name,
        semantic_index,
    )


def _is_subclass_of(
    parent_class: str,
    child_class: str,
    *,
    semantic_index: SemanticIndex,
) -> bool:
    return _semantic_validation.is_subclass_of(
        sys.modules[__name__],
        parent_class,
        child_class,
        semantic_index=semantic_index,
    )


def _infer_expr_class(
    expr: Expr | None,
    *,
    semantic_index: SemanticIndex,
    allow_uppercase_fallback: bool,
) -> str | None:
    return _semantic_validation.infer_expr_class(
        sys.modules[__name__],
        expr,
        semantic_index=semantic_index,
        allow_uppercase_fallback=allow_uppercase_fallback,
    )


def _infer_symbol_class_name(
    name: str,
    *,
    semantic_index: SemanticIndex,
    allow_uppercase_fallback: bool,
) -> str | None:
    return _semantic_validation.infer_symbol_class_name(
        sys.modules[__name__],
        name,
        semantic_index=semantic_index,
        allow_uppercase_fallback=allow_uppercase_fallback,
    )


def _class_candidates_from_name(name: str) -> tuple[str, ...]:
    return _semantic_validation.class_candidates_from_name(name)


def _collect_expr_required_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_expr_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_expr_exposed_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_expr_exposed_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_assignment_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_assignment_target_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_assignment_target_exposed_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_assignment_target_exposed_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_assignment_target_declared_symbols(
    expr: Expr,
    *,
    current_class: str | None,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_assignment_target_declared_symbols(
        sys.modules[__name__],
        expr,
        current_class=current_class,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_pipe_delimited_required_symbols(
    expr: DelimitedExpr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_pipe_delimited_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_premise_required_symbols(
    expr: Expr | None,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_premise_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_premise_target_required_symbols(
    expr: Expr,
    *,
    non_premise_symbols: frozenset[str],
) -> set[str]:
    return _semantic_symbols.collect_premise_target_required_symbols(
        sys.modules[__name__],
        expr,
        non_premise_symbols=non_premise_symbols,
    )


def _collect_enum_symbols(items: list[Node]) -> frozenset[str]:
    return _semantic_symbols.collect_enum_symbols(sys.modules[__name__], items)


def _collect_node_enum_symbols(node: Node) -> set[str]:
    return _semantic_symbols._collect_node_enum_symbols(sys.modules[__name__], node)


def _extract_enum_members(expr: Expr | None) -> set[str]:
    return _semantic_symbols.extract_enum_members(sys.modules[__name__], expr)


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
        root_node, issues = collect_semantic_issues_for_file(args.logic_program)
    except (OSError, ValueError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    pprint.pp(root_node)
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
