#!/usr/bin/env python3
"""Recover authored declaration symbol locations for generated declaration modules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from compile_pipeline.module_sections import (
    Module,
    call_text,
    explicit_class_header_sym,
    parse_declaration,
    split_indent,
    tuple_or_single,
)


AstLoc = dict[str, Any]


@dataclass(frozen=True)
class DeclarationLoc:
    name: str
    inputs: list[str]
    outputs: list[str]
    input_locs: list[AstLoc | None]
    output_locs: list[AstLoc | None]
    module_count: int


def annotate_declaration_bound_locs(module: Module, source_text: str, source_file: str) -> None:
    declarations = collect_declaration_locs(source_text, source_file)
    if not declarations:
        return
    applicator = DeclarationLocApplicator(declarations)
    applicator.visit_module(module)


def collect_declaration_locs(source_text: str, source_file: str) -> list[DeclarationLoc]:
    declarations: list[DeclarationLoc] = []
    class_stack: list[tuple[int, str]] = []
    lines = source_text.splitlines()
    for line_index, raw_line in enumerate(lines):
        if not raw_line.strip():
            continue
        indent, content = split_indent(raw_line)
        while class_stack and indent <= class_stack[-1][0]:
            class_stack.pop()
        class_name = explicit_class_header_sym(content)
        if class_name is not None:
            class_stack.append((indent, class_name))
            continue
        declaration = source_declaration_from_line(
            raw_line,
            content,
            indent,
            class_stack,
            source_file,
            line_index,
            has_following_indented_body(lines, line_index, indent),
        )
        if declaration is not None:
            declarations.append(declaration)
    return declarations


def source_declaration_from_line(
    raw_line: str,
    content: str,
    indent: int,
    class_stack: list[tuple[int, str]],
    source_file: str,
    line_index: int,
    has_body: bool,
) -> DeclarationLoc | None:
    stripped = content.strip()
    if stripped.startswith("|-"):
        return None
    premise_prefix = re.match(r"^\|\s*", content)
    declaration_start = indent
    declaration_text = content
    if premise_prefix is not None:
        declaration_start += premise_prefix.end()
        declaration_text = content[premise_prefix.end() :]

    parse_text = declaration_text.strip()
    parse_to_source_offset = declaration_start + (len(declaration_text) - len(declaration_text.lstrip()))
    if parse_text.startswith("::") and class_stack:
        parse_text = class_stack[-1][1] + parse_text
        parse_to_source_offset -= len(class_stack[-1][1])
    parsed = parse_declaration(parse_text)
    if parsed is None:
        return None
    name, inputs, outputs, _arrow = parsed
    colon_index = declaration_colon_index(parse_text)
    arrow_match = re.search(r"=>", parse_text)
    if colon_index is None or arrow_match is None:
        return None
    inputs_text = parse_text[colon_index + 1 : arrow_match.start()]
    outputs_text = parse_text[arrow_match.end() :]
    inputs_start = parse_to_source_offset + colon_index + 1
    outputs_start = parse_to_source_offset + arrow_match.end()
    return DeclarationLoc(
        name=name,
        inputs=inputs,
        outputs=outputs,
        input_locs=locate_signature_terms(inputs_text, inputs_start, source_file, line_index, inputs),
        output_locs=locate_signature_terms(outputs_text, outputs_start, source_file, line_index, outputs),
        module_count=2 if has_body else 1,
    )


def has_following_indented_body(lines: list[str], line_index: int, indent: int) -> bool:
    for raw_line in lines[line_index + 1 :]:
        if not raw_line.strip():
            continue
        next_indent, _content = split_indent(raw_line)
        return next_indent > indent
    return False


def locate_signature_terms(text: str, source_start_col: int, source_file: str, line_index: int, terms: list[str]) -> list[AstLoc | None]:
    locs: list[AstLoc | None] = []
    search_start = 0
    for term in terms:
        sym = signature_term_symbol(term)
        match = re.search(rf"(?<![\w']){re.escape(sym)}(?![\w'])", text[search_start:])
        if match is None:
            locs.append(None)
            continue
        start = search_start + match.start()
        end = search_start + match.end()
        search_start = end
        locs.append(
            {
                "source": source_file,
                "line": line_index + 1,
                "column": source_start_col + start + 1,
                "end_line": line_index + 1,
                "end_column": source_start_col + end + 1,
            }
        )
    return locs


def signature_term_symbol(term: str) -> str:
    stripped = term.strip()
    if "~" in stripped:
        stripped = stripped.split("~", 1)[1].strip()
    return stripped


def declaration_colon_index(text: str) -> int | None:
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
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


class DeclarationLocApplicator:
    def __init__(self, declarations: list[DeclarationLoc]) -> None:
        self.declarations = declarations
        self.index = 0
        self.remaining = 0
        self.current: DeclarationLoc | None = None

    def visit_module(self, module: Module) -> None:
        declaration = self.match_current_declaration(module)
        if declaration is not None:
            module.bound_sym_locs = [*declaration.input_locs, *declaration.output_locs]
            self.remaining -= 1
            if self.remaining <= 0:
                self.current = None
                self.index += 1
        for statement in [*module.predicate_statements, *module.target_statements]:
            for submodule in statement.sub_modules:
                self.visit_module(submodule)

    def match_current_declaration(self, module: Module) -> DeclarationLoc | None:
        if self.current is not None:
            if matches_declaration_module(module, self.current):
                return self.current
            return None
        for candidate_index in range(self.index, len(self.declarations)):
            candidate = self.declarations[candidate_index]
            if matches_declaration_module(module, candidate):
                self.index = candidate_index
                self.current = candidate
                self.remaining = candidate.module_count
                return candidate
        return None


def matches_declaration_module(module: Module, declaration: DeclarationLoc) -> bool:
    if module.syms != [*declaration.inputs, *declaration.outputs]:
        return False
    expected = declaration_premise_texts(declaration)
    actual = {statement.text.strip() for statement in module.predicate_statements}
    return bool(expected & actual)


def declaration_premise_texts(declaration: DeclarationLoc) -> set[str]:
    call = call_text(declaration.name, declaration.inputs)
    if declaration.outputs == ["bool"]:
        return {call}
    return {f"{tuple_or_single(declaration.outputs)} = {call}"}
