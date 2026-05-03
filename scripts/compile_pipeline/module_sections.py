"""Stage-3 module-section parser and related source-structure helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from compile_pipeline.errors import CompileError
from compile_pipeline.source_utils import (
    LiteralValue,
    UnexpectedInput,
    encode_char_literal,
    find_quoted_literal_end,
    format_lark_error,
    is_literal_quote_start,
    is_literal_text,
    is_raw_string_literal_start,
    literal_quote_index,
    parse_literal_text,
    remove_comments,
)
from inheritance_sources import CAPITAL_INTRINSIC_SYMS

INFER_OPERATORS = ("=", ">", "<", ">=", "<=", "≤", "≥", "∈", "∉", "⊂", "⊄", "⊆", "⊈", "≠")
FRESH_PREFIX = "__logic_language_out"
DECL_OUTPUT_MARKER = "__compiler_function_outputs"
INTRINSIC_SYMS = tuple(sorted(CAPITAL_INTRINSIC_SYMS | {"true", "false"}))


@dataclass
class Statement:
    text: str
    sub_modules: list["Module"] = field(default_factory=list)


@dataclass
class Module:
    type: str
    syms: list[str]
    predicate_statements: list[Statement]
    target_statements: list[Statement]
    quantifier: str | None = None


@dataclass
class LoweredTerm:
    generated_syms: list[str] = field(default_factory=list)
    generated_predicate_statements: list[Statement] = field(default_factory=list)
    output_statements: list[Statement] = field(default_factory=list)


class ModuleCompiler:
    def __init__(self, parser: Any) -> None:
        self.parser = parser
        self.fresh_index = 0

    def compile(self, text: str) -> Module:
        stripped = strip_outer_blank_lines(remove_comments(text))
        if not stripped:
            raise CompileError("empty module text")
        return self.parse_module(stripped, default_quantifier="∀")

    def parse_module(self, text: str, default_quantifier: str = "∀") -> Module:
        text = strip_outer_blank_lines(text)
        expr = self.try_parse_wrapped_module(text)
        if expr is not None:
            return expr
        return self.parse_line_module(text, default_quantifier)

    def try_parse_wrapped_module(self, text: str) -> Module | None:
        text = text.strip()
        quantifier: str | None = None
        body_start = 0
        if text.startswith(("∀", "∃")):
            quantifier = text[0]
            body_start = 1
        if body_start >= len(text) or text[body_start] != "{":
            return None
        close = find_matching(text, body_start, "{", "}")
        if close != len(text) - 1:
            return None
        try:
            self.parser.parse(text)
        except UnexpectedInput as error:
            raise CompileError(format_lark_error(error)) from error
        body = text[body_start + 1 : close]
        if quantifier is not None:
            return self.build_module("quantifier", quantifier, body)
        if self.is_image_set_body(body):
            return self.parse_image_set(body)
        return self.build_module("set", None, body)

    def parse_line_module(self, text: str, quantifier: str) -> Module:
        lines = logical_lines(text)
        lowered_lines = self.lower_line_blocks(lines)
        body = "\n".join(lowered_lines)
        return self.build_module("quantifier", quantifier, body)

    def lower_line_blocks(self, lines: list[str]) -> list[str]:
        output: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            indent, content = split_indent(line)
            if content in {"∀", "∃"} and index + 1 < len(lines):
                block, next_index = collect_indented_block(lines, index + 1, indent)
                if block:
                    module_text = content + "{\n" + unindent_block(block) + "\n}"
                    output.append(module_text)
                    index = next_index
                    continue
            if index + 1 < len(lines):
                block, next_index = collect_indented_block(lines, index + 1, indent)
                if block:
                    output.extend(self.lower_header_with_block(content, unindent_block(block)))
                    index = next_index
                    continue
            output.append(content)
            index += 1
        return output

    def lower_header_with_block(self, header: str, block: str) -> list[str]:
        if header.startswith("@"):
            return ["∀{\n" + block + "\n}"]
        if header.startswith("|-"):
            branch_ps = header[2:].strip()
            return ["∀{\n| " + branch_ps + "\n" + block + "\n}"]
        declaration = parse_declaration(header)
        if declaration is None:
            return [header, "∀{\n" + block + "\n}"]
        name, inputs, outputs, arrow = declaration
        if arrow == "->":
            call = call_text(name, inputs)
            target = f"{tuple_or_single(outputs)} = {call}"
            return [f"{name}: {tuple_or_single(inputs)} => {tuple_or_single(outputs)}", "∀{\n" + target + "\n" + block + "\n}"]
        call = call_text(name, inputs)
        target = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        marker = f"{DECL_OUTPUT_MARKER}({', '.join(outputs)})"
        return [f"Function ~ {name}", "∀{\n| " + ", ".join(inputs + outputs) + "\n| " + marker + "\n| " + target + "\n" + block + "\n}"]

    def build_module(self, module_type: str, quantifier: str | None, body: str) -> Module:
        sections = split_sections(body)
        if not sections:
            raise CompileError("module requires target statements")
        target_section = sections[-1]
        before_target = sections[:-1]
        syms: list[str] = []
        predicate_sections: list[str] = []
        for section in before_target:
            candidates = parse_binder_list(section)
            if candidates:
                syms.extend(candidates)
            else:
                predicate_sections.append(section)
        predicate_texts = split_terms("\n".join(predicate_sections))
        target_texts = split_terms(target_section)
        if not syms:
            syms = infer_syms(predicate_texts)
        predicate_statements: list[Statement] = []
        target_statements: list[Statement] = []
        generated_syms: list[str] = []
        for term in predicate_texts:
            lowered = self.lower_term(term, target_section=False)
            generated_syms.extend(lowered.generated_syms)
            predicate_statements.extend(lowered.generated_predicate_statements)
            predicate_statements.extend(lowered.output_statements)
        for term in target_texts:
            lowered = self.lower_term(term, target_section=True)
            generated_syms.extend(lowered.generated_syms)
            predicate_statements.extend(lowered.generated_predicate_statements)
            target_statements.extend(lowered.output_statements)
        syms = dedupe([*syms, *generated_syms])
        if module_type == "set" and not syms:
            raise CompileError("set module requires non-empty syms")
        if not target_statements:
            raise CompileError("module requires non-empty target_statements")
        return Module(
            type=module_type,
            quantifier=quantifier if module_type == "quantifier" else None,
            syms=syms,
            predicate_statements=predicate_statements,
            target_statements=target_statements,
        )

    def parse_image_set(self, body: str) -> Module:
        source, target = split_top_level_once(body, "=>")
        out_sym = self.fresh_sym(source + target)
        exists_body = source + " | " + out_sym + " = " + target.strip()
        submodule = self.build_module("quantifier", "∃", exists_body)
        return Module(
            type="set",
            syms=[out_sym],
            predicate_statements=[],
            target_statements=[Statement(text="$module0", sub_modules=[submodule])],
        )

    def lower_term(self, text: str, *, target_section: bool) -> LoweredTerm:
        text = text.strip()
        rewritten, sub_modules = self.extract_sub_modules(text)
        direct_assignment = self.parse_direct_literal_assignment(rewritten)
        if direct_assignment is not None:
            sym, literal = direct_assignment
            lowered = [self.compile_statement_text(statement_text) for statement_text in self.lower_literal_assignment(sym, literal)]
            return LoweredTerm(output_statements=lowered)
        rewritten, generated_syms, generated_predicates = self.lift_literals_in_text(rewritten)
        if not rewritten:
            raise CompileError("literal cannot be used as a standalone statement")
        return LoweredTerm(
            generated_syms=generated_syms,
            generated_predicate_statements=[self.compile_statement_text(statement_text) for statement_text in generated_predicates],
            output_statements=[self.compile_statement_text(rewritten, sub_modules=sub_modules)],
        )

    def compile_statement_text(self, text: str, *, sub_modules: list[Module] | None = None) -> Statement:
        text = text.strip()
        text = lower_member_calls(text)
        if sub_modules is None:
            rewritten, sub_modules = self.extract_sub_modules(text)
        else:
            rewritten = text
        return Statement(text=rewritten, sub_modules=sub_modules)

    def extract_sub_modules(self, text: str) -> tuple[str, list[Module]]:
        output: list[str] = []
        sub_modules: list[Module] = []
        index = 0
        while index < len(text):
            start = find_next_module_start(text, index)
            if start is None:
                output.append(text[index:])
                break
            output.append(text[index:start])
            module_start = start + 1 if text[start] in {"∀", "∃"} else start
            end = find_matching(text, module_start, "{", "}")
            module_text = text[start : end + 1]
            placeholder = f"$module{len(sub_modules)}"
            sub_modules.append(self.parse_module(module_text))
            output.append(placeholder)
            index = end + 1
        return "".join(output).strip(), sub_modules

    def is_image_set_body(self, body: str) -> bool:
        stripped = body.lstrip()
        return stripped.startswith("|") and has_top_level(body, "=>")

    def fresh_sym(self, seed: str) -> str:
        while True:
            sym = f"{FRESH_PREFIX}{self.fresh_index}"
            self.fresh_index += 1
            if sym not in seed:
                return sym

    def parse_direct_literal_assignment(self, text: str) -> tuple[str, LiteralValue] | None:
        assignment_index = top_level_assignment_index(text)
        if assignment_index is None:
            return None
        left = text[:assignment_index].strip()
        right = text[assignment_index + 1 :].strip()
        if is_literal_text(left):
            raise CompileError("literal cannot appear on assignment left-hand side")
        literal = parse_literal_text(right)
        if literal is None or not is_plain_sym(left):
            return None
        return left, literal

    def lower_literal_assignment(self, sym: str, literal: LiteralValue) -> list[str]:
        if literal.kind == "char":
            return [f"Char~{sym}", f"{sym} = {encode_char_literal(literal.value)}"]
        statements = [f"String~{sym}", f"{sym}.size = {len(literal.value)}"]
        statements.extend(f"{sym}[{index}] = {encode_char_literal(char)}" for index, char in enumerate(literal.value))
        return statements

    def lift_literals_in_text(self, text: str) -> tuple[str, list[str], list[str]]:
        output: list[str] = []
        generated_syms: list[str] = []
        generated_predicates: list[str] = []
        index = 0
        while index < len(text):
            if is_literal_quote_start(text, index):
                literal = parse_literal_text(text[index : find_quoted_literal_end(text, index) + 1])
                if literal is None:
                    raise CompileError("invalid literal")
                fresh = self.fresh_sym(text)
                generated_syms.append(fresh)
                generated_predicates.extend(self.lower_literal_assignment(fresh, literal))
                output.append(fresh)
                index += len(literal.raw)
                continue
            output.append(text[index])
            index += 1
        return "".join(output).strip(), generated_syms, generated_predicates


def strip_outer_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    pending: list[str] = []
    balance = 0
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        pending.append(line)
        balance += brace_delta(line)
        if balance <= 0:
            lines.append("\n".join(pending))
            pending = []
            balance = 0
    if pending:
        raise CompileError("unclosed {")
    return lines


def brace_delta(line: str) -> int:
    delta = 0
    index = 0
    while index < len(line):
        char = line[index]
        if is_literal_quote_start(line, index):
            index = find_quoted_literal_end(line, index) + 1
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        index += 1
    return delta


def split_indent(line: str) -> tuple[int, str]:
    first_line = line.splitlines()[0]
    return len(first_line) - len(first_line.lstrip(" ")), line.strip()


def collect_indented_block(lines: list[str], start: int, parent_indent: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start
    while index < len(lines):
        indent, _ = split_indent(lines[index])
        if indent <= parent_indent:
            break
        block.append(lines[index])
        index += 1
    return block, index


def unindent_block(lines: Iterable[str]) -> str:
    block = list(lines)
    indents = [len(line) - len(line.lstrip(" ")) for line in block if line.strip()]
    trim = min(indents) if indents else 0
    return "\n".join(line[trim:] for line in block)


def split_sections(body: str) -> list[str]:
    if "\n" in body:
        line_sections = split_multiline_sections(body)
        if line_sections:
            return line_sections
    sections = split_top_level(body, "|")
    if len(sections) == 1:
        return [section.strip() for section in sections if section.strip()]
    cleaned = [section.strip() for section in sections]
    return [section for section in cleaned if section]


def split_multiline_sections(body: str) -> list[str]:
    sections: list[str] = []
    target_lines: list[str] = []
    section_lines: list[str] = []
    balance = 0
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if section_lines:
            section_lines.append(line)
            balance += brace_delta(line)
            if balance <= 0:
                sections.append("\n".join(section_lines))
                section_lines = []
                balance = 0
            continue
        if balance == 0 and line.startswith("|"):
            if target_lines:
                sections.append("\n".join(target_lines))
                target_lines = []
            section = line[1:].strip()
            if section:
                balance = brace_delta(section)
                if balance > 0:
                    section_lines = [section]
                else:
                    sections.append(section)
        elif balance == 0 and is_plain_sym(line):
            if target_lines:
                sections.append("\n".join(target_lines))
                target_lines = []
            sections.append(line)
        else:
            target_lines.append(line)
            balance += brace_delta(line)
            if balance < 0:
                balance = 0
    if section_lines:
        sections.append("\n".join(section_lines))
    if target_lines:
        sections.append("\n".join(target_lines))
    return sections


def split_terms(text: str) -> list[str]:
    terms: list[str] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in {",", "\n"}:
            term = text[start:index].strip()
            if term:
                terms.append(term)
            start = index + 1
        index += 1
    term = text[start:].strip()
    if term:
        terms.append(term)
    return terms


def split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and text.startswith(separator, index):
            if separator == "|":
                previous_char = text[index - 1] if index > 0 else ""
                next_char = text[index + 1] if index + 1 < len(text) else ""
                if previous_char == "|" or next_char == "|":
                    index += 1
                    continue
            parts.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(text[start:])
    return parts


def split_top_level_once(text: str, separator: str) -> tuple[str, str]:
    parts = split_top_level(text, separator)
    if len(parts) < 2:
        raise CompileError(f"expected top-level {separator}")
    return parts[0], separator.join(parts[1:])


def has_top_level(text: str, separator: str) -> bool:
    return len(split_top_level(text, separator)) > 1


def find_matching(text: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise CompileError(f"unclosed {open_char}")


def find_next_module_start(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        char = text[index]
        if char in {"∀", "∃"} and index + 1 < len(text) and text[index + 1] == "{":
            return index
        if char == "{":
            try:
                end = find_matching(text, index, "{", "}")
            except CompileError:
                return index
            body = text[index + 1 : end].strip()
            if body.startswith("|") or has_top_level(body, "|") or has_top_level(body, "=>"):
                return index
            index = end + 1
            continue
        index += 1
    return None


def parse_binder_list(section: str) -> list[str] | None:
    terms = split_terms(section)
    if not terms:
        return None
    syms: list[str] = []
    for term in terms:
        term = term.strip()
        if term.startswith("(") and term.endswith(")"):
            nested = [part.strip() for part in split_top_level(term[1:-1], ",") if part.strip()]
            if not nested or not all(is_plain_sym(part) for part in nested):
                return None
            syms.extend(nested)
        elif is_plain_sym(term):
            syms.append(term)
        else:
            return None
    return syms


def is_plain_sym(text: str) -> bool:
    if re.fullmatch(r"[^\W\d]\w*'?", text, flags=re.UNICODE) is not None:
        return True
    return len(text) == 1 and not text.isspace() and not text.isdigit() and text not in {"(", ")", "[", "]", "{", "}", ",", '"', "'"}


def infer_syms(predicate_texts: list[str]) -> list[str]:
    syms: list[str] = []
    for text in predicate_texts:
        for op in INFER_OPERATORS:
            if op in text:
                left = text.split(op, 1)[0].strip()
                parsed = parse_binder_list(left)
                if parsed:
                    syms.extend(parsed)
                break
        if "~" in text:
            right = text.split("~", 1)[1].strip()
            if is_plain_sym(right):
                syms.append(right)
    return dedupe(syms)


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def parse_declaration(text: str) -> tuple[str, list[str], list[str], str] | None:
    colon_index = declaration_colon_index(text)
    if colon_index is None:
        return None
    name = text[:colon_index].strip()
    rest = text[colon_index + 1 :].strip()
    match = re.match(r"^(?P<inputs>.+?)\s*(?P<arrow>=>|->)\s*(?P<outputs>.+)$", rest)
    if not name or not match:
        return None
    if "::" in name:
        name = name.split("::")[-1]
    return (
        name,
        parse_signature_terms(match.group("inputs")),
        parse_signature_terms(match.group("outputs")),
        match.group("arrow"),
    )


def declaration_colon_index(text: str) -> int | None:
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == ":":
            previous_char = text[index - 1] if index > 0 else ""
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if previous_char == ":" or next_char == ":":
                index += 1
                continue
            return index
        index += 1
    return None


def top_level_assignment_index(text: str) -> int | None:
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == "=":
            previous_char = text[index - 1] if index > 0 else ""
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if previous_char in {"<", ">", "!", "="} or next_char in {">", "="}:
                index += 1
                continue
            return index
        index += 1
    return None


def parse_signature_terms(text: str) -> list[str]:
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    terms = []
    for term in split_top_level(text, ","):
        term = term.strip()
        if "~" in term:
            term = term.split("~", 1)[1].strip()
        if term:
            terms.append(term)
    return terms


def tuple_or_single(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return "(" + ", ".join(values) + ")"


def call_text(name: str, inputs: list[str]) -> str:
    return name + "(" + ", ".join(inputs) + ")"


def lower_member_calls(text: str) -> str:
    pattern = re.compile(r"\b(?P<recv>[A-Za-z_][A-Za-z0-9_']*)\.(?P<name>[A-Za-z_][A-Za-z0-9_']*)(?:\((?P<args>[^()]*)\))?")

    def replace(match: re.Match[str]) -> str:
        receiver = match.group("recv")
        name = match.group("name")
        args = match.group("args")
        if args is None:
            return f"{name}({receiver})"
        args = args.strip()
        if not args:
            return f"{name}({receiver})"
        return f"{name}({receiver}, {args})"

    previous = None
    current = text
    while previous != current:
        previous = current
        current = pattern.sub(replace, current)
    return current
