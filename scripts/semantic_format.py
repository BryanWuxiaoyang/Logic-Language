from __future__ import annotations


def condition_to_source(lp, condition) -> str:
    return "\n".join(_format_condition_lines(lp, condition, indent=0))


def program_to_source(lp, root_node) -> str:
    if isinstance(root_node, lp.Program):
        return "\n".join(_format_statement_block(lp, root_node.items, indent=0))
    if isinstance(root_node, lp.Condition):
        return "\n".join(_format_condition_lines(lp, root_node, indent=0))
    if isinstance(root_node, lp.Statement):
        return "\n".join(_format_statement_lines(lp, root_node, indent=0))
    if isinstance(root_node, lp.Expr):
        return _format_expr(lp, root_node)
    return repr(root_node)


def _format_condition_lines(lp, condition, *, indent: int) -> list[str]:
    lines = [_indent_text(indent) + condition.quantifier]
    lines.extend(_format_statement_block(lp, condition.body, indent=indent + 4))
    return lines


def _format_statement_block(lp, items, *, indent: int) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(_format_statement_lines(lp, item, indent=indent))
    return lines


def _format_statement_lines(lp, statement, *, indent: int) -> list[str]:
    prefix = _indent_text(indent)
    trailing = _format_trailing_comment(statement.trailing_comment)

    if isinstance(statement, lp.Condition):
        lines = [prefix + statement.quantifier + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Premise):
        lines = [prefix + "| " + _format_expr(lp, statement.expression) + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Branch):
        lines = [prefix + "|- " + _format_expr(lp, statement.expression) + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.ExpressionStatement):
        lines = [prefix + _format_expr(lp, statement.expression) + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Declaration):
        lines = [prefix + _format_declaration(lp, statement) + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Heading):
        lines = [prefix + "@" + statement.title + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Import):
        lines = [prefix + "$import " + statement.module_path + trailing]
        lines.extend(_format_statement_block(lp, statement.body, indent=indent + 4))
        return lines

    if isinstance(statement, lp.Comment):
        return [prefix + "#" + (" " + statement.text if statement.text else "")]

    return [prefix + repr(statement)]


def _format_declaration(lp, statement) -> str:
    head = "" if statement.head is None else _format_expr(lp, statement.head)

    input_expr = _format_expr(lp, statement.input_expr) if statement.input_expr else ""
    output_expr = _format_expr(lp, statement.output_expr) if statement.output_expr else ""
    return f"{head}: {input_expr} => {output_expr}".strip()


def _format_expr(lp, expr) -> str:
    if expr is None:
        return ""

    if isinstance(expr, lp.IdentifierExpr):
        return expr.name
    if isinstance(expr, lp.NumberExpr):
        return expr.value
    if isinstance(expr, lp.StringExpr):
        escaped = (
            expr.value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(expr, lp.SymbolExpr):
        return expr.value
    if isinstance(expr, lp.UnaryExpr):
        return f"{expr.operator}{_format_atom(lp, expr.operand)}"
    if isinstance(expr, lp.BinaryExpr):
        return (
            f"{_format_binary_operand(lp, expr.left)} {expr.operator} "
            f"{_format_binary_operand(lp, expr.right)}"
        )
    if isinstance(expr, lp.SequenceExpr):
        parts = [_format_expr(lp, item) for item in expr.items]
        return _join_with_separators(parts, expr.separators)
    if isinstance(expr, lp.DelimitedExpr):
        if expr.opener == "{" and expr.closer == "}" and "|" in expr.separators:
            return _format_pipe_delimited_expr(lp, expr)
        parts = [_format_expr(lp, item) for item in expr.items]
        inner = _join_with_separators(parts, expr.separators)
        return f"{expr.opener}{inner}{expr.closer}"
    if isinstance(expr, lp.AttributeExpr):
        if expr.base is None:
            return f"::{expr.attribute}"
        return f"{_format_atom(lp, expr.base)}.{expr.attribute}"
    if isinstance(expr, lp.CallExpr):
        if expr.delimiter == "{}":
            if len(expr.args) == 1 and isinstance(expr.args[0], lp.DelimitedExpr):
                return f"{_format_atom(lp, expr.callee)}{_format_expr(lp, expr.args[0])}"
            args = _join_with_separators(
                [_format_expr(lp, arg) for arg in expr.args],
                expr.separators,
            )
            return f"{_format_atom(lp, expr.callee)}{{{args}}}"

        args = _join_with_separators(
            [_format_expr(lp, arg) for arg in expr.args],
            expr.separators,
        )
        return f"{_format_atom(lp, expr.callee)}({args})"
    if isinstance(expr, lp.IndexExpr):
        return f"{_format_atom(lp, expr.base)}{_format_expr(lp, expr.index)}"
    if isinstance(expr, lp.QuantifiedExpr):
        return f"{expr.quantifier}{_format_expr(lp, expr.body)}"
    return repr(expr)


def _format_pipe_delimited_expr(lp, expr) -> str:
    segments = lp._split_condition_segments(expr)
    condition_segments, target_segment = lp._canonicalize_pipe_segments(segments)

    parts = [""]
    parts.extend(
        _format_expr(lp, lp._merge_segment_expr(segment))
        for segment in condition_segments
        if segment
    )

    if target_segment is not None and target_segment:
        parts.append(_format_expr(lp, lp._merge_segment_expr(target_segment)))
        separators = ["|"] * (len(parts) - 1)
    else:
        separators = ["|"] * len(parts)

    inner = _join_with_separators(parts, separators)
    return f"{expr.opener}{inner}{expr.closer}"


def _format_atom(lp, expr) -> str:
    if isinstance(
        expr,
        (
            lp.IdentifierExpr,
            lp.NumberExpr,
            lp.StringExpr,
            lp.SymbolExpr,
            lp.AttributeExpr,
            lp.CallExpr,
            lp.IndexExpr,
            lp.QuantifiedExpr,
            lp.DelimitedExpr,
        ),
    ):
        return _format_expr(lp, expr)
    return f"({_format_expr(lp, expr)})"


def _format_binary_operand(lp, expr) -> str:
    if isinstance(expr, lp.BinaryExpr) and expr.operator == "->":
        return _format_expr(lp, expr)
    if isinstance(expr, lp.UnaryExpr):
        return _format_expr(lp, expr)
    return _format_atom(lp, expr)


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


def normalize_semantic_tree(lp, node):
    if node is None:
        return None

    if isinstance(node, lp.Program):
        return lp.Program(
            items=_normalize_statement_block(lp, node.items),
            line=0,
            column=0,
        )
    if isinstance(node, lp.Comment):
        return None
    if isinstance(node, lp.IdentifierExpr):
        return lp.IdentifierExpr(name=node.name, line=0, column=0)
    if isinstance(node, lp.NumberExpr):
        return lp.NumberExpr(value=node.value, line=0, column=0)
    if isinstance(node, lp.StringExpr):
        return lp.StringExpr(value=node.value, line=0, column=0)
    if isinstance(node, lp.SymbolExpr):
        return lp.SymbolExpr(value=node.value, line=0, column=0)
    if isinstance(node, lp.UnaryExpr):
        return lp.UnaryExpr(
            operator=node.operator,
            operand=_normalize_expr(lp, node.operand),
            line=0,
            column=0,
        )
    if isinstance(node, lp.BinaryExpr):
        return lp.BinaryExpr(
            left=_normalize_expr(lp, node.left),
            operator=node.operator,
            right=_normalize_expr(lp, node.right),
            line=0,
            column=0,
        )
    if isinstance(node, lp.SequenceExpr):
        return lp.SequenceExpr(
            items=_normalize_expr_items(lp, node.items),
            separators=list(node.separators),
            line=0,
            column=0,
        )
    if isinstance(node, lp.DelimitedExpr):
        normalized = lp.DelimitedExpr(
            opener=node.opener,
            items=_normalize_expr_items(lp, node.items),
            separators=list(node.separators),
            closer=node.closer,
            line=0,
            column=0,
        )
        if normalized.opener == "{" and normalized.closer == "}" and "|" in normalized.separators:
            condition_segments, target_segment = lp._canonicalize_pipe_segments(
                lp._split_condition_segments(normalized)
            )
            return lp._build_canonical_pipe_delimited_expr(
                condition_segments,
                target_segment,
                line=0,
                column=0,
            )
        return normalized
    if isinstance(node, lp.AttributeExpr):
        return lp.AttributeExpr(
            base=_normalize_expr(lp, node.base) if node.base is not None else None,
            attribute=node.attribute,
            line=0,
            column=0,
        )
    if isinstance(node, lp.CallExpr):
        return lp.CallExpr(
            callee=_normalize_expr(lp, node.callee),
            args=_normalize_expr_items(lp, node.args),
            separators=list(node.separators),
            delimiter=node.delimiter,
            line=0,
            column=0,
        )
    if isinstance(node, lp.IndexExpr):
        return lp.IndexExpr(
            base=_normalize_expr(lp, node.base),
            index=_normalize_delimited_expr(lp, node.index),
            line=0,
            column=0,
        )
    if isinstance(node, lp.QuantifiedExpr):
        return lp.QuantifiedExpr(
            quantifier=node.quantifier,
            body=_normalize_delimited_expr(lp, node.body),
            line=0,
            column=0,
        )
    if isinstance(node, lp.Heading):
        return lp.Heading(
            title=node.title,
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )
    if isinstance(node, lp.Import):
        return lp.Import(
            module_path=node.module_path,
            line=0,
            column=0,
            body=_normalize_statement_block(lp, node.body),
            trailing_comment=None,
        )
    if isinstance(node, lp.ExpressionStatement):
        return lp.ExpressionStatement(
            expression=_normalize_expr(lp, node.expression),
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )
    if isinstance(node, lp.Declaration):
        return lp.Declaration(
            head=_normalize_expr(lp, node.head) if node.head is not None else None,
            input_expr=_normalize_expr(lp, node.input_expr) if node.input_expr is not None else None,
            output_expr=_normalize_expr(lp, node.output_expr) if node.output_expr is not None else None,
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            alias=_normalize_expr(lp, node.alias) if node.alias is not None else None,
            trailing_comment=None,
        )
    if isinstance(node, lp.Condition):
        return lp.Condition(
            quantifier=node.quantifier,
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )
    if isinstance(node, lp.Premise):
        return lp.Premise(
            expression=_normalize_expr(lp, node.expression),
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )
    if isinstance(node, lp.Branch):
        return lp.Branch(
            expression=_normalize_expr(lp, node.expression),
            body=_normalize_statement_block(lp, node.body),
            line=0,
            column=0,
            trailing_comment=None,
        )
    raise TypeError(f"unsupported node type: {type(node).__name__}")


def _normalize_statement_block(lp, items) -> list:
    normalized_items: list = []
    for item in items:
        normalized_item = normalize_semantic_tree(lp, item)
        if isinstance(normalized_item, lp.Statement):
            normalized_items.append(normalized_item)
    return normalized_items


def _normalize_expr_items(lp, items) -> list:
    return [_normalize_expr(lp, item) if item is not None else None for item in items]


def _normalize_expr(lp, expr):
    normalized_expr = normalize_semantic_tree(lp, expr)
    assert isinstance(normalized_expr, lp.Expr)
    if _is_redundant_grouped_expr(lp, normalized_expr):
        inner_expr = normalized_expr.items[0]
        assert isinstance(inner_expr, lp.Expr)
        return inner_expr
    return normalized_expr


def _normalize_delimited_expr(lp, expr):
    normalized_expr = normalize_semantic_tree(lp, expr)
    assert isinstance(normalized_expr, lp.DelimitedExpr)
    return normalized_expr


def _is_redundant_grouped_expr(lp, expr) -> bool:
    return (
        isinstance(expr, lp.DelimitedExpr)
        and expr.opener == "("
        and expr.closer == ")"
        and len(expr.items) == 1
        and not expr.separators
        and expr.items[0] is not None
    )
