from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(slots=True)
class TraversalState:
    current_class: str | None
    inside_declaration_body: bool = False


def normalize_import_path_text(module_path: str) -> str:
    return module_path.strip().replace("\\", "/")


def validate_import_path(module_path: str) -> str | None:
    normalized = normalize_import_path_text(module_path)
    if not normalized:
        return "import path must not be empty"
    if normalized.startswith("{") or normalized.endswith("}"):
        return "import path must not use braces; use '$import module_path'"
    if normalized.endswith(".lp"):
        return "import path must not include the .lp suffix"
    if normalized.startswith(".") and not (
        normalized.startswith("./") or normalized.startswith("../")
    ):
        return "import path must use terminal-style absolute or relative paths"
    return None


def iter_root_imports(lp, program):
    for item in program.items:
        if isinstance(item, lp.Import):
            yield item


def resolve_import_path(lp, base_dir: Path, module_path: str) -> Path:
    validation_error = validate_import_path(module_path)
    if validation_error is not None:
        raise ValueError(validation_error)

    raw_path = Path(normalize_import_path_text(module_path))
    candidate = raw_path if raw_path.is_absolute() else (base_dir / raw_path)
    candidate = candidate.with_suffix(".lp")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(
            f"unable to resolve import {module_path!r} from {base_dir}"
        )
    return candidate.resolve()


def render_import_path(module_file: Path, imported_file: Path) -> str:
    imported_stem = imported_file.with_suffix("")
    if imported_stem.is_absolute():
        if module_file.is_absolute():
            relative_text = os.path.relpath(imported_stem, start=module_file.parent)
            return Path(relative_text).as_posix()
        return imported_stem.as_posix()
    return imported_stem.as_posix()


def load_module_closure(lp, entry_file: str | Path):
    entry_path = Path(entry_file).resolve()
    ordered_modules = []
    visited: set[Path] = set()
    visiting: list[Path] = []

    def visit(module_file: Path) -> None:
        resolved_file = module_file.resolve()
        if resolved_file in visited:
            return
        if resolved_file in visiting:
            cycle_start = visiting.index(resolved_file)
            cycle = visiting[cycle_start:] + [resolved_file]
            cycle_text = " -> ".join(path.as_posix() for path in cycle)
            raise ValueError(f"import cycle detected: {cycle_text}")

        source = resolved_file.read_text(encoding="utf-8")
        program = lp.parse_program_text(source, source_name=str(resolved_file))
        visiting.append(resolved_file)
        for import_stmt in iter_root_imports(lp, program):
            imported_file = resolve_import_path(lp, resolved_file.parent, import_stmt.module_path)
            visit(imported_file)
        visiting.pop()
        visited.add(resolved_file)
        ordered_modules.append(lp.LoadedModule(path=resolved_file, program=program))

    visit(entry_path)
    return ordered_modules


def build_semantic_index(lp, root_node):
    semantic_index = lp.SemanticIndex()
    seed_declared_entities(lp, root_node, semantic_index, current_class=None)
    scan_semantic_relations(
        lp,
        root_node,
        semantic_index,
        current_class=None,
        inside_declaration_body=False,
    )
    return semantic_index


def seed_declared_entities(lp, node, semantic_index, *, current_class: str | None) -> None:
    items = _node_items(lp, node)
    if items is None:
        return

    for item in items:
        state = TraversalState(current_class=current_class)

        if isinstance(item, lp.Declaration):
            owner_class = lp._declaration_owner_class(item, current_class=current_class)
            if owner_class is not None:
                semantic_index.class_names.add(owner_class)
                member_name = lp._extract_member_name(item.head)
                if member_name is not None:
                    lp._register_member_name(semantic_index, owner_class, member_name)
                elif item.head is None:
                    lp._register_member_name(semantic_index, owner_class, "call")
            elif isinstance(item.head, lp.IdentifierExpr):
                semantic_index.function_names.add(item.head.name)
                alias_name = lp._extract_alias_name(item.alias)
                if alias_name is not None:
                    semantic_index.function_names.add(alias_name)
            elif isinstance(item.head, lp.SymbolExpr):
                semantic_index.function_names.add(item.head.value)
                alias_name = lp._extract_alias_name(item.alias)
                if alias_name is not None:
                    semantic_index.function_names.add(alias_name)

            _seed_signature_class_candidates(lp, item.input_expr, semantic_index)
            _seed_signature_class_candidates(lp, item.output_expr, semantic_index)

        if isinstance(item, lp.ExpressionStatement):
            state = _seed_expression_statement(lp, item, semantic_index, state)

        if isinstance(item, lp.Statement) and item.body:
            seed_declared_entities(
                lp,
                item,
                semantic_index,
                current_class=state.current_class,
            )


def scan_semantic_relations(
    lp,
    node,
    semantic_index,
    *,
    current_class: str | None,
    inside_declaration_body: bool = False,
) -> None:
    items = _node_items(lp, node)
    if items is None:
        return

    for item in items:
        state = TraversalState(
            current_class=current_class,
            inside_declaration_body=inside_declaration_body,
        )

        if isinstance(item, lp.Declaration):
            owner_class = lp._declaration_owner_class(item, current_class=current_class)
            signature = lp._build_signature_spec(
                item,
                semantic_index=semantic_index,
                owner_class=owner_class,
            )
            if signature is not None:
                if owner_class is None:
                    semantic_index.function_signatures_by_name.setdefault(signature.name, []).append(signature)
                else:
                    semantic_index.member_signatures_by_key.setdefault((owner_class, signature.name), []).append(signature)
                if lp._is_operator_alias(signature.name):
                    semantic_index.operator_aliases.setdefault(signature.name, []).append(signature)
                if signature.alias is not None and lp._is_operator_alias(signature.alias):
                    semantic_index.operator_aliases.setdefault(signature.alias, []).append(signature)

        if isinstance(item, lp.ExpressionStatement):
            state = _scan_expression_statement(lp, item, semantic_index, state)

        if isinstance(item, lp.Statement) and item.body:
            scan_semantic_relations(
                lp,
                item,
                semantic_index,
                current_class=state.current_class,
                inside_declaration_body=state.inside_declaration_body or isinstance(item, lp.Declaration),
            )


def _seed_signature_class_candidates(lp, expr, semantic_index) -> None:
    for item in lp._signature_expr_items(expr):
        if not isinstance(item, lp.IdentifierExpr):
            continue
        class_name = lp._infer_symbol_class_name(
            item.name,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        if class_name is not None:
            semantic_index.class_names.add(class_name)


def _seed_expression_statement(lp, item, semantic_index, state: TraversalState) -> TraversalState:
    if isinstance(item.expression, lp.IdentifierExpr):
        semantic_index.class_names.add(item.expression.name)
    if isinstance(item.expression, lp.BinaryExpr):
        semantic_index.class_names.update(lp._extract_enum_class_names(item.expression))
        semantic_index.symbol_inheritance_relations.update(
            lp._extract_enum_class_relations(item.expression)
        )
        if item.expression.operator == "~":
            left_name = lp._extract_relation_name(item.expression.left)
            if left_name is not None and left_name not in semantic_index.function_names:
                semantic_index.class_names.add(left_name)

    if state.current_class is not None and isinstance(item.expression, lp.AttributeExpr):
        if item.expression.base is None:
            lp._register_member_name(
                semantic_index,
                state.current_class,
                item.expression.attribute,
            )

    scoped_owner = lp._scoped_block_owner_class(item.expression, item.body, semantic_index)
    if scoped_owner is not None:
        state.current_class = scoped_owner
        semantic_index.class_names.add(scoped_owner)
        if isinstance(item.expression, lp.BinaryExpr) and item.expression.operator in {"::", "~"}:
            left_name = lp._extract_relation_name(item.expression.left)
            right_name = lp._extract_relation_name(item.expression.right)
            if left_name is not None:
                semantic_index.class_names.add(left_name)
            if right_name is not None:
                semantic_index.class_names.add(right_name)
            alias_symbol = lp._extract_relation_symbol_alias(item.expression.right)
            if right_name is not None and alias_symbol is not None:
                semantic_index.symbol_inheritance_relations.add((right_name, alias_symbol))
    return state


def _scan_expression_statement(lp, item, semantic_index, state: TraversalState) -> TraversalState:
    if isinstance(item.expression, lp.BinaryExpr):
        resolved = lp._resolve_relation_expression(item.expression, semantic_index)
        if resolved is not None:
            relation_kind, left_name, right_name = resolved
            if (
                state.inside_declaration_body
                and item.expression.operator == "~"
                and not item.body
                and relation_kind == "class_inheritance"
            ):
                relation_kind = "symbol_inheritance"
            if relation_kind == "class_inheritance":
                semantic_index.class_inheritance_relations.add((left_name, right_name))
            elif relation_kind == "function_inheritance":
                semantic_index.function_inheritance_relations.add((left_name, right_name))
            elif relation_kind == "symbol_inheritance":
                semantic_index.symbol_inheritance_relations.add((left_name, right_name))
            elif relation_kind == "function_to_class":
                semantic_index.function_class_relations.add((left_name, right_name))

        semantic_index.symbol_inheritance_relations.update(
            lp._extract_enum_class_relations(item.expression)
        )

    scoped_owner = lp._scoped_block_owner_class(item.expression, item.body, semantic_index)
    if scoped_owner is not None:
        state.current_class = scoped_owner
    return state


def _node_items(lp, node):
    if isinstance(node, lp.Program):
        return node.items
    if isinstance(node, lp.Statement):
        return node.body
    return None


def scoped_block_owner_class(lp, expr, body, semantic_index):
    if not body:
        return None

    if isinstance(expr, lp.IdentifierExpr):
        return expr.name

    if isinstance(expr, lp.BinaryExpr) and expr.operator in {"::", "~"}:
        left_name = extract_relation_name(lp, expr.left)
        right_name = extract_relation_name(lp, expr.right)
        if left_name is None or right_name is None:
            return None
        if body_declares_members(lp, body):
            return right_name
        resolved = resolve_relation_expression(lp, expr, semantic_index)
        if resolved is not None and resolved[0] == "class_inheritance":
            return right_name

    return None


def body_declares_members(lp, body) -> bool:
    for item in body:
        if isinstance(item, lp.Declaration):
            owner_class = lp._declaration_owner_class(item, current_class=None)
            if owner_class is not None:
                return True
        if isinstance(item, lp.ExpressionStatement):
            if isinstance(item.expression, lp.AttributeExpr) and item.expression.base is None:
                return True
    return False


def build_signature_spec(lp, statement, *, semantic_index, owner_class):
    if statement.head is None:
        if owner_class is None:
            return None
        name = "call"
    elif owner_class is not None:
        _, member_name = extract_member_owner_and_name(
            lp,
            statement.head,
            current_class=owner_class,
        )
        if member_name is None:
            return None
        name = member_name
    elif isinstance(statement.head, lp.IdentifierExpr):
        name = statement.head.name
    elif isinstance(statement.head, lp.SymbolExpr):
        name = statement.head.value
    else:
        return None

    alias = extract_alias_name(lp, statement.alias)
    return lp.SignatureSpec(
        name=name,
        input_shape=lp._format_expr(statement.input_expr),
        output_shape=lp._format_expr(statement.output_expr),
        arity=signature_expr_arity(lp, statement.input_expr),
        arg_classes=signature_expr_classes(
            lp,
            statement.input_expr,
            semantic_index=semantic_index,
        ),
        owner_class=owner_class,
        alias=alias,
        line=statement.line,
        column=statement.column,
    )


def extract_alias_name(lp, expr):
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    if isinstance(expr, lp.SymbolExpr):
        return expr.value
    return None


def is_operator_alias(lp, alias: str) -> bool:
    return (
        alias in lp._LineExpressionParser._INFIX_PRECEDENCE
        or lp._is_custom_operator_alias(alias)
        or lp._is_latex_name(alias)
    )


def signature_expr_arity(lp, expr) -> int:
    return len(signature_expr_items(lp, expr))


def signature_expr_classes(lp, expr, *, semantic_index):
    return tuple(
        lp._infer_expr_class(
            item,
            semantic_index=semantic_index,
            allow_uppercase_fallback=True,
        )
        for item in signature_expr_items(lp, expr)
    )


def signature_expr_items(lp, expr):
    if expr is None:
        return []
    if isinstance(expr, (lp.DelimitedExpr, lp.SequenceExpr)):
        return [item for item in expr.items if item is not None]
    return [expr]


def extract_enum_class_names(lp, expr):
    definition = extract_enum_definition(lp, expr)
    if definition is None:
        return set()
    enum_class_name, _ = definition
    return {enum_class_name}


def resolve_relation_expression(lp, expr, semantic_index):
    if expr.operator == "::":
        return resolve_double_colon_expression(lp, expr, semantic_index)
    if expr.operator == "~":
        return resolve_tilde_expression(lp, expr, semantic_index)
    return None


def resolve_double_colon_expression(lp, expr, semantic_index):
    if expr.operator != "::":
        return None

    left_name = extract_relation_name(lp, expr.left)
    right_name = extract_relation_name(lp, expr.right)
    if left_name is None or right_name is None:
        return None

    if right_name in semantic_index.member_names_by_class.get(left_name, set()):
        return "member_extraction", left_name, right_name

    if left_name in semantic_index.function_names and right_name in semantic_index.function_names:
        return "function_inheritance", left_name, right_name

    if looks_like_class_identifier(lp, left_name, semantic_index) and looks_like_class_identifier(lp, right_name, semantic_index):
        return "class_inheritance", left_name, right_name

    if looks_like_class_identifier(lp, left_name, semantic_index):
        return "symbol_inheritance", left_name, right_name

    return None


def resolve_tilde_expression(lp, expr, semantic_index):
    if expr.operator != "~":
        return None

    left_name = extract_relation_name(lp, expr.left)
    if left_name is None:
        return None

    class_call_owner = extract_class_call_owner(lp, expr.right)
    if left_name in semantic_index.function_names and class_call_owner is not None:
        return "function_to_class", left_name, class_call_owner

    right_name = extract_relation_name(lp, expr.right)
    if right_name is None:
        return None

    if left_name in semantic_index.function_names and right_name in semantic_index.function_names:
        return "function_inheritance", left_name, right_name

    if looks_like_class_identifier(lp, left_name, semantic_index):
        if (
            isinstance(expr.right, lp.CallExpr)
            or right_name in semantic_index.class_names
            or left_name in semantic_index.class_names
        ):
            return "class_inheritance", left_name, right_name
        return "symbol_inheritance", left_name, right_name

    return None


def extract_relation_name(lp, expr):
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    if isinstance(expr, lp.SymbolExpr):
        return expr.value
    if isinstance(expr, lp.CallExpr) and isinstance(expr.callee, lp.IdentifierExpr):
        return expr.callee.name
    if isinstance(expr, lp.CallExpr) and isinstance(expr.callee, lp.SymbolExpr):
        return expr.callee.value
    return None


def extract_member_name(lp, expr):
    if isinstance(expr, lp.AttributeExpr):
        return expr.attribute
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    if isinstance(expr, lp.SymbolExpr):
        return expr.value
    if isinstance(expr, lp.CallExpr) and isinstance(expr.callee, lp.IdentifierExpr):
        return expr.callee.name
    if isinstance(expr, lp.CallExpr) and isinstance(expr.callee, lp.SymbolExpr):
        return expr.callee.value
    if isinstance(expr, lp.BinaryExpr) and expr.operator == "::":
        return extract_member_name(lp, expr.right)
    return None


def extract_member_owner_and_name(lp, expr, *, current_class):
    if isinstance(expr, lp.AttributeExpr):
        if expr.base is None:
            return current_class, expr.attribute
        if isinstance(expr.base, lp.IdentifierExpr):
            return expr.base.name, expr.attribute
        return None, None

    if isinstance(expr, lp.BinaryExpr) and expr.operator == "::":
        owner_class = extract_relation_name(lp, expr.left)
        member_name = extract_member_name(lp, expr.right)
        return owner_class, member_name

    return None, None


def extract_relation_symbol_alias(lp, expr):
    if not isinstance(expr, lp.CallExpr) or not isinstance(expr.callee, lp.IdentifierExpr):
        return None
    args = [arg for arg in expr.args if arg is not None]
    if len(args) != 1 or not isinstance(args[0], lp.IdentifierExpr):
        return None
    return args[0].name


def extract_class_call_owner(lp, expr):
    if not isinstance(expr, lp.BinaryExpr) or expr.operator != "::":
        return None
    if not isinstance(expr.left, lp.IdentifierExpr):
        return None
    right_name = extract_relation_name(lp, expr.right)
    if right_name != "call":
        return None
    return expr.left.name


def looks_like_class_identifier(lp, name: str, semantic_index) -> bool:
    if name in semantic_index.class_names:
        return True
    if any(char.isdigit() for char in name) or "_" in name:
        return False
    return bool(name[:1].isupper())


def extract_enum_class_relations(lp, expr):
    definition = extract_enum_definition(lp, expr)
    if definition is None:
        return ()
    enum_class_name, member_names = definition
    return tuple(sorted((enum_class_name, member_name) for member_name in member_names))


def extract_class_name(lp, expr):
    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    return None


def extract_enum_definition(lp, expr):
    if expr.operator != "∈":
        return None

    member_names = extract_enum_member_names(lp, expr.left)
    enum_class_name = extract_class_name(lp, expr.right)
    if member_names and enum_class_name is not None:
        return enum_class_name, member_names

    enum_class_name = extract_class_name(lp, expr.left)
    member_names = extract_enum_member_names(lp, expr.right)
    if member_names and enum_class_name is not None:
        return enum_class_name, member_names

    return None


def extract_enum_member_names(lp, expr):
    if not isinstance(expr, lp.DelimitedExpr):
        return set()
    if expr.opener != "{" or expr.closer != "}":
        return set()

    members: set[str] = set()
    for item in expr.items:
        if item is None or not isinstance(item, lp.IdentifierExpr):
            return set()
        members.add(item.name)
    return members


def reachable_class_relations(lp, adjacency, class_name: str, *, transitive: bool):
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


def condition_from_quantified_expr(lp, expr):
    segments = split_condition_segments(lp, expr.body)
    premise_segments, target_segment = canonicalize_pipe_segments(lp, segments)
    if target_segment is None or not target_segment:
        raise lp.ParserError("quantified condition must contain at least one target")
    if any(not segment for segment in premise_segments):
        raise lp.ParserError("quantified condition contains an empty clause")

    body = []
    for segment in premise_segments:
        premise_expr = merge_segment_expr(lp, segment)
        body.append(
            lp.Premise(
                expression=premise_expr,
                body=[],
                line=premise_expr.line,
                column=premise_expr.column,
            )
        )

    for target_expr in target_segment:
        body.append(
            lp.ExpressionStatement(
                expression=target_expr,
                body=[],
                line=target_expr.line,
                column=target_expr.column,
            )
        )

    return lp.Condition(
        quantifier=expr.quantifier,
        body=body,
        line=expr.line,
        column=expr.column,
    )


def split_condition_segments(lp, body):
    if not body.items and not body.separators:
        return [[]]

    segments = [[]]
    for index, item in enumerate(body.items):
        if item is not None:
            segments[-1].append(item)
        if index >= len(body.separators):
            continue
        separator = body.separators[index]
        if separator == "|":
            segments.append([])
            continue
        if separator != ",":
            raise lp.ParserError(
                f"unsupported quantified-condition separator {separator!r}"
            )

    for separator in body.separators[len(body.items):]:
        if separator == "|":
            segments.append([])
            continue
        if separator != ",":
            raise lp.ParserError(
                f"unsupported quantified-condition separator {separator!r}"
            )

    return segments


def canonicalize_pipe_segments(lp, segments):
    if not segments:
        return [], None

    if not segments[0]:
        if len(segments) == 1:
            return [], None
        if not segments[-1]:
            return list(segments[1:-1]), None
        return list(segments[1:-1]), list(segments[-1])

    return list(reversed(segments[1:])), list(segments[0])


def build_canonical_pipe_delimited_expr(lp, condition_segments, target_segment, *, line: int, column: int):
    items = [None]
    items.extend(merge_segment_expr(lp, segment) for segment in condition_segments)
    if target_segment is not None and target_segment:
        items.append(merge_segment_expr(lp, target_segment))
        separators = ["|"] * (len(items) - 1)
    else:
        separators = ["|"] * len(items)
    return lp.DelimitedExpr(
        opener="{",
        items=items,
        separators=separators,
        closer="}",
        line=line,
        column=column,
    )


def merge_segment_expr(lp, items):
    if len(items) == 1:
        return items[0]
    line = items[0].line
    column = items[0].column
    return lp.SequenceExpr(
        items=list(items),
        separators=[","] * (len(items) - 1),
        line=line,
        column=column,
    )
