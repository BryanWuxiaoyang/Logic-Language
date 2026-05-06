#!/usr/bin/env python3
"""Stage 2: desugar logic-language module text before AST compilation."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import (
    BRANCH_MODULE_MARKER,
    DECL_BODY_OUTPUT_MARKER,
    DECL_OUTPUT_MARKER,
    Module,
    ModuleCompiler,
    Statement,
    class_member_owner_name,
    dedupe,
    explicit_class_header_sym,
    infer_syms,
    GENERATED_SYM_PREFIX,
    is_plain_sym,
    logical_lines,
    lower_member_calls,
    parse_signature_terms,
    split_indent,
    strip_outer_blank_lines,
    top_level_assignment_index,
)
from compile_pipeline.source_utils import (
    IMPORT_RE,
    expand_imports,
    find_quoted_literal_end,
    is_literal_quote_start,
    load_lark_parser,
    load_tokens,
    normalize_latex,
    remove_comments,
    skill_dir,
)
from syntax_check_common import STDIN_FILE, collect_top_level_declarations, make_located_text
from inheritance_sources import SYMBOL_SOURCE, selected_inheritance_source


NUMERIC_LITERAL_RE = re.compile(r"(?<![\w'])\d+(?:\.\d+)?(?![\w'])")
CANONICAL_INFIX_OPERATORS = {"~", "=", "!=", "≠", ">=", "≥", "<=", "≤", ">", "<", "∈", "∉", "⊂", "⊄", "⊆", "⊈"}


class DesugarError(CompileError):
    """Raised when module text cannot be desugared."""


@dataclass(frozen=True)
class BindingInfo:
    name: str


@dataclass(frozen=True)
class ScopeState:
    ancestor_bound_syms: set[str]


@dataclass(frozen=True)
class DesugarResult:
    text: str
    import_count: int
    body_line_count: int
    visible_sym_count: int

    def summary(self) -> str:
        return "\n".join(
            [
                "stage: stage2_desugar_module_text",
                f"imports: {self.import_count}",
                f"body_lines: {self.body_line_count}",
                f"visible_syms: {self.visible_sym_count}",
                "desugared_text:",
                self.text.rstrip(),
            ]
        )


def run(text: str, base_dir: Path | str = ".") -> DesugarResult:
    base_path = Path(base_dir).resolve()
    tokens = load_tokens()
    import_lines, body_text = split_imports(text)
    output_imports = dedupe([normalize_latex(line, tokens) for line in import_lines])

    normalized_body = normalize_latex(body_text, tokens)
    visible_text = visible_context_text(text, base_path, tokens)
    visible_syms = (
        collect_visible_syms(visible_text)
        | collect_free_class_owner_syms(visible_text)
        | collect_free_class_owner_syms(normalized_body)
    )

    body = strip_outer_blank_lines(remove_comments(normalized_body))
    if not body:
        desugared = "\n".join(output_imports) + "\n"
        return DesugarResult(desugared, len(output_imports), 0, len(visible_syms))

    compiler = ModuleCompiler(load_lark_parser())
    module = compiler.compile(body)
    desugarer = ModuleDesugarer(visible_syms)
    desugared_body = desugarer.render_module(module, ScopeState(set(visible_syms)), indent=0)
    desugared = "\n".join([*output_imports, desugared_body]) + "\n"
    return DesugarResult(desugared, len(output_imports), len(desugared_body.splitlines()), len(visible_syms))


def desugar_module_text(text: str, base_dir: Path | str = ".") -> str:
    return run(text, base_dir).text


def split_imports(text: str) -> tuple[list[str], str]:
    imports: list[str] = []
    body_lines: list[str] = []
    for line in text.splitlines():
        if IMPORT_RE.match(line):
            imports.append(line.strip())
        else:
            body_lines.append(line)
    return imports, "\n".join(body_lines)


def visible_context_text(text: str, base_dir: Path, tokens: dict[str, str]) -> str:
    import_lines, _ = split_imports(text)
    context_parts: list[str] = []
    for import_line in import_lines:
        context_parts.append(desugar_visible_import(import_line, base_dir))
    return normalize_latex("\n".join(context_parts), tokens)


def desugar_visible_import(import_line: str, base_dir: Path) -> str:
    match = IMPORT_RE.match(import_line)
    if not match:
        return ""
    return expand_imports(import_line, base_dir)


def collect_visible_syms(text: str) -> set[str]:
    cleaned = remove_comments(text)
    located = make_located_text(cleaned, STDIN_FILE, import_origin=True)
    return {declaration.name for declaration in collect_top_level_declarations(located, import_origin_only=True)}


def collect_free_class_owner_syms(text: str) -> set[str]:
    owners: set[str] = set()
    for line in logical_lines(remove_comments(text)):
        _, content = split_indent(line)
        class_header = explicit_class_header_sym(content)
        if class_header is not None:
            owners.add(class_header)
        owner = class_member_owner_name(content)
        if owner is not None and is_plain_sym(owner):
            owners.add(owner)
    return owners


def is_bool_predicate_sym(sym: str) -> bool:
    if is_generated_sym(sym):
        return False
    normalized = sym.lstrip("_").rstrip("'")
    normalized = re.sub(r"\d+$", "", normalized)
    return normalized.startswith("is_")


class ModuleDesugarer:
    def __init__(self, visible_syms: set[str]) -> None:
        self.reserved_syms = set(visible_syms)
        self.fresh_index = 0

    def render_module(self, module: Module, scope: ScopeState, indent: int) -> str:
        output_syms, body_output_syms, predicate_statements = self.extract_function_output_markers(module.predicate_statements)
        output_sym_set = set(output_syms)
        body_output_sym_set = set(body_output_syms)
        declaration_sym_set = set(module.declaration_syms)
        inferred_syms = [] if module.suppress_inferred_syms else self.infer_statement_syms(predicate_statements)
        original_syms = dedupe([*module.syms, *inferred_syms])
        ancestor_bound_syms = set(scope.ancestor_bound_syms)
        local_bindings: list[BindingInfo] = []
        local_syms_set: set[str] = set()
        self.reserved_syms.update(ancestor_bound_syms)

        for source in original_syms:
            local_bindings.append(BindingInfo(source))
            local_syms_set.add(source)
            self.reserved_syms.add(source)

        current_scope = ScopeState(ancestor_bound_syms | local_syms_set)
        local_syms = [binding.name for binding in local_bindings]
        rendered_predicates = [self.render_statement(statement, current_scope) for statement in predicate_statements]
        rendered_targets: list[str] = []
        for statement in module.target_statements:
            rendered_targets.extend(self.render_target_statement(statement, current_scope))
        target_inheritance_rhs = inheritance_rhs_names(rendered_targets)
        premise_binding_lhs = set() if body_output_sym_set else leading_premise_binding_lhs_names(rendered_predicates)
        target_binding_names = output_sym_set | declaration_sym_set
        premise_bindings = [
            binding
            for binding in local_bindings
            if binding.name not in target_binding_names
            and binding.name not in body_output_sym_set
            and binding.name not in premise_binding_lhs
            and binding.name not in target_inheritance_rhs
        ]
        output_bindings = [binding for binding in local_bindings if binding.name in target_binding_names]
        predicates = self.implicit_predicates(premise_bindings, ancestor_bound_syms, rendered_predicates)
        target_inheritance = self.implicit_predicates(output_bindings, ancestor_bound_syms, rendered_targets)
        targets = [*target_inheritance, *rendered_targets]
        predicates.extend(rendered_predicates)
        predicates.extend(self.local_wrapper_predicates(rendered_predicates + targets))
        predicates = dedupe_statements([predicate for predicate in predicates if predicate])
        if module.suppress_inferred_syms:
            predicates = [BRANCH_MODULE_MARKER, *predicates]
        targets = [target for target in targets if target]
        if output_sym_set and len(output_syms) > 1 and not targets:
            targets.append(f"{DECL_OUTPUT_MARKER}({', '.join(output_syms)})")
        if output_sym_set and len(output_syms) == 1 and not targets:
            return ""

        opener = module.quantifier + "{" if module.type == "quantifier" else "{"
        return self.format_module(opener, local_syms, predicates, targets, indent)

    def extract_function_output_markers(self, statements: list[Statement]) -> tuple[list[str], list[str], list[Statement]]:
        declaration_output_syms: list[str] = []
        body_output_syms: list[str] = []
        remaining: list[Statement] = []
        for statement in statements:
            text = statement.text.strip()
            marker_name = self.function_output_marker_name(text)
            if statement.sub_modules or marker_name is None:
                remaining.append(statement)
                continue
            inner = text[len(marker_name) + 1 : -1]
            parsed = [sym for sym in parse_signature_terms(inner) if is_plain_sym(sym)]
            if marker_name == DECL_OUTPUT_MARKER:
                declaration_output_syms.extend(parsed)
            else:
                body_output_syms.extend(parsed)
                remaining.append(statement)
        return dedupe(declaration_output_syms), dedupe(body_output_syms), remaining

    def function_output_marker_name(self, text: str) -> str | None:
        for marker in (DECL_OUTPUT_MARKER, DECL_BODY_OUTPUT_MARKER):
            if text.startswith(marker + "(") and text.endswith(")"):
                return marker
        return None

    def infer_statement_syms(self, statements: list[Statement]) -> list[str]:
        return infer_syms([statement.text for statement in statements])

    def render_statement(self, statement: Statement, scope: ScopeState) -> str:
        text = self.rewrite_statement_text(statement, scope)
        for index, submodule in enumerate(statement.sub_modules):
            rendered = self.render_module(submodule, scope, indent=0)
            text = text.replace(f"$module{index}", rendered)
        return text

    def render_target_statement(self, statement: Statement, scope: ScopeState) -> list[str]:
        if not statement.sub_modules and self.function_output_marker_name(statement.text.strip()) is not None:
            return []
        return [self.render_statement(statement, scope)]

    def rewrite_statement_text(self, statement: Statement, scope: ScopeState) -> str:
        return normalize_legacy_wrapper_statement(lower_member_calls(statement.text))

    def implicit_predicates(self, bindings: list[BindingInfo], visible_syms: set[str], authored_predicates: list[str]) -> list[str]:
        predicates: list[str] = []
        for binding in bindings:
            if is_generated_sym(binding.name) or binding.name in CANONICAL_INFIX_OPERATORS:
                continue
            specific_predicates = self.naming_inheritance(binding.name, visible_syms)
            predicates.extend(specific_predicates)

        inherited_rhs = inheritance_rhs_names([*authored_predicates, *predicates])
        for binding in bindings:
            if is_generated_sym(binding.name) or binding.name in CANONICAL_INFIX_OPERATORS:
                continue
            if binding.name not in inherited_rhs:
                predicates.append(render_infix(SYMBOL_SOURCE, "~", binding.name))
        return predicates

    def naming_inheritance(self, sym: str, visible_syms: set[str]) -> list[str]:
        predicates: list[str] = []
        if is_bool_predicate_sym(sym):
            predicates.append(render_infix("Bool", "~", sym))
            return predicates

        source_sym = selected_inheritance_source(sym, visible_syms)
        if source_sym is not None and source_sym != sym:
            predicates.append(render_infix(source_sym, "~", sym))

        collection = self.collection_inheritance(sym, visible_syms)
        if collection is not None:
            item = self.fresh_sym(f"{sym}_item")
            predicates.append(render_infix(collection[0], "~", sym))
            predicates.append(f"∀{{| {item} | {render_infix(item, '∈', sym)} | {render_infix(collection[1], '~', item)}}}")
        return predicates

    def collection_inheritance(self, sym: str, visible_syms: set[str]) -> tuple[str, str] | None:
        if sym.endswith("_list"):
            source = selected_inheritance_source(sym[: -len("_list")], visible_syms)
            if source is not None:
                return ("Tuple", source)
        if sym.endswith("s") and len(sym) > 1:
            source = selected_inheritance_source(sym[:-1], visible_syms)
            if source is not None:
                return ("Set", source)
        return None

    def local_wrapper_predicates(self, texts: list[str]) -> list[str]:
        predicates: list[str] = []
        for text in texts:
            predicate = wrapper_predicate_for_expression(text)
            if predicate:
                predicates.append(predicate)
        return predicates

    def fresh_sym(self, preferred: str) -> str:
        candidate = preferred
        while candidate in self.reserved_syms:
            candidate = f"{preferred}{self.fresh_index}"
            self.fresh_index += 1
        self.reserved_syms.add(candidate)
        return candidate

    def format_module(
        self,
        opener: str,
        syms: list[str],
        predicates: list[str],
        targets: list[str],
        indent: int,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 4)
        lines = [pad + opener]
        if syms:
            lines.append(inner + "| " + ", ".join(syms))
        for predicate in predicates:
            lines.extend(format_section_line(predicate, inner, prefix="| "))
        for target in targets:
            lines.extend(format_section_line(target, inner, prefix=""))
        lines.append(pad + "}")
        return "\n".join(lines)


def wrapper_predicate_for_expression(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if is_numeric_literal_text(stripped):
        return render_infix("Value", "~", stripped)
    if is_tuple_literal_text(stripped):
        return render_infix("Tuple", "~", stripped)
    if is_set_literal_text(stripped):
        return render_infix("Set", "~", stripped)
    return None


def normalize_legacy_wrapper_statement(text: str) -> str:
    stripped = text.strip()
    for wrapper_sym, validator in (
        ("Tuple", is_tuple_literal_text),
        ("Set", is_set_literal_text),
        ("Value", is_numeric_literal_text),
    ):
        legacy_head = wrapper_sym + "~"
        if not stripped.startswith(legacy_head):
            continue
        rhs = stripped[len(legacy_head) :].strip()
        if validator(rhs):
            return render_infix(wrapper_sym, "~", rhs)
    return text


def is_numeric_literal_text(text: str) -> bool:
    return NUMERIC_LITERAL_RE.fullmatch(text) is not None


def is_tuple_literal_text(text: str) -> bool:
    text = text.strip()
    if len(text) < 2:
        return False
    if text.startswith("("):
        close = ")"
    elif text.startswith("["):
        close = "]"
    else:
        return False
    if not text.endswith(close):
        return False
    try:
        if matching_close(text, 0, text[0], close) != len(text) - 1:
            return False
    except DesugarError:
        return False
    inner = text[1:-1]
    if text[0] == "[" and ":" in inner:
        return False
    if text == "[,]":
        return True
    terms = parse_signature_terms(inner)
    return len(terms) > 1 and "," in inner


def is_set_literal_text(text: str) -> bool:
    text = text.strip()
    if len(text) < 2 or not text.startswith("{") or not text.endswith("}"):
        return False
    try:
        if matching_close(text, 0, "{", "}") != len(text) - 1:
            return False
    except DesugarError:
        return False
    inner = text[1:-1].strip()
    if "|" in inner or "=>" in inner:
        return False
    return True


def replace_symbols(text: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return text
    output: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
            output.append(char)
            index += 1
            continue
        if in_string:
            output.append(char)
            index += 1
            continue
        match = re.match(r"[^\W\d]\w*'*", text[index:], flags=re.UNICODE)
        if match is None:
            output.append(char)
            index += 1
            continue
        token = match.group(0)
        output.append(replacements.get(token, token))
        index += len(token)
    return "".join(output)


def matching_close(text: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    in_string = False
    for index in range(start, len(text)):
        char = text[index]
        if char == '"':
            in_string = not in_string
        if in_string:
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    raise DesugarError(f"unclosed {open_char}")


def format_section_line(text: str, indent: str, prefix: str) -> list[str]:
    lines = text.splitlines() or [text]
    if len(lines) == 1:
        return [indent + prefix + lines[0]]
    output = [indent + prefix + lines[0]]
    output.extend(indent + line for line in lines[1:])
    return output


def dedupe_statements(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = canonical_statement_key(value)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def inheritance_rhs_names(statements: list[str]) -> set[str]:
    names: set[str] = set()
    for statement in statements:
        rhs = inheritance_rhs_name(statement)
        if rhs is not None:
            names.add(rhs)
    return names


def leading_premise_binding_lhs_names(statements: list[str]) -> set[str]:
    names: set[str] = set()
    if not statements:
        return names
    assignment_index = top_level_assignment_index(statements[0])
    if assignment_index is None:
        return names
    lhs = statements[0][:assignment_index].strip()
    for name in parse_signature_terms(lhs):
        if is_plain_sym(name):
            names.add(name)
    return names


def inheritance_rhs_name(statement: str) -> str | None:
    stripped = statement.strip()
    if "\n" in stripped:
        return None
    match = re.match(r"^(.+?)\s*~\s*(.+)$", stripped)
    if not match:
        return None
    rhs = match.group(2).strip()
    if is_plain_sym(rhs):
        return rhs
    return None


def canonical_statement_key(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if is_literal_quote_start(text, index):
            end = find_quoted_literal_end(text, index)
            output.append(text[index : end + 1])
            index = end + 1
            continue
        char = text[index]
        if char.isspace():
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def render_infix(lhs: str, operator: str, rhs: str) -> str:
    if operator in CANONICAL_INFIX_OPERATORS:
        return f"{lhs} {operator} {rhs}"
    return f"{operator}({lhs}, {rhs})"


def is_generated_sym(sym: str) -> bool:
    return sym.startswith(GENERATED_SYM_PREFIX)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 2 desugaring.")
    parser.add_argument("--text", help="module text to desugar; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="base directory for $import")
    args = parser.parse_args()

    source = args.text if args.text is not None else sys.stdin.read()
    try:
        result = run(source, args.base_dir)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(result.summary())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
