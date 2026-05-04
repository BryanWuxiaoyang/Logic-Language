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
GENERATED_SYM_PREFIX = "^"
SPECIAL_IDENTIFIER_SYMS = {"[:]", "[]"}
FRESH_PREFIX = "^logic_language_out"
DECL_OUTPUT_MARKER = "__compiler_function_outputs"
DECL_BODY_OUTPUT_MARKER = "__compiler_function_body_outputs"
BRANCH_MODULE_MARKER = "__compiler_branch_module"
CLASS_FIELD_MARKER = "__compiler_class_field"
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
    declaration_syms: list[str] = field(default_factory=list)
    suppress_inferred_syms: bool = False


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
            content = erase_coloncolon_statement_head(content)
            if content in {"∀", "∃"} and index + 1 < len(lines):
                block, next_index = collect_indented_block(lines, index + 1, indent)
                if block:
                    module_text = content + "{\n" + self.lower_nested_block(unindent_block(block)) + "\n}"
                    output.append(module_text)
                    index = next_index
                    continue
            if index + 1 < len(lines):
                block, next_index = collect_indented_block(lines, index + 1, indent)
                if block:
                    premise_declaration = parse_premise_declaration(content)
                    if premise_declaration is not None:
                        output.extend(self.lower_premise_declaration(premise_declaration, block=self.lower_nested_block(unindent_block(block))))
                        index = next_index
                        continue
                    output.extend(self.lower_header_with_block(content, unindent_block(block)))
                    index = next_index
                    continue
            if content.startswith("|-"):
                raise CompileError("branch header requires an indented block")
            premise_declaration = parse_premise_declaration(content)
            if premise_declaration is not None:
                output.extend(self.lower_premise_declaration(premise_declaration, block=None))
                index += 1
                continue
            declaration = parse_declaration(content)
            if declaration is not None:
                output.extend(self.lower_declaration(declaration, block=None))
            else:
                reject_unsupported_coloncolon(content)
                output.append(content)
            index += 1
        return output

    def lower_header_with_block(self, header: str, block: str) -> list[str]:
        if header.startswith("@"):
            return ["∀{\n" + block + "\n}"]
        if header.startswith("|-"):
            branch_ps = header[2:].strip()
            return ["| ∀{\n| " + BRANCH_MODULE_MARKER + "\n| " + branch_ps + "\n" + self.lower_nested_block(block) + "\n}"]
        if is_class_field_marker(header):
            raise CompileError("class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration")
        class_sym = class_header_sym(header)
        if class_sym is not None:
            return self.lower_class_block(header, class_sym, block)
        declaration = parse_declaration(header)
        if declaration is None:
            reject_unsupported_coloncolon(header)
            return [header, "∀{\n" + block + "\n}"]
        return self.lower_declaration(declaration, block=self.lower_nested_block(block))

    def lower_declaration(self, declaration: tuple[str, list[str], list[str], str], block: str | None) -> list[str]:
        name, inputs, outputs, arrow = declaration
        if arrow != "=>":
            raise CompileError("function-assign '->' is not supported; use '=>' with an indented function body")
        output = [declaration_kind_fact(name, outputs), self.declaration_module_text(name, inputs, outputs)]
        if block is not None:
            output.append(self.function_body_module_text(name, inputs, outputs, block))
        return output

    def lower_premise_declaration(self, declaration: tuple[str, list[str], list[str], str], block: str | None) -> list[str]:
        return [premise_artifact(artifact) for artifact in self.lower_declaration(declaration, block)]

    def declaration_module_text(self, name: str, inputs: list[str], outputs: list[str]) -> str:
        call = call_text(name, inputs)
        binding = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        marker = f"{DECL_OUTPUT_MARKER}({', '.join(outputs)})"
        return "∀{\n| " + ", ".join(inputs + outputs) + "\n| " + marker + "\n| " + binding + "\n" + marker + "\n}"

    def function_body_module_text(self, name: str, inputs: list[str], outputs: list[str], block: str) -> str:
        call = call_text(name, inputs)
        binding = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        marker = f"{DECL_BODY_OUTPUT_MARKER}({', '.join(outputs)})"
        return "∀{\n| " + ", ".join(inputs + outputs) + "\n| " + marker + "\n| " + binding + "\n" + block + "\n}"

    def lower_class_block(self, header: str, class_sym: str, block: str) -> list[str]:
        expanded_lines = class_block_prefix_lines(header, class_sym)
        body_lines = logical_lines(block)
        index = 0
        while index < len(body_lines):
            line = body_lines[index]
            indent, content = split_indent(line)
            if indent != 0:
                raise CompileError("class-declaration body line must start with '::'")
            if not content.startswith("::"):
                raise CompileError("class-declaration body line must start with '::'")
            if content.startswith(":::") or content.strip() == "::":
                raise CompileError("class-declaration body line must start with '::' followed by a declaration")
            class_line = f"{class_sym}{content}"
            nested, next_index = collect_indented_block(body_lines, index + 1, indent)
            expanded_lines.append(class_line)
            expanded_lines.extend(nested)
            index = next_index
        return self.lower_line_blocks(expanded_lines)

    def lower_nested_block(self, block: str) -> str:
        return "\n".join(self.lower_line_blocks(logical_lines(block)))

    def build_module(self, module_type: str, quantifier: str | None, body: str) -> Module:
        declaration_syms = collect_standalone_declaration_syms(body)
        sections = split_sections(body)
        if not sections:
            raise CompileError("module requires target statements")
        target_section = sections[-1]
        before_target = sections[:-1]
        syms: list[str] = []
        predicate_sections: list[str] = []
        suppress_inferred_syms = False
        for section in before_target:
            if section == BRANCH_MODULE_MARKER:
                suppress_inferred_syms = True
                continue
            candidates = parse_binder_list(section)
            if candidates:
                syms.extend(candidates)
            else:
                predicate_sections.append(section)
        predicate_texts = split_terms("\n".join(predicate_sections))
        suppress_inferred_syms = suppress_inferred_syms or BRANCH_MODULE_MARKER in predicate_texts
        predicate_texts = [text for text in predicate_texts if text != BRANCH_MODULE_MARKER]
        target_texts = split_terms(target_section)
        if not syms and not suppress_inferred_syms:
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
            declaration_syms=dedupe([sym for sym in declaration_syms if sym in syms]),
            suppress_inferred_syms=suppress_inferred_syms,
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
        reject_unsupported_coloncolon(rewritten)
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


def collect_standalone_declaration_syms(body: str) -> list[str]:
    if "\n" not in body:
        return []
    syms: list[str] = []
    section_balance = 0
    target_balance = 0
    in_bar_section = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if in_bar_section:
            section_balance += brace_delta(line)
            if section_balance <= 0:
                in_bar_section = False
                section_balance = 0
            continue
        if target_balance > 0:
            target_balance += brace_delta(line)
            if target_balance < 0:
                target_balance = 0
            continue
        if line.startswith("|"):
            section = line[1:].strip()
            section_balance = brace_delta(section)
            in_bar_section = section_balance > 0
            continue
        if is_plain_sym(line):
            syms.append(line)
            continue
        target_balance = max(0, brace_delta(line))
    return dedupe(syms)


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
    if text in SPECIAL_IDENTIFIER_SYMS:
        return True
    if is_generated_sym_name(text):
        return True
    if "^" in text:
        return False
    if re.fullmatch(r"[^\W\d]\w*'*", text, flags=re.UNICODE) is not None:
        return True
    return len(text) == 1 and not text.isspace() and not text.isdigit() and text not in {"(", ")", "[", "]", "{", "}", ",", '"', "'", "^"}


def is_generated_sym_name(text: str) -> bool:
    if not text.startswith(GENERATED_SYM_PREFIX) or text == GENERATED_SYM_PREFIX:
        return False
    base = text[len(GENERATED_SYM_PREFIX) :]
    if base.startswith(GENERATED_SYM_PREFIX) or GENERATED_SYM_PREFIX in base:
        return False
    if re.fullmatch(r"[^\W\d]\w*'*", base, flags=re.UNICODE) is not None:
        return True
    return False


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


def class_header_sym(header: str) -> str | None:
    header = header.strip()
    if is_plain_sym(header):
        return header
    return None


def class_block_prefix_lines(header: str, class_sym: str) -> list[str]:
    return [header.strip()]


def erase_coloncolon_statement_head(text: str) -> str:
    stripped = text.strip()
    if "::" not in stripped:
        return stripped
    assignment_index = top_level_assignment_index(stripped)
    if assignment_index is not None and "::" in stripped[:assignment_index]:
        raise CompileError("class-field assignment with '::' is not supported")

    colon_index = declaration_colon_index(stripped)
    if colon_index is not None:
        name = stripped[:colon_index].strip()
        if "::" in name:
            return erase_coloncolon_name(name) + stripped[colon_index:]
        reject_unsupported_coloncolon(stripped)
        return stripped

    if is_bare_coloncolon_field_shorthand(stripped):
        return coloncolon_field_marker(stripped)
    reject_unsupported_coloncolon(stripped)
    return stripped


def reject_unsupported_coloncolon(text: str) -> None:
    if "::" in text:
        raise CompileError("unsupported '::' usage; '::' is only supported in declaration heads")


def erase_coloncolon_name(name: str) -> str:
    if not is_coloncolon_name(name):
        raise CompileError("unsupported '::' usage; '::' is only supported in declaration heads")
    suffix = name.split("::", 1)[1].strip()
    if not suffix:
        raise CompileError("unsupported '::' usage; missing declaration name after '::'")
    return suffix


def coloncolon_field_declaration(name: str) -> str:
    if not is_coloncolon_name(name):
        raise CompileError("unsupported '::' usage; '::' is only supported in declaration heads")
    class_name, field_name = (part.strip() for part in name.split("::", 1))
    param_name = lower_head(class_name)
    return f"{field_name}: {param_name} => {field_name}'"


def coloncolon_field_marker(name: str) -> str:
    if not is_bare_coloncolon_field_shorthand(name):
        raise CompileError("unsupported '::' usage; bare class-field shorthand requires ordinary symbol names")
    class_name, field_name = (part.strip() for part in name.split("::", 1))
    return f"{CLASS_FIELD_MARKER}({class_name}, {field_name})"


def lower_head(name: str) -> str:
    return name[:1].lower() + name[1:]


def is_bare_coloncolon_field_shorthand(name: str) -> bool:
    if name.count("::") != 1:
        return False
    prefix, suffix = (part.strip() for part in name.split("::", 1))
    return bool(prefix and suffix and is_plain_sym(prefix) and is_plain_sym(suffix))


def is_class_field_marker(text: str) -> bool:
    return parse_class_field_marker(text) is not None


def parse_class_field_marker(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped.startswith(CLASS_FIELD_MARKER + "(") or not stripped.endswith(")"):
        return None
    inner = stripped[len(CLASS_FIELD_MARKER) + 1 : -1]
    terms = parse_signature_terms(inner)
    if len(terms) != 2 or not all(is_plain_sym(term) for term in terms):
        return None
    return terms[0], terms[1]


def is_coloncolon_name(name: str) -> bool:
    if name.count("::") != 1:
        return False
    prefix, suffix = (part.strip() for part in name.split("::", 1))
    return bool(prefix and suffix and is_plain_sym(prefix) and is_declaration_head_name(suffix))


def is_declaration_head_name(name: str) -> bool:
    if is_plain_sym(name):
        return True
    return bool(re.fullmatch(r"[^\s:(),{}]+", name))


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
    if re.match(r"^.+?\s*->\s*.+$", rest):
        raise CompileError("function-assign '->' is not supported; use '=>' with an indented function body")
    match = re.match(r"^(?P<inputs>.+?)\s*(?P<arrow>=>)\s*(?P<outputs>.+)$", rest)
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


def parse_premise_declaration(text: str) -> tuple[str, list[str], list[str], str] | None:
    stripped = text.strip()
    if not stripped.startswith("|") or stripped.startswith("|-"):
        return None
    return parse_declaration(stripped[1:].strip())


def declaration_kind_fact(name: str, outputs: list[str]) -> str:
    classifier = "Predicate" if outputs == ["bool"] else "Function"
    return f"{classifier} ~ {name}"


def premise_artifact(text: str) -> str:
    return "| " + text


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
    text = lower_compound_member_calls(text)
    pattern = re.compile(r"(?<![\w'^])(?P<recv>\^?[A-Za-z_][A-Za-z0-9_']*)\.(?P<name>[A-Za-z_][A-Za-z0-9_']*)(?:\((?P<args>[^()]*)\))?")

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


def lower_compound_member_calls(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = lower_one_compound_member_call(current)
    return current


def lower_one_compound_member_call(text: str) -> str:
    index = 0
    while index < len(text):
        if text[index] != ".":
            index += 1
            continue
        name_start = index + 1
        name_end = scan_identifier(text, name_start)
        if name_end is None:
            index += 1
            continue
        args_start = name_end
        args = None
        args_end = name_end
        if args_start < len(text) and text[args_start] == "(":
            close = find_matching(text, args_start, "(", ")")
            args = text[args_start + 1 : close].strip()
            args_end = close + 1
        recv_start = compound_member_receiver_start(text, index)
        if recv_start is None:
            index += 1
            continue
        receiver = text[recv_start:index].strip()
        if is_simple_member_receiver(receiver):
            index += 1
            continue
        name = text[name_start:name_end]
        if args is None or not args:
            replacement = f"{name}({receiver})"
        else:
            replacement = f"{name}({receiver}, {args})"
        return text[:recv_start] + replacement + text[args_end:]
    return text


def compound_member_receiver_start(text: str, dot_index: int) -> int | None:
    end = dot_index
    while end > 0 and text[end - 1].isspace():
        end -= 1
    if end <= 0:
        return None
    close_char = text[end - 1]
    pairs = {")": "(", "]": "[", "}": "{"}
    if close_char in pairs:
        start = find_matching_open(text, end - 1, pairs[close_char], close_char)
        if start is None:
            return None
        prefix_start = start - 1
        while prefix_start >= 0 and is_member_receiver_char(text[prefix_start]):
            prefix_start -= 1
        return prefix_start + 1
    start = end - 1
    while start >= 0 and is_member_receiver_char(text[start]):
        start -= 1
    return start + 1


def find_matching_open(text: str, close_index: int, open_char: str, close_char: str) -> int | None:
    depth = 0
    index = close_index
    while index >= 0:
        char = text[index]
        if is_literal_quote_start(text, index):
            quote_start = literal_quote_index(text[: index + 1])
            if quote_start is not None:
                index = quote_start - 1
                continue
        if char == close_char:
            depth += 1
        elif char == open_char:
            depth -= 1
            if depth == 0:
                return index
        index -= 1
    return None


def is_simple_member_receiver(text: str) -> bool:
    return re.fullmatch(r"\^?[A-Za-z_][A-Za-z0-9_']*", text) is not None


def is_member_receiver_char(char: str) -> bool:
    return char.isalnum() or char in {"_", "'", GENERATED_SYM_PREFIX}


def scan_identifier(text: str, start: int) -> int | None:
    if start >= len(text) or not re.match(r"[A-Za-z_]", text[start]):
        return None
    index = start + 1
    while index < len(text) and re.match(r"[A-Za-z0-9_']", text[index]):
        index += 1
    return index
