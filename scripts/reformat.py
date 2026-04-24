from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import semantic_parser as lp_parser
except ImportError:  # pragma: no cover - module execution fallback
    from . import semantic_parser as lp_parser

LATEX_SYMBOL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Formatting helpers
    ("", ("left", "right")),
    # Quantifiers / logic.
    # Prefer parser-native forms when the language already has an ASCII operator.
    ("∀", ("forall", "all")),
    ("∃", ("exists",)),
    ("!", ("neg", "lnot", "not")),
    ("&&", ("land", "wedge")),
    ("||", ("lor", "vee")),
    # Equality / comparison
    ("≠", ("ne", "neq")),
    ("≤", ("le", "leq", "leqslant", "leqq")),
    ("≥", ("ge", "geq", "geqslant", "geqq")),
    # Set / relation
    ("∈", ("in",)),
    ("∉", ("notin", "nin")),
    ("⊆", ("subseteq", "subset_eq", "subseteqq", "included_in")),
    ("⊂", ("subset", "subsetneq")),
    ("⊇", ("supseteq", "supset_eq", "supseteqq")),
    ("⊃", ("supset", "supsetneq")),
    ("∪", ("cup", "bigcup", "union")),
    ("∩", ("cap", "bigcap", "intersect")),
    ("{}", ("emptyset", "varnothing")),
    # Arrows / implication
    ("→", ("to", "rightarrow", "longrightarrow")),
    ("←", ("leftarrow", "gets")),
    ("↔", ("leftrightarrow",)),
    ("⇒", ("Rightarrow", "Longrightarrow", "implies")),
    ("⇐", ("Leftarrow",)),
    ("⇔", ("Leftrightarrow", "iff")),
    # Grouping / punctuation
    ("{", ("lbrace",)),
    ("}", ("rbrace",)),
    ("(", ("lparen",)),
    (")", ("rparen",)),
    ("[", ("lbrack",)),
    ("]", ("rbrack",)),
    ("|", ("mid", "vert")),
    (":", ("colon",)),
    # Arithmetic / misc
    ("*", ("times", "cdot", "ast")),
    ("/", ("div",)),
    ("...", ("ldots", "cdots", "dots")),
    ("৹", ("concat",)),
    # Greek letters
    ("α", ("alpha",)),
    ("β", ("beta",)),
    ("γ", ("gamma",)),
    ("δ", ("delta",)),
    ("ϵ", ("epsilon",)),
    ("ε", ("varepsilon",)),
    ("ζ", ("zeta",)),
    ("η", ("eta",)),
    ("θ", ("theta",)),
    ("ϑ", ("vartheta",)),
    ("ι", ("iota",)),
    ("κ", ("kappa",)),
    ("λ", ("lambda",)),
    ("μ", ("mu",)),
    ("ν", ("nu",)),
    ("ξ", ("xi",)),
    ("ο", ("omicron",)),
    ("π", ("pi",)),
    ("ρ", ("rho",)),
    ("ϱ", ("varrho",)),
    ("σ", ("sigma",)),
    ("ς", ("varsigma",)),
    ("τ", ("tau",)),
    ("υ", ("upsilon",)),
    ("ϕ", ("phi",)),
    ("φ", ("varphi",)),
    ("χ", ("chi",)),
    ("ψ", ("psi",)),
    ("ω", ("omega",)),
    ("Γ", ("Gamma",)),
    ("Δ", ("Delta",)),
    ("Θ", ("Theta",)),
    ("Λ", ("Lambda",)),
    ("Ξ", ("Xi",)),
    ("Π", ("Pi",)),
    ("Σ", ("Sigma",)),
    ("Υ", ("Upsilon",)),
    ("Φ", ("Phi",)),
    ("Ψ", ("Psi",)),
    ("Ω", ("Omega",)),
)
LATEX_NAME_TO_SYMBOL: dict[str, str] = {
    latex_name: symbol
    for symbol, latex_names in LATEX_SYMBOL_GROUPS
    for latex_name in latex_names
}
NORMALIZED_ASCII_SYMBOLS: dict[str, str] = {
    "｜": "|",
}
LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(slots=True)
class _FormatContext:
    source_lines: tuple[str, ...]
    end_line_cache: dict[int, int]


_CURRENT_FORMAT_CONTEXT: _FormatContext | None = None


def reformat_text(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False

    while i < len(text):
        ch = text[i]

        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                i += 1
                out.append(text[i])
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "#":
            newline = text.find("\n", i)
            if newline == -1:
                out.append(text[i:])
                break
            out.append(text[i:newline + 1])
            i = newline + 1
            continue

        mapped = NORMALIZED_ASCII_SYMBOLS.get(ch)
        if mapped is not None:
            out.append(mapped)
            i += 1
            continue

        if ch == "\\":
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            name = text[i + 1 : j]
            if name:
                out.append(LATEX_NAME_TO_SYMBOL.get(name, text[i:j]))
                i = j
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def pretty_format_text(text: str, *, source_name: str = "<string>") -> str:
    root = lp_parser.parse_program_text(text, source_name=source_name)
    global _CURRENT_FORMAT_CONTEXT
    previous_context = _CURRENT_FORMAT_CONTEXT
    _CURRENT_FORMAT_CONTEXT = _FormatContext(
        source_lines=tuple(text.splitlines()),
        end_line_cache={},
    )
    try:
        if isinstance(root, lp_parser.Program):
            return "\n".join(_format_statement_block(root.items, indent=0))
        if isinstance(root, lp_parser.Condition):
            return "\n".join(_format_condition_lines(root, indent=0))
        if isinstance(root, lp_parser.Statement):
            return "\n".join(_format_statement_lines(root, indent=0))
        if isinstance(root, lp_parser.Expr):
            return _format_expr(root)
        return lp_parser.program_to_source(root)
    finally:
        _CURRENT_FORMAT_CONTEXT = previous_context


def find_unconverted_latex_commands(text: str) -> list[tuple[int, int, str]]:
    pending: list[tuple[int, int, str]] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        index = 0
        in_string = False
        while index < len(line):
            ch = line[index]
            if in_string:
                if ch == "\\" and index + 1 < len(line):
                    index += 2
                    continue
                if ch == '"':
                    in_string = False
                index += 1
                continue
            if ch == "#":
                break
            if ch == '"':
                in_string = True
                index += 1
                continue
            if ch == "\\":
                match = LATEX_COMMAND_RE.match(line, index)
                if match is not None:
                    pending.append((line_no, index + 1, match.group(1)))
                    index = match.end()
                    continue
            index += 1
    return pending


def _format_statement_block(
    items: list[lp_parser.Statement],
    *,
    indent: int,
) -> list[str]:
    lines: list[str] = []
    previous_item: lp_parser.Statement | None = None
    for item in items:
        if previous_item is not None:
            blank_line_count = max(
                _source_blank_line_count(previous_item, item),
                1 if _needs_leading_blank_line(item) else 0,
            )
            lines.extend([""] * blank_line_count)
        lines.extend(_format_statement_lines(item, indent=indent))
        previous_item = item
    return lines


def _source_blank_line_count(
    previous_item: lp_parser.Statement,
    current_item: lp_parser.Statement,
) -> int:
    previous_end_line = _node_end_line(previous_item)
    return max(0, current_item.line - previous_end_line - 1)


def _node_end_line(node: lp_parser.Node | None) -> int:
    if node is None:
        return 0

    context = _CURRENT_FORMAT_CONTEXT
    if context is None:
        return getattr(node, "line", 0)

    cache_key = id(node)
    cached = context.end_line_cache.get(cache_key)
    if cached is not None:
        return cached

    end_line = getattr(node, "line", 0)
    for child in node.children():
        end_line = max(end_line, _node_end_line(child))

    if isinstance(node, lp_parser.DelimitedExpr):
        end_line = _extend_to_closing_delimiter(end_line, node.closer)
    elif isinstance(node, lp_parser.CallExpr) and len(node.delimiter) == 2:
        end_line = _extend_to_closing_delimiter(end_line, node.delimiter[1])

    context.end_line_cache[cache_key] = end_line
    return end_line


def _extend_to_closing_delimiter(end_line: int, closer: str) -> int:
    context = _CURRENT_FORMAT_CONTEXT
    if context is None or end_line <= 0 or end_line >= len(context.source_lines):
        return end_line

    next_line = context.source_lines[end_line].strip()
    if next_line.startswith(closer):
        return end_line + 1
    return end_line


def _was_multiline(node: lp_parser.Node | None) -> bool:
    if node is None:
        return False
    return _node_end_line(node) > getattr(node, "line", 0)


def _needs_leading_blank_line(statement: lp_parser.Statement) -> bool:
    if isinstance(statement, (lp_parser.Declaration, lp_parser.Heading)):
        return True

    if not isinstance(statement, lp_parser.ExpressionStatement):
        return False

    if not statement.body:
        return False

    expr = statement.expression
    if isinstance(expr, lp_parser.IdentifierExpr):
        return True

    return isinstance(expr, lp_parser.BinaryExpr) and expr.operator == "~"


def _source_statement_lines(statement: lp_parser.Statement) -> list[str]:
    context = _CURRENT_FORMAT_CONTEXT
    if context is None:
        return []

    start_line = max(statement.line, 1)
    end_line = _node_end_line(statement)
    if end_line < start_line:
        end_line = start_line
    end_line = min(end_line, len(context.source_lines))
    if start_line > len(context.source_lines):
        return []
    return list(context.source_lines[start_line - 1 : end_line])


def _preserve_non_compression(
    statement: lp_parser.Statement,
    formatted_lines: list[str],
) -> list[str]:
    source_lines = _source_statement_lines(statement)
    if not source_lines:
        return formatted_lines
    # Expand-only formatting: if the source already spans multiple lines,
    # keep the original layout whenever the formatter would not add lines.
    if _was_multiline(statement) and len(formatted_lines) <= len(source_lines):
        return source_lines
    return formatted_lines


def _format_condition_lines(
    condition: lp_parser.Condition,
    *,
    indent: int,
) -> list[str]:
    lines = [(" " * indent) + condition.quantifier]
    lines.extend(_format_statement_block(condition.body, indent=indent + 4))
    return lines


def _format_statement_lines(
    statement: lp_parser.Statement,
    *,
    indent: int,
) -> list[str]:
    prefix = " " * indent
    trailing = lp_parser._format_trailing_comment(statement.trailing_comment)

    if isinstance(statement, lp_parser.Condition):
        lines = _format_condition_lines(statement, indent=indent)
        lines[0] += trailing
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Premise):
        expr_lines = _format_expr_lines(statement.expression, indent=indent)
        lines = [prefix + "| " + expr_lines[0].lstrip() + trailing, *expr_lines[1:]]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Branch):
        expr_lines = _format_expr_lines(statement.expression, indent=indent)
        lines = [prefix + "|- " + expr_lines[0].lstrip() + trailing, *expr_lines[1:]]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.ExpressionStatement):
        expr_lines = _format_expr_lines(statement.expression, indent=indent)
        lines = [prefix + expr_lines[0].lstrip() + trailing, *expr_lines[1:]]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Declaration):
        lines = _format_declaration_lines(statement, indent=indent)
        lines[0] += trailing
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Heading):
        lines = [prefix + "@" + statement.title + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Import):
        lines = [prefix + "$import " + statement.module_path + trailing]
        lines.extend(_format_statement_block(statement.body, indent=indent + 4))
        return _preserve_non_compression(statement, lines)

    if isinstance(statement, lp_parser.Comment):
        lines = [prefix + "#" + (" " + statement.text if statement.text else "")]
        return _preserve_non_compression(statement, lines)

    return _preserve_non_compression(statement, [prefix + repr(statement)])


def _format_expr_lines(expr: lp_parser.Expr | None, *, indent: int) -> list[str]:
    if expr is None:
        return [""]

    if isinstance(expr, lp_parser.BinaryExpr):
        if expr.operator == "::":
            return [_format_expr(expr)]
        left = _format_binary_operand(expr.left)
        right_lines = _format_expr_lines(expr.right, indent=indent)
        if len(right_lines) == 1:
            return [f"{left} {expr.operator} {right_lines[0].lstrip()}"]
        return [f"{left} {expr.operator} {right_lines[0].lstrip()}", *right_lines[1:]]

    if isinstance(expr, lp_parser.CallExpr) and expr.delimiter == "{}":
        callee = _format_atom(expr.callee)
        if len(expr.args) == 1 and isinstance(expr.args[0], lp_parser.DelimitedExpr):
            arg_lines = _format_expr_lines(expr.args[0], indent=indent)
            if len(arg_lines) == 1:
                return [f"{callee}{arg_lines[0].lstrip()}"]
            return [f"{callee}{arg_lines[0].lstrip()}", *arg_lines[1:]]

    if isinstance(expr, lp_parser.CallExpr) and expr.delimiter == "()":
        callee = _format_atom(expr.callee)
        arg_line_groups = [
            _format_expr_lines(arg, indent=indent + 4) if arg is not None else [""]
            for arg in expr.args
        ]
        if _was_multiline(expr) or any(len(arg_lines) > 1 for arg_lines in arg_line_groups):
            if not arg_line_groups:
                return [f"{callee}()"]
            lines = [f"{callee}("]
            child_prefix = " " * (indent + 4)
            for index, arg_lines in enumerate(arg_line_groups):
                group_lines = [child_prefix + arg_lines[0].lstrip(), *arg_lines[1:]]
                if index < len(expr.separators):
                    group_lines[-1] += expr.separators[index]
                lines.extend(group_lines)
            lines.append((" " * indent) + ")")
            return lines

    if isinstance(expr, lp_parser.QuantifiedExpr):
        clause_count = _pipe_clause_count(expr.body)
        if _was_multiline(expr):
            return _format_quantified_brace_lines(expr, indent=indent)
        if clause_count > 2:
            return _format_quantified_brace_lines(expr, indent=indent)

    if isinstance(expr, lp_parser.DelimitedExpr):
        if expr.opener == "{" and expr.closer == "}":
            entry_count = _brace_entry_count(expr)
            if entry_count > 2 or _was_multiline(expr):
                if "|" in expr.separators:
                    return _format_pipe_brace_lines(expr, indent=indent)
                return _format_plain_brace_lines(expr, indent=indent)
        else:
            item_line_groups = [
                _format_expr_lines(item, indent=indent + 4) if item is not None else [""]
                for item in expr.items
            ]
            if _was_multiline(expr) or any(len(group) > 1 for group in item_line_groups):
                lines = [expr.opener]
                child_prefix = " " * (indent + 4)
                for index, group in enumerate(item_line_groups):
                    if not group:
                        group_lines = [child_prefix]
                    else:
                        first_line = child_prefix + group[0].lstrip()
                        rest_lines = [
                            line if line.startswith(" ") else (child_prefix + line.lstrip())
                            for line in group[1:]
                        ]
                        group_lines = [first_line, *rest_lines]
                    if index < len(expr.separators):
                        group_lines[-1] += expr.separators[index]
                    lines.extend(group_lines)
                lines.append((" " * indent) + expr.closer)
                return lines

    return [_format_expr(expr)]


def _pipe_clause_count(expr: lp_parser.DelimitedExpr) -> int:
    condition_segments, target_segment = lp_parser._canonicalize_pipe_segments(
        lp_parser._split_condition_segments(expr)
    )
    return len([segment for segment in condition_segments if segment]) + (
        1 if target_segment else 0
    )


def _brace_entry_count(expr: lp_parser.DelimitedExpr) -> int:
    if "|" in expr.separators:
        return _pipe_clause_count(expr)
    return len([item for item in expr.items if item is not None])


def _format_pipe_brace_lines(
    expr: lp_parser.DelimitedExpr,
    *,
    indent: int,
) -> list[str]:
    condition_segments, target_segment = lp_parser._canonicalize_pipe_segments(
        lp_parser._split_condition_segments(expr)
    )
    lines = ["{"]
    child_prefix = " " * (indent + 4)
    for segment in condition_segments:
        if not segment:
            continue
        lines.append(
            child_prefix + "| " + _format_expr(lp_parser._merge_segment_expr(segment))
        )
    if target_segment:
        lines.append(child_prefix + _format_expr(lp_parser._merge_segment_expr(target_segment)))
    lines.append((" " * indent) + "}")
    return lines


def _format_quantified_brace_lines(
    expr: lp_parser.QuantifiedExpr,
    *,
    indent: int,
) -> list[str]:
    if "|" in expr.body.separators:
        lines = _format_pipe_brace_lines(expr.body, indent=indent)
    else:
        lines = _format_plain_brace_lines(expr.body, indent=indent)
    lines[0] = expr.quantifier + lines[0]
    return lines


def _format_plain_brace_lines(
    expr: lp_parser.DelimitedExpr,
    *,
    indent: int,
) -> list[str]:
    items = [item for item in expr.items if item is not None]
    lines = ["{"]
    child_prefix = " " * (indent + 4)
    for index, item in enumerate(items):
        suffix = "," if index < len(items) - 1 else ""
        lines.append(child_prefix + _format_expr(item) + suffix)
    lines.append((" " * indent) + "}")
    return lines


def _format_declaration(statement: lp_parser.Declaration) -> str:
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


def _format_declaration_lines(
    statement: lp_parser.Declaration,
    *,
    indent: int,
) -> list[str]:
    prefix = " " * indent
    if statement.head is None:
        head = ""
    else:
        head = _format_expr(statement.head)

    if statement.alias is not None:
        head = f"{head}({_format_expr(statement.alias)})" if head else _format_expr(
            statement.alias
        )

    input_expr = _format_expr(statement.input_expr) if statement.input_expr else ""
    output_lines = _format_expr_lines(statement.output_expr, indent=indent)
    declaration_prefix = f"{head}: {input_expr} =>".strip()

    if len(output_lines) == 1:
        suffix = f" {output_lines[0].lstrip()}" if output_lines[0] else ""
        return [f"{prefix}{declaration_prefix}{suffix}".rstrip()]

    first_line = f"{prefix}{declaration_prefix} {output_lines[0].lstrip()}".rstrip()
    return [first_line, *output_lines[1:]]


def _format_expr(expr: lp_parser.Expr | None) -> str:
    if expr is None:
        return ""

    if isinstance(expr, lp_parser.IdentifierExpr):
        return expr.name

    if isinstance(expr, lp_parser.NumberExpr):
        return expr.value

    if isinstance(expr, lp_parser.StringExpr):
        escaped = (
            expr.value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'

    if isinstance(expr, lp_parser.SymbolExpr):
        return expr.value

    if isinstance(expr, lp_parser.UnaryExpr):
        return f"{expr.operator}{_format_atom(expr.operand)}"

    if isinstance(expr, lp_parser.BinaryExpr):
        if expr.operator == "::":
            return f"{_format_member_operand(expr.left)}::{_format_member_operand(expr.right)}"
        return (
            f"{_format_binary_operand(expr.left)} {expr.operator} "
            f"{_format_binary_operand(expr.right)}"
        )

    if isinstance(expr, lp_parser.SequenceExpr):
        parts = [_format_expr(item) for item in expr.items]
        return lp_parser._join_with_separators(parts, expr.separators)

    if isinstance(expr, lp_parser.DelimitedExpr):
        if expr.opener == "{" and expr.closer == "}" and "|" in expr.separators:
            return _format_pipe_delimited_expr(expr)
        parts = [_format_expr(item) for item in expr.items]
        inner = lp_parser._join_with_separators(parts, expr.separators)
        return f"{expr.opener}{inner}{expr.closer}"

    if isinstance(expr, lp_parser.AttributeExpr):
        if expr.base is None:
            return f"::{expr.attribute}"
        return f"{_format_atom(expr.base)}.{expr.attribute}"

    if isinstance(expr, lp_parser.CallExpr):
        if expr.delimiter == "{}":
            if len(expr.args) == 1 and isinstance(expr.args[0], lp_parser.DelimitedExpr):
                return f"{_format_atom(expr.callee)}{_format_expr(expr.args[0])}"
            args = lp_parser._join_with_separators(
                [_format_expr(arg) for arg in expr.args],
                expr.separators,
            )
            return f"{_format_atom(expr.callee)}{{{args}}}"

        args = lp_parser._join_with_separators(
            [_format_expr(arg) for arg in expr.args],
            expr.separators,
        )
        return f"{_format_atom(expr.callee)}({args})"

    if isinstance(expr, lp_parser.IndexExpr):
        return f"{_format_atom(expr.base)}{_format_expr(expr.index)}"

    if isinstance(expr, lp_parser.QuantifiedExpr):
        return f"{expr.quantifier}{_format_expr(expr.body)}"

    return repr(expr)


def _format_pipe_delimited_expr(expr: lp_parser.DelimitedExpr) -> str:
    segments = lp_parser._split_condition_segments(expr)
    condition_segments, target_segment = lp_parser._canonicalize_pipe_segments(segments)

    parts = [""]
    parts.extend(
        _format_expr(lp_parser._merge_segment_expr(segment))
        for segment in condition_segments
        if segment
    )

    if target_segment is not None and target_segment:
        parts.append(_format_expr(lp_parser._merge_segment_expr(target_segment)))
        separators = ["|"] * (len(parts) - 1)
    else:
        separators = ["|"] * len(parts)

    inner = lp_parser._join_with_separators(parts, separators)
    return f"{expr.opener}{inner}{expr.closer}"


def _format_atom(expr: lp_parser.Expr) -> str:
    if isinstance(
        expr,
        (
            lp_parser.IdentifierExpr,
            lp_parser.NumberExpr,
            lp_parser.StringExpr,
            lp_parser.SymbolExpr,
            lp_parser.AttributeExpr,
            lp_parser.CallExpr,
            lp_parser.IndexExpr,
            lp_parser.QuantifiedExpr,
            lp_parser.DelimitedExpr,
        ),
    ):
        return _format_expr(expr)
    return f"({_format_expr(expr)})"


def _format_binary_operand(expr: lp_parser.Expr) -> str:
    if isinstance(expr, lp_parser.BinaryExpr) and expr.operator == "->":
        return _format_expr(expr)
    if isinstance(expr, lp_parser.UnaryExpr):
        return _format_expr(expr)
    return _format_atom(expr)


def _format_member_operand(expr: lp_parser.Expr) -> str:
    if isinstance(expr, lp_parser.BinaryExpr) and expr.operator == "::":
        return _format_expr(expr)
    if isinstance(
        expr,
        (
            lp_parser.IdentifierExpr,
            lp_parser.NumberExpr,
            lp_parser.StringExpr,
            lp_parser.SymbolExpr,
            lp_parser.AttributeExpr,
            lp_parser.CallExpr,
            lp_parser.IndexExpr,
            lp_parser.QuantifiedExpr,
            lp_parser.DelimitedExpr,
            lp_parser.UnaryExpr,
        ),
    ):
        return _format_expr(expr)
    return f"({_format_expr(expr)})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reformat a .lp file by normalizing symbols and applying canonical layout."
        )
    )
    parser.add_argument("lp_path", help="Path to the input .lp file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.lp_path)
    text = source_path.read_text(encoding="utf-8")
    normalized = reformat_text(text)
    unresolved = find_unconverted_latex_commands(normalized)
    if unresolved:
        first_line, first_column, first_name = unresolved[0]
        print(
            (
                f"{source_path}:{first_line}:{first_column}: "
                f"unconverted LaTeX command '\\{first_name}'. "
                "Extend LATEX_SYMBOL_GROUPS in scripts/reformat.py."
            ),
            file=sys.stderr,
        )
        return 1

    reformatted = pretty_format_text(normalized, source_name=str(source_path))

    if args.output:
        Path(args.output).write_text(reformatted, encoding="utf-8")
    else:
        sys.stdout.write(reformatted)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
