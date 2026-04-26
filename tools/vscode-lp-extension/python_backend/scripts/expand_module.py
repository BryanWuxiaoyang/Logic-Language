from __future__ import annotations

import argparse
import copy
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
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
        Program,
        QuantifiedExpr,
        SequenceExpr,
        Statement,
        SymbolExpr,
        TokenizerError,
        _build_semantic_index,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _is_else_identifier,
        _resolve_branch_premise_expr,
        _scoped_block_owner_class,
        _split_expanded_target_exprs,
        parse_condition_text,
        parse_program_text,
        program_to_source,
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
        Program,
        QuantifiedExpr,
        SequenceExpr,
        Statement,
        SymbolExpr,
        TokenizerError,
        _build_semantic_index,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _is_else_identifier,
        _resolve_branch_premise_expr,
        _scoped_block_owner_class,
        _split_expanded_target_exprs,
        parse_condition_text,
        parse_program_text,
        program_to_source,
    )


GLOBAL_CONSTRAINT_GROUP = "__global_constraints__"


@dataclass(frozen=True, slots=True)
class ModuleUnit:
    path: Path
    program: Program


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


def _append_constraints(
    constraints_by_group: dict[str, list[str]],
    group: str,
    conditions: list[Condition],
) -> None:
    if not conditions:
        return
    lines = constraints_by_group.setdefault(group, [])
    for condition in conditions:
        lines.append(program_to_source(condition))


def _collect_module_symbols_and_constraints(
    module: ModuleUnit,
    *,
    symbols: set[str],
    constraints_by_group: dict[str, list[str]],
) -> None:
    semantic_index = _build_semantic_index(module.program)

    def walk_block(items: list[Statement], *, current_class: str | None) -> None:
        for item in items:
            if isinstance(item, Heading):
                walk_block(item.body, current_class=current_class)
                continue

            if isinstance(item, (Import, Comment)):
                continue

            if isinstance(item, Declaration):
                symbol_name = _declaration_symbol_name(item, current_class=current_class)
                if symbol_name:
                    symbols.add(_normalize_symbol_name(symbol_name))

                alias_name = _expr_symbol_name(item.alias)
                if alias_name:
                    symbols.add(_normalize_symbol_name(alias_name))

                group = _normalize_symbol_name(symbol_name) if symbol_name else GLOBAL_CONSTRAINT_GROUP
                declaration_conditions = _expand_declaration_conditions(
                    item,
                    current_class=current_class,
                    initial_state=[],
                )
                _append_constraints(
                    constraints_by_group,
                    group,
                    declaration_conditions,
                )
                continue

            if isinstance(item, Condition):
                initial_state: list[Statement] = []
                if current_class is not None:
                    initial_state.append(
                        Premise(
                            expression=IdentifierExpr(
                                name=current_class,
                                line=item.line,
                                column=item.column,
                            ),
                            body=[],
                            line=item.line,
                            column=item.column,
                        )
                    )
                conditions, _ = _expand_condition_items(
                    item.body,
                    states=[initial_state],
                    quantifier=item.quantifier,
                )
                group = current_class or GLOBAL_CONSTRAINT_GROUP
                _append_constraints(constraints_by_group, group, conditions)
                continue

            if isinstance(item, ExpressionStatement):
                declared_symbol = _declared_symbol_from_expression(
                    item.expression,
                    current_class=current_class,
                )
                if declared_symbol is not None:
                    symbols.add(_normalize_symbol_name(declared_symbol))

                scoped_owner = _scoped_block_owner_class(
                    item.expression,
                    item.body,
                    semantic_index,
                )
                if scoped_owner is not None:
                    if declared_symbol is None:
                        initial_state: list[Statement] = []
                        if current_class is not None:
                            initial_state.append(
                                Premise(
                                    expression=IdentifierExpr(
                                        name=current_class,
                                        line=item.line,
                                        column=item.column,
                                    ),
                                    body=[],
                                    line=item.line,
                                    column=item.column,
                                )
                            )
                        conditions, _ = _expand_condition_items(
                            [copy.deepcopy(item)],
                            states=[initial_state],
                            quantifier="∀",
                        )
                        group = current_class or GLOBAL_CONSTRAINT_GROUP
                        _append_constraints(constraints_by_group, group, conditions)
                    walk_block(item.body, current_class=scoped_owner)
                    continue

                if declared_symbol is not None and not item.body:
                    continue

                if isinstance(item.expression, QuantifiedExpr):
                    quantified_condition = _condition_from_quantified_expression(item.expression)
                    initial_state = []
                    if current_class is not None:
                        initial_state.append(
                            Premise(
                                expression=IdentifierExpr(
                                    name=current_class,
                                    line=item.line,
                                    column=item.column,
                                ),
                                body=[],
                                line=item.line,
                                column=item.column,
                            )
                        )
                    conditions, _ = _expand_condition_items(
                        quantified_condition.body,
                        states=[initial_state],
                        quantifier=quantified_condition.quantifier,
                    )
                    group = current_class or GLOBAL_CONSTRAINT_GROUP
                    _append_constraints(constraints_by_group, group, conditions)
                    continue

                initial_state = []
                if current_class is not None:
                    initial_state.append(
                        Premise(
                            expression=IdentifierExpr(
                                name=current_class,
                                line=item.line,
                                column=item.column,
                            ),
                            body=[],
                            line=item.line,
                            column=item.column,
                        )
                    )
                conditions, _ = _expand_condition_items(
                    [copy.deepcopy(item)],
                    states=[initial_state],
                    quantifier="∀",
                )
                group = current_class or GLOBAL_CONSTRAINT_GROUP
                _append_constraints(constraints_by_group, group, conditions)
                continue

    walk_block(module.program.items, current_class=None)


def _module_import_paths(items: list[Statement]) -> list[str]:
    imports: list[str] = []
    for item in items:
        if isinstance(item, Import):
            imports.append(item.module_path)
        for child in item.body:
            imports.extend(_module_import_paths([child]))
    return imports


def _import_path_candidates(base_dir: Path, module_path: str) -> list[Path]:
    raw = module_path.strip()
    if not raw:
        return []

    raw_norm = raw.replace("\\", "/")
    bases: list[Path] = []
    seen_bases: set[str] = set()

    def add_base(path_text: str) -> None:
        key = path_text.strip()
        if not key or key in seen_bases:
            return
        seen_bases.add(key)
        bases.append(Path(key))

    if raw_norm.startswith("./") or raw_norm.startswith("../") or "/" in raw_norm:
        add_base(raw_norm)
    elif raw_norm.startswith("."):
        trimmed = raw_norm.lstrip(".")
        if trimmed:
            add_base(trimmed)
            if "." in trimmed:
                add_base(trimmed.replace(".", "/"))
    else:
        add_base(raw_norm)
        if "." in raw_norm and not raw_norm.endswith(".lp"):
            add_base(raw_norm.replace(".", "/"))

    candidates: list[Path] = []
    seen_candidates: set[str] = set()
    for base in bases:
        full_base = base if base.is_absolute() else (base_dir / base)
        variants = [full_base]
        if full_base.suffix != ".lp":
            variants.insert(0, full_base.with_suffix(".lp"))
        for variant in variants:
            normalized = str(variant)
            if normalized in seen_candidates:
                continue
            seen_candidates.add(normalized)
            candidates.append(variant)
    return candidates


def _resolve_import_path(base_dir: Path, module_path: str) -> Path:
    candidates = _import_path_candidates(base_dir, module_path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    candidate_text = ", ".join(str(path) for path in candidates) or "(no candidate paths)"
    raise FileNotFoundError(
        f"unable to resolve import {module_path!r} from {base_dir}; tried: {candidate_text}"
    )


def _load_modules_recursive(entry_file: Path) -> list[ModuleUnit]:
    ordered_modules: list[ModuleUnit] = []
    visited: set[Path] = set()
    visiting: set[Path] = set()

    def visit(module_file: Path) -> None:
        resolved_file = module_file.resolve()
        if resolved_file in visited:
            return
        if resolved_file in visiting:
            return

        source = resolved_file.read_text(encoding="utf-8")
        program = parse_program_text(source, source_name=str(resolved_file))

        visiting.add(resolved_file)
        for import_path in _module_import_paths(program.items):
            import_file = _resolve_import_path(resolved_file.parent, import_path)
            visit(import_file)
        visiting.remove(resolved_file)

        visited.add(resolved_file)
        ordered_modules.append(ModuleUnit(path=resolved_file, program=program))

    visit(entry_file)
    return ordered_modules


def _indent_block(text: str, *, prefix: str) -> list[str]:
    if not text:
        return [prefix.rstrip()]
    return [prefix + line if line else prefix.rstrip() for line in text.splitlines()]


def _render_output(
    *,
    symbols: set[str],
    constraints_by_group: dict[str, list[str]],
) -> str:
    lines: list[str] = []
    lines.append("@symbols")
    for symbol in sorted(_normalize_symbol_name(item) for item in symbols):
        lines.append(f"    {symbol}")

    lines.append("")
    lines.append("@constraints")

    group_names = sorted(
        name for name in constraints_by_group.keys() if name != GLOBAL_CONSTRAINT_GROUP
    )
    if GLOBAL_CONSTRAINT_GROUP in constraints_by_group:
        group_names.append(GLOBAL_CONSTRAINT_GROUP)

    for index, group in enumerate(group_names):
        title = "global_constraints" if group == GLOBAL_CONSTRAINT_GROUP else group
        lines.append(f"    @{title}")
        for condition_text in constraints_by_group[group]:
            lines.extend(_indent_block(condition_text, prefix="        "))
            lines.append("")
        if lines[-1] == "":
            lines.pop()
        if index != len(group_names) - 1:
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def expand_module_file(
    input_file: str | Path,
    *,
    output_file: str | Path | None = None,
) -> Path:
    input_path = Path(input_file).resolve()
    if output_file is None:
        output_path = input_path.with_suffix(".expanded.lp")
    else:
        output_path = Path(output_file).resolve()

    modules = _load_modules_recursive(input_path)

    symbols: set[str] = set()
    constraints_by_group: dict[str, list[str]] = defaultdict(list)
    for module in modules:
        _collect_module_symbols_and_constraints(
            module,
            symbols=symbols,
            constraints_by_group=constraints_by_group,
        )

    output_text = _render_output(
        symbols=symbols,
        constraints_by_group=constraints_by_group,
    )
    output_path.write_text(output_text, encoding="utf-8")
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
