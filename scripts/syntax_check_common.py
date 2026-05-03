#!/usr/bin/env python3
"""Shared syntax analysis helpers for logic-language checkers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from compile_module import (
    BASIC_ESCAPES,
    IMPORT_RE,
    LATEX_CODE_RE,
    CompileError,
    brace_delta,
    call_text,
    collect_indented_block,
    dedupe,
    find_matching,
    find_quoted_literal_end,
    has_top_level,
    is_literal_quote_start,
    is_plain_sym,
    is_raw_string_literal_start,
    literal_quote_index,
    load_tokens,
    parse_declaration,
    remove_comments,
    split_indent,
    split_top_level,
    strip_outer_blank_lines,
    tuple_or_single,
)


STDIN_FILE = "__stdin__"
QUANTIFIERS = {"∀", "∃"}


class CheckError(CompileError):
    """Raised when shared checker syntax analysis cannot continue."""


@dataclass(frozen=True)
class SourcePosition:
    file: str
    line: int
    column: int
    import_origin: bool = False


@dataclass(frozen=True)
class Binder:
    text: str
    position: SourcePosition


@dataclass
class CheckStatement:
    text: str
    sub_modules: list["CheckModule"] = field(default_factory=list)


@dataclass
class CheckModule:
    type: str
    binders: list[Binder]
    predicate_statements: list[CheckStatement]
    target_statements: list[CheckStatement]
    quantifier: str | None = None


@dataclass(frozen=True)
class Declaration:
    name: str
    position: SourcePosition


@dataclass
class CheckResult:
    file: str
    source_text: str
    expanded_text: str
    ast: CheckModule
    import_declarations: list[Declaration]


@dataclass(frozen=True)
class LocatedText:
    text: str
    positions: tuple[SourcePosition, ...]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.positions):
            raise ValueError("located text position length mismatch")

    def __bool__(self) -> bool:
        return bool(self.text)

    def slice(self, start: int, end: int | None = None) -> "LocatedText":
        return LocatedText(self.text[start:end], self.positions[start:end])

    def strip(self) -> "LocatedText":
        start = 0
        end = len(self.text)
        while start < end and self.text[start].isspace():
            start += 1
        while end > start and self.text[end - 1].isspace():
            end -= 1
        return self.slice(start, end)

    def lstrip(self, chars: str | None = None) -> "LocatedText":
        start = 0
        while start < len(self.text) and self.text[start].lstrip(chars) == "":
            start += 1
        return self.slice(start)

    def rstrip(self) -> "LocatedText":
        end = len(self.text)
        while end > 0 and self.text[end - 1].isspace():
            end -= 1
        return self.slice(0, end)


def analyze_module_text(source_text: str, *, file_path: Path | None = None) -> CheckResult:
    source_file = str(file_path.resolve()) if file_path is not None else STDIN_FILE
    root = make_located_text(source_text, source_file, import_origin=False)
    root = strip_leading_bom(root)
    tokens = load_tokens()
    normalized = normalize_latex_located(root, tokens)
    if file_path is None and has_import(normalized.text):
        raise CheckError("$import is not supported when semantic_check reads module text from stdin")

    expanded = expand_for_checking(normalized, base_dir=file_path.parent if file_path else Path.cwd(), seen=set())
    import_declarations = collect_import_declarations(expanded)
    cleaned = strip_outer_blank_lines_located(remove_comments_located(expanded))
    if not cleaned.text.strip():
        raise CheckError("empty module text")
    ast = LocatedModuleParser().parse_module(cleaned, default_quantifier="∀")
    return CheckResult(
        file=source_file,
        source_text=source_text,
        expanded_text=expanded.text,
        ast=ast,
        import_declarations=import_declarations,
    )


def analyze_module_file(file_path: Path) -> CheckResult:
    absolute = file_path.resolve()
    return analyze_module_text(absolute.read_text(encoding="utf-8"), file_path=absolute)


def collect_import_declarations(expanded: LocatedText) -> list[Declaration]:
    return collect_top_level_declarations(expanded, import_origin_only=True)


def make_located_text(text: str, file_name: str, *, import_origin: bool) -> LocatedText:
    positions: list[SourcePosition] = []
    line = 1
    column = 1
    for char in text:
        positions.append(SourcePosition(file_name, line, column, import_origin))
        if char == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return LocatedText(text, tuple(positions))


def strip_leading_bom(located: LocatedText) -> LocatedText:
    if located.text.startswith("\ufeff"):
        return located.slice(1)
    return located


def synthetic_text(text: str, origin: SourcePosition) -> LocatedText:
    return LocatedText(text, tuple(origin for _ in text))


def concat_located(parts: Iterable[LocatedText]) -> LocatedText:
    texts: list[str] = []
    positions: list[SourcePosition] = []
    for part in parts:
        texts.append(part.text)
        positions.extend(part.positions)
    return LocatedText("".join(texts), tuple(positions))


def normalize_latex_located(located: LocatedText, tokens: dict[str, str]) -> LocatedText:
    output: list[LocatedText] = []
    keys = sorted(tokens, key=len, reverse=True)
    index = 0
    while index < len(located.text):
        if is_literal_quote_start(located.text, index):
            end = find_quoted_literal_end(located.text, index)
            output.append(normalize_literal_latex_located(located.slice(index, end + 1), tokens, keys))
            index = end + 1
            continue
        if located.text[index] == "#":
            end = located.text.find("\n", index)
            if end == -1:
                output.append(located.slice(index))
                break
            output.append(located.slice(index, end))
            index = end
            continue
        matched_key = next((key for key in keys if located.text.startswith(key, index)), None)
        if matched_key is not None:
            output.append(synthetic_text(tokens[matched_key], located.positions[index]))
            index += len(matched_key)
            continue
        if located.text[index] == "\\":
            match = LATEX_CODE_RE.match(located.text, index)
            if match is not None:
                position = located.positions[index]
                raise CheckError(f"{position.file}:{position.line}:{position.column}: unknown latex code {match.group(0)}")
        output.append(located.slice(index, index + 1))
        index += 1
    return concat_located(output)


def normalize_literal_latex_located(located: LocatedText, tokens: dict[str, str], keys: list[str]) -> LocatedText:
    if is_raw_string_literal_start(located.text, 0):
        return located
    quote_index = literal_quote_index(located.text, 0)
    if quote_index is None:
        return located
    output: list[LocatedText] = [located.slice(0, quote_index + 1)]
    index = quote_index + 1
    end = len(located.text) - 1
    while index < end:
        if located.text[index] == "\\":
            escape = located.text[index + 1] if index + 1 < end else ""
            if escape in BASIC_ESCAPES:
                output.append(located.slice(index, index + 2))
                index += 2
                continue
            matched_key = next((key for key in keys if located.text.startswith(key, index)), None)
            if matched_key is not None:
                output.append(synthetic_text(tokens[matched_key], located.positions[index]))
                index += len(matched_key)
                continue
            match = LATEX_CODE_RE.match(located.text, index)
            if match is not None:
                output.append(located.slice(index, match.end()))
                index = match.end()
                continue
        output.append(located.slice(index, index + 1))
        index += 1
    output.append(located.slice(end, end + 1))
    return concat_located(output)


def has_import(text: str) -> bool:
    return any(IMPORT_RE.match(line) for line in text.splitlines())


def expand_for_checking(located: LocatedText, *, base_dir: Path, seen: set[Path]) -> LocatedText:
    lines = split_lines_located(located)
    output: list[LocatedText] = []
    tokens = load_tokens()
    for line in lines:
        line_without_newline = line.slice(0, -1) if line.text.endswith("\n") else line
        match = IMPORT_RE.match(line_without_newline.text)
        if match is None:
            output.append(line)
            continue
        import_path = resolve_import_path(match.group("path"), base_dir)
        if import_path in seen:
            raise CheckError(f"cyclic import: {import_path}")
        if not import_path.exists():
            raise CheckError(f"import not found: {import_path}")
        imported = strip_leading_bom(make_located_text(import_path.read_text(encoding="utf-8"), str(import_path), import_origin=True))
        imported = normalize_latex_located(imported, tokens)
        imported = expand_for_checking(imported, base_dir=import_path.parent, seen=seen | {import_path})
        indent = match.group("indent")
        if indent:
            imported = indent_located(imported, line.positions[0], indent)
        output.append(imported)
        if line.text.endswith("\n") and (not output[-1].text.endswith("\n")):
            output.append(synthetic_text("\n", line.positions[-1]))
    return concat_located(output)


def resolve_import_path(raw_path: str, base_dir: Path) -> Path:
    import_path = Path(raw_path.strip().strip("\"'"))
    if not import_path.is_absolute():
        import_path = base_dir / import_path
    return import_path.resolve()


def indent_located(located: LocatedText, origin: SourcePosition, indent: str) -> LocatedText:
    lines = split_lines_located(located)
    output: list[LocatedText] = []
    for line in lines:
        if line.text.strip():
            output.append(synthetic_text(indent, origin))
        output.append(line)
    return concat_located(output)


def split_lines_located(located: LocatedText) -> list[LocatedText]:
    lines: list[LocatedText] = []
    start = 0
    for index, char in enumerate(located.text):
        if char == "\n":
            lines.append(located.slice(start, index + 1))
            start = index + 1
    if start < len(located.text):
        lines.append(located.slice(start))
    return lines


def remove_comments_located(located: LocatedText) -> LocatedText:
    lines: list[LocatedText] = []
    for line in split_lines_located(located):
        text = line.text.rstrip("\n")
        stripped = remove_comments(text).rstrip()
        lines.append(line.slice(0, len(stripped)))
        if line.text.endswith("\n"):
            newline_pos = line.positions[-1]
            lines.append(synthetic_text("\n", newline_pos))
    return concat_located(lines)


def strip_outer_blank_lines_located(located: LocatedText) -> LocatedText:
    lines = split_lines_located(located)
    while lines and not lines[0].text.strip():
        lines.pop(0)
    while lines and not lines[-1].text.strip():
        lines.pop()
    return concat_located(lines)


def collect_top_level_declarations(located: LocatedText, *, import_origin_only: bool) -> list[Declaration]:
    declarations: list[Declaration] = []
    cleaned = remove_comments_located(located)
    for logical_line in logical_lines_for_declaration_scan(cleaned):
        indent, stripped = split_indent_located(logical_line)
        if indent != 0 or not stripped.text:
            continue
        if import_origin_only and not any(position.import_origin for position in stripped.positions):
            continue
        scan_target = import_header_located(stripped) if import_origin_only else stripped
        binders = parse_top_level_binders(scan_target)
        if binders is not None:
            declarations.extend(Declaration(binder.text, binder.position) for binder in binders)
            continue
        declarations.extend(scan_line_declarations(scan_target, import_origin_only=import_origin_only))
    return dedupe_declarations(declarations)


def import_header_located(located: LocatedText) -> LocatedText:
    lines = split_lines_located(located)
    if not lines:
        return located
    return lines[0].strip()


def logical_lines_for_declaration_scan(located: LocatedText) -> list[LocatedText]:
    try:
        return logical_lines_located(located)
    except CheckError:
        return [line.rstrip() for line in split_lines_located(located) if line.text.strip()]


def parse_top_level_binders(line: LocatedText) -> list[Binder] | None:
    stripped = line.strip()
    if stripped.text.startswith("|"):
        return parse_binder_list_located(stripped.slice(1).strip())
    return parse_binder_list_located(stripped)


def scan_line_declarations(line: LocatedText, *, import_origin_only: bool) -> list[Declaration]:
    stripped = line.strip()
    if not stripped.text or stripped.text.startswith("$import"):
        return []
    declarations: list[Declaration] = []

    declaration = parse_declaration(stripped.text)
    if declaration is not None:
        name, inputs, outputs, _ = declaration
        declarations.append(declaration_at_text(stripped, name, import_origin_only=import_origin_only))
        if not import_origin_only:
            for term in inputs + outputs:
                if is_plain_sym(term):
                    declarations.append(declaration_at_text(stripped, term, import_origin_only=import_origin_only))
        return [declaration for declaration in declarations if declaration is not None]

    for separator in ("=", "~", "::"):
        if separator in stripped.text:
            for part in split_top_level(stripped.text.replace("::", separator), separator):
                term = part.strip()
                if is_plain_sym(term):
                    declarations.append(declaration_at_text(stripped, term, import_origin_only=import_origin_only))

    if is_plain_sym(stripped.text):
        declarations.append(Declaration(stripped.text, stripped.positions[0]))
    return [declaration for declaration in declarations if declaration is not None]


def declaration_at_text(line: LocatedText, name: str, *, import_origin_only: bool) -> Declaration | None:
    match = re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", line.text)
    if match is None:
        return None
    position = line.positions[match.start()]
    if import_origin_only and not position.import_origin:
        return None
    return Declaration(name, position)


def dedupe_declarations(declarations: Iterable[Declaration]) -> list[Declaration]:
    seen: set[tuple[str, str, int, int]] = set()
    output: list[Declaration] = []
    for declaration in declarations:
        key = (declaration.name, declaration.position.file, declaration.position.line, declaration.position.column)
        if key in seen:
            continue
        seen.add(key)
        output.append(declaration)
    return output


class LocatedModuleParser:
    def __init__(self) -> None:
        self.fresh_index = 0

    def parse_module(self, located: LocatedText, default_quantifier: str = "∀") -> CheckModule:
        located = strip_outer_blank_lines_located(located).strip()
        wrapped = self.try_parse_wrapped_module(located)
        if wrapped is not None:
            return wrapped
        return self.parse_line_module(located, default_quantifier)

    def try_parse_wrapped_module(self, located: LocatedText) -> CheckModule | None:
        located = located.strip()
        quantifier: str | None = None
        body_start = 0
        if located.text.startswith(("∀", "∃")):
            quantifier = located.text[0]
            body_start = 1
        if body_start >= len(located.text) or located.text[body_start] != "{":
            return None
        close = find_matching(located.text, body_start, "{", "}")
        if close != len(located.text) - 1:
            return None
        body = located.slice(body_start + 1, close)
        if self.is_image_set_body(body.text):
            return self.parse_image_set(body)
        return self.build_module("quantifier" if quantifier else "set", quantifier, body)

    def parse_line_module(self, located: LocatedText, quantifier: str) -> CheckModule:
        lines = logical_lines_located(located)
        lowered = self.lower_line_blocks(lines)
        body = join_lines_located(lowered)
        return self.build_module("quantifier", quantifier, body)

    def lower_line_blocks(self, lines: list[LocatedText]) -> list[LocatedText]:
        output: list[LocatedText] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            indent, content = split_indent_located(line)
            if content.text in QUANTIFIERS and index + 1 < len(lines):
                block, next_index = collect_indented_block_located(lines, index + 1, indent)
                if block:
                    output.append(concat_located([content, synthetic_text("{\n", content.positions[0]), unindent_block_located(block), synthetic_text("\n}", content.positions[0])]))
                    index = next_index
                    continue
            if index + 1 < len(lines):
                block, next_index = collect_indented_block_located(lines, index + 1, indent)
                if block:
                    output.extend(self.lower_header_with_block(content, unindent_block_located(block)))
                    index = next_index
                    continue
            output.append(content)
            index += 1
        return output

    def lower_header_with_block(self, header: LocatedText, block: LocatedText) -> list[LocatedText]:
        if header.text.startswith("@"):
            return [concat_located([synthetic_text("∀{\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])])]
        if header.text.startswith("|-"):
            branch_ps = header.slice(2).strip()
            return [concat_located([synthetic_text("∀{\n| ", header.positions[0]), branch_ps, synthetic_text("\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])])]
        declaration = parse_declaration(header.text)
        if declaration is None:
            return [header, concat_located([synthetic_text("∀{\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])])]
        name, inputs, outputs, arrow = declaration
        if arrow == "->":
            call = call_text(name, inputs)
            target = f"{tuple_or_single(outputs)} = {call}"
            return [
                synthetic_text(f"{name}: {tuple_or_single(inputs)} => {tuple_or_single(outputs)}", header.positions[0]),
                concat_located([synthetic_text("∀{\n", header.positions[0]), synthetic_text(target, header.positions[0]), synthetic_text("\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])]),
            ]
        call = call_text(name, inputs)
        target = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        binder_line = located_binder_line_from_header(header, inputs + outputs)
        return [
            synthetic_text("function~" + name, header.positions[0]),
            concat_located([synthetic_text("∀{\n", header.positions[0]), binder_line, synthetic_text("\n| ", header.positions[0]), synthetic_text(target, header.positions[0]), synthetic_text("\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])]),
        ]

    def build_module(self, module_type: str, quantifier: str | None, body: LocatedText) -> CheckModule:
        sections = split_sections_located(body)
        if not sections:
            raise CheckError("module requires target statements")
        target_section = sections[-1]
        before_target = sections[:-1]
        binders: list[Binder] = []
        predicate_sections: list[LocatedText] = []
        for section in before_target:
            candidates = parse_binder_list_located(section)
            if candidates:
                binders.extend(candidates)
            else:
                predicate_sections.append(section)
        predicate_texts = split_terms_located(join_lines_located(predicate_sections))
        target_texts = split_terms_located(target_section)
        if not binders:
            binders = infer_binders(predicate_texts)
        if module_type == "set" and not binders:
            raise CheckError("set module requires non-empty syms")
        if not target_texts:
            raise CheckError("module requires non-empty target_statements")
        return CheckModule(
            type=module_type,
            quantifier=quantifier if module_type == "quantifier" else None,
            binders=binders,
            predicate_statements=[self.compile_statement(term) for term in predicate_texts],
            target_statements=[self.compile_statement(term) for term in target_texts],
        )

    def parse_image_set(self, body: LocatedText) -> CheckModule:
        source, target = split_top_level_once_located(body, "=>")
        out_origin = target.strip().positions[0] if target.strip() else source.strip().positions[0]
        out = Binder(self.fresh_sym(source.text + target.text), out_origin)
        exists_body = concat_located([source, synthetic_text(" | ", out_origin), synthetic_text(out.text + " = ", out_origin), target.strip()])
        submodule = self.build_module("quantifier", "∃", exists_body)
        return CheckModule(type="set", binders=[out], predicate_statements=[], target_statements=[CheckStatement("$module0", [submodule])])

    def compile_statement(self, located: LocatedText) -> CheckStatement:
        text, submodules = self.extract_sub_modules(located.strip())
        return CheckStatement(text.text.strip(), submodules)

    def extract_sub_modules(self, located: LocatedText) -> tuple[LocatedText, list[CheckModule]]:
        output: list[LocatedText] = []
        submodules: list[CheckModule] = []
        index = 0
        while index < len(located.text):
            start = find_next_module_start(located.text, index)
            if start is None:
                output.append(located.slice(index))
                break
            output.append(located.slice(index, start))
            module_start = start + 1 if located.text[start] in QUANTIFIERS else start
            end = find_matching(located.text, module_start, "{", "}")
            module_text = located.slice(start, end + 1)
            submodules.append(self.parse_module(module_text))
            output.append(synthetic_text(f"$module{len(submodules) - 1}", located.positions[start]))
            index = end + 1
        return concat_located(output).strip(), submodules

    def is_image_set_body(self, body: str) -> bool:
        return body.lstrip().startswith("|") and has_top_level(body, "=>")

    def fresh_sym(self, seed: str) -> str:
        while True:
            sym = f"__logic_language_out{self.fresh_index}"
            self.fresh_index += 1
            if sym not in seed:
                return sym


def logical_lines_located(located: LocatedText) -> list[LocatedText]:
    lines: list[LocatedText] = []
    pending: list[LocatedText] = []
    balance = 0
    for raw_line in split_lines_located(located):
        line = raw_line.rstrip()
        if not line.text.strip():
            continue
        pending.append(line)
        balance += brace_delta(line.text)
        if balance <= 0:
            lines.append(join_lines_located(pending))
            pending = []
            balance = 0
    if pending:
        raise CheckError("unclosed {")
    return lines


def split_indent_located(line: LocatedText) -> tuple[int, LocatedText]:
    first_line = line.text.splitlines()[0]
    indent = len(first_line) - len(first_line.lstrip(" "))
    return indent, line.strip()


def collect_indented_block_located(lines: list[LocatedText], start: int, parent_indent: int) -> tuple[list[LocatedText], int]:
    block: list[LocatedText] = []
    index = start
    while index < len(lines):
        indent, _ = split_indent_located(lines[index])
        if indent <= parent_indent:
            break
        block.append(lines[index])
        index += 1
    return block, index


def unindent_block_located(lines: Iterable[LocatedText]) -> LocatedText:
    block = list(lines)
    indents = [len(line.text) - len(line.text.lstrip(" ")) for line in block if line.text.strip()]
    trim = min(indents) if indents else 0
    return join_lines_located([line.slice(trim) for line in block])


def join_lines_located(lines: Iterable[LocatedText]) -> LocatedText:
    parts: list[LocatedText] = []
    first = True
    fallback: SourcePosition | None = None
    for line in lines:
        if not first:
            origin = fallback or (line.positions[0] if line.positions else SourcePosition(STDIN_FILE, 1, 1))
            parts.append(synthetic_text("\n", origin))
        parts.append(line)
        if line.positions:
            fallback = line.positions[-1]
        first = False
    return concat_located(parts)


def split_sections_located(body: LocatedText) -> list[LocatedText]:
    if "\n" in body.text:
        line_sections = split_multiline_sections_located(body)
        if line_sections:
            return line_sections
    sections = split_top_level_located(body, "|")
    if len(sections) == 1:
        return [section.strip() for section in sections if section.text.strip()]
    return [section.strip() for section in sections if section.text.strip()]


def split_multiline_sections_located(body: LocatedText) -> list[LocatedText]:
    sections: list[LocatedText] = []
    target_lines: list[LocatedText] = []
    section_lines: list[LocatedText] = []
    balance = 0
    for raw_line in split_lines_located(body):
        line = raw_line.strip()
        if not line.text:
            continue
        if section_lines:
            section_lines.append(line)
            balance += brace_delta(line.text)
            if balance <= 0:
                sections.append(join_lines_located(section_lines))
                section_lines = []
                balance = 0
            continue
        if balance == 0 and line.text.startswith("|"):
            if target_lines:
                sections.append(join_lines_located(target_lines))
                target_lines = []
            section = line.slice(1).strip()
            if section.text:
                balance = brace_delta(section.text)
                if balance > 0:
                    section_lines = [section]
                else:
                    sections.append(section)
        else:
            target_lines.append(line)
            balance += brace_delta(line.text)
            if balance < 0:
                balance = 0
    if section_lines:
        sections.append(join_lines_located(section_lines))
    if target_lines:
        sections.append(join_lines_located(target_lines))
    return sections


def split_terms_located(located: LocatedText) -> list[LocatedText]:
    terms: list[LocatedText] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(located.text):
        char = located.text[index]
        if is_literal_quote_start(located.text, index):
            index = find_quoted_literal_end(located.text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in {",", "\n"}:
            term = located.slice(start, index).strip()
            if term.text:
                terms.append(term)
            start = index + 1
        index += 1
    term = located.slice(start).strip()
    if term.text:
        terms.append(term)
    return terms


def split_top_level_located(located: LocatedText, separator: str) -> list[LocatedText]:
    parts: list[LocatedText] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(located.text):
        char = located.text[index]
        if is_literal_quote_start(located.text, index):
            index = find_quoted_literal_end(located.text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and located.text.startswith(separator, index):
            parts.append(located.slice(start, index))
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(located.slice(start))
    return parts


def split_top_level_once_located(located: LocatedText, separator: str) -> tuple[LocatedText, LocatedText]:
    parts = split_top_level_located(located, separator)
    if len(parts) < 2:
        raise CheckError(f"expected top-level {separator}")
    return parts[0], concat_located(parts[1:])


def parse_binder_list_located(section: LocatedText) -> list[Binder] | None:
    terms = split_terms_located(section)
    if not terms:
        return None
    binders: list[Binder] = []
    for term in terms:
        term = term.strip()
        if term.text.startswith("(") and term.text.endswith(")"):
            inner = term.slice(1, -1)
            nested = [part.strip() for part in split_top_level_located(inner, ",") if part.text.strip()]
            if not nested or not all(is_plain_sym(part.text) for part in nested):
                return None
            binders.extend(Binder(part.text, part.positions[0]) for part in nested)
        elif is_plain_sym(term.text):
            binders.append(Binder(term.text, term.positions[0]))
        else:
            return None
    return binders


def infer_binders(predicate_texts: list[LocatedText]) -> list[Binder]:
    binders: list[Binder] = []
    operators = ("=", ">", "<", ">=", "<=", "≤", "≥", "∈", "∉", "⊂", "⊄", "⊆", "⊈", "≠")
    for text in predicate_texts:
        for op in operators:
            index = text.text.find(op)
            if index >= 0:
                parsed = parse_binder_list_located(text.slice(0, index).strip())
                if parsed:
                    binders.extend(parsed)
                break
        if "~" in text.text:
            index = text.text.find("~")
            right = text.slice(index + 1).strip()
            if is_plain_sym(right.text):
                binders.append(Binder(right.text, right.positions[0]))
    return binders


def find_next_module_start(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        char = text[index]
        if char in QUANTIFIERS and index + 1 < len(text) and text[index + 1] == "{":
            return index
        if char == "{":
            return index
        index += 1
    return None


def located_binder_line_from_header(header: LocatedText, names: list[str]) -> LocatedText:
    parts = [synthetic_text("| ", header.positions[0])]
    for index, name in enumerate(names):
        if index:
            parts.append(synthetic_text(", ", header.positions[0]))
        parts.append(located_name_from_header(header, name))
    return concat_located(parts)


def located_name_from_header(header: LocatedText, name: str) -> LocatedText:
    match = re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", header.text)
    if match is None:
        return synthetic_text(name, header.positions[0])
    return header.slice(match.start(), match.end())
