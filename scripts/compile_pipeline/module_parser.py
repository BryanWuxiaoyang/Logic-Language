#!/usr/bin/env python3
"""Stage1-owned located parser for logic-language module text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from AST import (
    BRANCH_MODULE_MARKER,
    DECL_BODY_OUTPUT_MARKER,
    DECL_OUTPUT_MARKER,
    FRESH_PREFIX,
    GENERATED_SYM_PREFIX,
    INDENT_WIDTH,
    INDENTATION_BODY_OWNER_ERROR,
    INDENTATION_LEVEL_ERROR,
    Call_expr,
    Char_literal_expr,
    Empty_expr,
    ExprNode,
    Module,
    Module_ref_expr,
    Raw_expr,
    SourceLoc,
    Statement,
    Set_expr,
    String_literal_expr,
    SymNode,
    Sym_expr,
    Tuple_expr,
    Value_literal_expr,
    dedupe,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.source_syntax import (
    brace_delta,
    call_text,
    class_declaration_marker,
    class_declaration_from_plain_target,
    class_block_prefix_lines,
    class_header_sym,
    class_member_owner_name,
    coloncolon_field_declaration,
    erase_coloncolon_statement_head,
    explicit_class_header_sym,
    find_matching,
    has_top_level,
    infer_syms,
    is_generated_sym_name,
    is_bare_coloncolon_field_shorthand,
    is_plain_sym,
    lower_member_calls,
    lower_head,
    declaration_kind_fact,
    parse_class_field_assignment,
    premise_quantifier_header,
    parse_declaration,
    parse_premise_declaration,
    reject_unsupported_coloncolon,
    split_top_level,
    strip_outer_blank_lines,
    top_level_assignment_index,
    tuple_or_single,
)
from compile_pipeline.source_utils import (
    BASIC_ESCAPES,
    IMPORT_RE,
    LATEX_CODE_RE,
    LiteralValue,
    find_quoted_literal_end,
    is_literal_quote_start,
    is_raw_string_literal_start,
    literal_quote_index,
    load_tokens,
    parse_literal_text,
    remove_comments,
    resolve_import_path,
)


STDIN_FILE = "__stdin__"
QUANTIFIERS = {"∀", "∃"}


class CheckError(CompileError):
    """Raised when shared checker syntax analysis cannot continue."""

    def __init__(self, message: str, *, position: SourcePosition | None = None, width: int = 1) -> None:
        super().__init__(message)
        self.position = position
        self.width = max(width, 1)


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
    located: LocatedText | None = None


@dataclass(frozen=True)
class CheckDeclaration:
    kind: str
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


@dataclass
class CheckModule:
    type: str
    binders: list[Binder]
    predicate_statements: list[CheckStatement]
    target_statements: list[CheckStatement]
    quantifier: str | None = None
    class_declarations: list[Declaration] = field(default_factory=list)
    premise_binding_statements: list[CheckStatement] = field(default_factory=list)
    declaration: CheckDeclaration | None = None
    suppress_inferred_syms: bool = False


@dataclass(frozen=True)
class Declaration:
    name: str
    position: SourcePosition


@dataclass(frozen=True)
class ClassMemberOwner:
    name: str
    position: SourcePosition
    declared: bool


@dataclass
class CheckResult:
    file: str
    source_text: str
    expanded_text: str
    ast: CheckModule
    import_declarations: list[Declaration]
    import_class_declarations: list[Declaration] = field(default_factory=list)
    class_member_owners: list[ClassMemberOwner] = field(default_factory=list)


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


def first_position(located: LocatedText) -> SourcePosition | None:
    stripped = located.strip()
    if stripped.positions:
        return stripped.positions[0]
    if located.positions:
        return located.positions[0]
    return None


def raise_located_error(message: str, located: LocatedText | SourcePosition, *, width: int = 1) -> None:
    position = located if isinstance(located, SourcePosition) else first_position(located)
    raise CheckError(message, position=position, width=width)


def raise_located_token_error(message: str, located: LocatedText, token: str | None = None) -> None:
    position = first_position(located)
    width = 1
    if token:
        index = located.text.find(token)
        if index >= 0 and index < len(located.positions):
            position = located.positions[index]
            width = len(token)
    raise CheckError(message, position=position, width=width)


def raise_compile_error_located(error: CompileError, located: LocatedText) -> None:
    message = str(error)
    token = token_for_compile_error(message, located.text)
    raise_located_token_error(message, located, token)


def token_for_compile_error(message: str, text: str) -> str | None:
    if "unsupported '::' usage" in message:
        return "::"
    if "bare class-field shorthand" in message or "missing declaration name after '::'" in message:
        return "::"
    if message.startswith("function-assign '->'"):
        return "->"
    if message == "branch header requires an indented block":
        return "|-"
    if "invalid escape sequence " in message:
        escape = message.rsplit(" ", 1)[-1]
        if escape in text:
            return escape
    if message.startswith("char literal") or message.startswith("invalid literal"):
        quote_index = next((index for index, char in enumerate(text) if char in {"'", '"'}), -1)
        if quote_index >= 0:
            return text[quote_index]
    if message == "literal cannot appear on assignment left-hand side":
        quote_index = next((index for index, char in enumerate(text) if char in {"'", '"'}), -1)
        if quote_index >= 0:
            return text[quote_index]
    if message.startswith("set module requires") and "{" in text:
        return "{"
    if message.startswith("class declaration requires a capital-head symbol: "):
        fragment = message.split(": ", 1)[1].strip()
        if fragment in text:
            return fragment
    return None


def analyze_module_text(
    source_text: str,
    *,
    file_path: Path | None = None,
    base_dir: Path | None = None,
    source_label: str | None = None,
) -> CheckResult:
    source_file = source_label or (str(file_path.resolve()) if file_path is not None else STDIN_FILE)
    root = make_located_text(source_text, source_file, import_origin=False)
    root = strip_leading_bom(root)
    tokens = load_tokens()
    normalized = normalize_latex_located(root, tokens)

    import_base_dir = base_dir or (file_path.parent if file_path else Path.cwd())
    expanded = expand_for_checking(normalized, base_dir=import_base_dir, seen=set())
    import_declarations = collect_import_declarations(expanded)
    import_class_declarations = collect_import_class_declarations(expanded)
    import_class_names = {declaration.name for declaration in import_class_declarations}
    cleaned = strip_outer_blank_lines_located(remove_comments_located(expanded))
    if not cleaned.text.strip():
        raise CheckError("empty module text")
    parser = LocatedModuleParser(visible_class_names=import_class_names)
    ast = parser.parse_module(cleaned, default_quantifier="∀")
    return CheckResult(
        file=source_file,
        source_text=source_text,
        expanded_text=expanded.text,
        ast=ast,
        import_declarations=import_declarations,
        import_class_declarations=import_class_declarations,
        class_member_owners=parser.class_member_owners,
    )


def analyze_module_file(file_path: Path) -> CheckResult:
    absolute = file_path.resolve()
    return analyze_module_text(absolute.read_text(encoding="utf-8"), file_path=absolute)


def collect_import_declarations(expanded: LocatedText) -> list[Declaration]:
    return collect_top_level_declarations(expanded, import_origin_only=True)


def collect_import_class_declarations(expanded: LocatedText) -> list[Declaration]:
    return collect_top_level_class_declarations(expanded, import_origin_only=True)


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


def prefix_premise_located(header: LocatedText, artifact: LocatedText) -> LocatedText:
    origin = header.positions[0]
    return concat_located([synthetic_text("| ", origin), artifact])


def concat_located(parts: Iterable[LocatedText]) -> LocatedText:
    texts: list[str] = []
    positions: list[SourcePosition] = []
    for part in parts:
        texts.append(part.text)
        positions.extend(part.positions)
    return LocatedText("".join(texts), tuple(positions))


def located_key(located: LocatedText) -> tuple[str, SourcePosition | None]:
    return (located.text, located.positions[0] if located.positions else None)


def generated_declaration_binding_text(declaration: CheckDeclaration) -> str:
    call = call_text(declaration.name, list(declaration.inputs))
    if declaration.outputs == ("bool",):
        return call
    return f"{tuple_or_single(list(declaration.outputs))} = {call}"


def is_declaration_marker_text(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(DECL_OUTPUT_MARKER + "(") and stripped.endswith(")")


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


def expand_for_checking(
    located: LocatedText,
    *,
    base_dir: Path,
    seen: set[Path],
    expanded: set[Path] | None = None,
) -> LocatedText:
    expanded = set() if expanded is None else expanded
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
        if import_path in expanded:
            continue
        if not import_path.exists():
            raise CheckError(f"import not found: {import_path}")
        expanded.add(import_path)
        imported = strip_leading_bom(make_located_text(import_path.read_text(encoding="utf-8"), str(import_path), import_origin=True))
        imported = normalize_latex_located(imported, tokens)
        imported = expand_for_checking(imported, base_dir=import_path.parent, seen=seen | {import_path}, expanded=expanded)
        indent = match.group("indent")
        if indent:
            imported = indent_located(imported, line.positions[0], indent)
        output.append(imported)
        if line.text.endswith("\n") and (not output[-1].text.endswith("\n")):
            output.append(synthetic_text("\n", line.positions[-1]))
    return concat_located(output)


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


def collect_top_level_class_declarations(located: LocatedText, *, import_origin_only: bool) -> list[Declaration]:
    declarations: list[Declaration] = []
    cleaned = remove_comments_located(located)
    for logical_line in logical_lines_for_declaration_scan(cleaned):
        indent, stripped = split_indent_located(logical_line)
        if indent != 0 or not stripped.text:
            continue
        class_name = explicit_class_header_sym(stripped.text)
        if class_name is None:
            continue
        declaration = declaration_at_text(stripped, class_name, import_origin_only=import_origin_only)
        if declaration is not None:
            declarations.append(declaration)
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
    return None


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

    for separator in ("=", "::"):
        if separator in stripped.text:
            for part in split_top_level(stripped.text.replace("::", separator), separator):
                term = part.strip()
                if is_plain_sym(term):
                    declarations.append(declaration_at_text(stripped, term, import_origin_only=import_origin_only))

    if explicit_class_header_sym(stripped.text) is not None:
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
    def __init__(self, *, visible_class_names: Iterable[str] = ()) -> None:
        self.fresh_index = 0
        self.declarations_by_module: dict[tuple[str, SourcePosition | None], CheckDeclaration] = {}
        self.class_member_owners: list[ClassMemberOwner] = []
        self.visible_class_names = set(visible_class_names)

    def parse_module(self, located: LocatedText, default_quantifier: str = "∀") -> CheckModule:
        located = strip_outer_blank_lines_located(located).strip()
        wrapped = self.try_parse_wrapped_module(located)
        if wrapped is not None:
            return wrapped
        return self.parse_line_module(located, default_quantifier)

    def try_parse_wrapped_module(self, located: LocatedText) -> CheckModule | None:
        located = located.strip()
        declaration = self.declarations_by_module.get(located_key(located))
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
        return self.build_module(
            "quantifier" if quantifier else "set",
            quantifier,
            body,
            declaration=declaration,
            error_position=located.positions[body_start],
        )

    def parse_line_module(self, located: LocatedText, quantifier: str) -> CheckModule:
        lines = logical_lines_located(located)
        lowered = self.lower_line_blocks(lines)
        body = join_lines_located(lowered)
        return self.build_module("quantifier", quantifier, body)

    def lower_line_blocks(self, lines: list[LocatedText], *, visible_class_names: Iterable[str] | None = None) -> list[LocatedText]:
        validate_indentation_levels_located(lines)
        output: list[LocatedText] = []
        visible_classes = set(visible_class_names or self.visible_class_names) | direct_class_header_names_located(lines)
        index = 0
        while index < len(lines):
            line = lines[index]
            indent, content = split_indent_located(line)
            if content.text.startswith("@"):
                content = synthetic_text("∀", content.positions[0])
            self.record_class_member_owner(content, visible_classes)
            class_field_assignment = parse_class_field_assignment_located(content)
            if index + 1 < len(lines):
                block, _ = collect_indented_block_located(lines, index + 1, indent)
                if block and (is_bare_coloncolon_field_shorthand(content.text) or class_field_assignment is not None):
                    raise_located_error(
                        "class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration",
                        content,
                        width=2,
                    )
            if class_field_assignment is not None:
                assignment, rhs = class_field_assignment
                output.extend(self.lower_class_field_assignment(content, assignment, rhs))
                index += 1
                continue
            content = erase_coloncolon_statement_head_located(content)
            if content.text in QUANTIFIERS and index + 1 < len(lines):
                block, next_index = collect_indented_block_located(lines, index + 1, indent)
                if block:
                    output.append(
                        concat_located(
                            [
                                content,
                                synthetic_text("{\n", content.positions[0]),
                                self.lower_nested_block(unindent_block_located(block), visible_classes),
                                synthetic_text("\n}", content.positions[0]),
                            ]
                        )
                    )
                    index = next_index
                    continue
            premise_quantifier = premise_quantifier_header(content.text)
            if premise_quantifier is not None and index + 1 < len(lines):
                block, next_index = collect_indented_block_located(lines, index + 1, indent)
                if block:
                    output.append(
                        concat_located(
                            [
                                synthetic_text("| " + premise_quantifier + "{\n", content.positions[0]),
                                self.lower_nested_block(unindent_block_located(block), visible_classes),
                                synthetic_text("\n}", content.positions[0]),
                            ]
                        )
                    )
                    index = next_index
                    continue
            if index + 1 < len(lines):
                block, next_index = collect_indented_block_located(lines, index + 1, indent)
                if block:
                    premise_declaration = parse_premise_declaration(content.text)
                    if premise_declaration is not None:
                        output.extend(
                            self.lower_premise_declaration(
                                content,
                                premise_declaration,
                                block=self.lower_nested_block(unindent_block_located(block), visible_classes),
                            )
                        )
                        index = next_index
                        continue
                    output.extend(self.lower_header_with_block(content, unindent_block_located(block), visible_classes))
                    index = next_index
                    continue
            if content.text.startswith("|-"):
                raise_located_error("branch header requires an indented block", content, width=2)
            premise_declaration = parse_premise_declaration(content.text)
            if premise_declaration is not None:
                output.extend(self.lower_premise_declaration(content, premise_declaration, block=None))
                index += 1
                continue
            declaration = parse_declaration(content.text)
            if declaration is not None:
                output.extend(self.lower_declaration(content, declaration, block=None))
            else:
                reject_unsupported_coloncolon_located(content)
                output.append(content)
            index += 1
        return output

    def record_class_member_owner(self, content: LocatedText, visible_classes: set[str]) -> None:
        class_name = class_member_owner_name(content.text)
        if class_name is None or not content.positions:
            return
        index = content.text.find(class_name)
        position = content.positions[index] if 0 <= index < len(content.positions) else content.positions[0]
        self.class_member_owners.append(ClassMemberOwner(class_name, position, class_name in visible_classes))

    def lower_header_with_block(self, header: LocatedText, block: LocatedText, visible_classes: set[str]) -> list[LocatedText]:
        if header.text.startswith("@"):
            return [concat_located([synthetic_text("∀{\n", header.positions[0]), block, synthetic_text("\n}", header.positions[0])])]
        if header.text.startswith("|-"):
            branch_ps = header.slice(2).strip()
            branch_premise_parts = [] if branch_ps.text == "else" else [synthetic_text("\n| ", header.positions[0]), branch_ps]
            return [
                concat_located(
                    [
                        synthetic_text("∀{\n| ", header.positions[0]),
                        synthetic_text(BRANCH_MODULE_MARKER, header.positions[0]),
                        *branch_premise_parts,
                        synthetic_text("\n", header.positions[0]),
                        self.lower_nested_block(block, visible_classes),
                        synthetic_text("\n}", header.positions[0]),
                    ]
                )
            ]
        class_sym = class_header_sym(header.text)
        if class_sym is not None:
            return self.lower_class_block(header, class_sym, block, visible_classes)
        declaration = parse_declaration(header.text)
        if declaration is None:
            reject_unsupported_coloncolon_located(header)
            raise_located_error(INDENTATION_BODY_OWNER_ERROR, header)
        return self.lower_declaration(header, declaration, block=self.lower_nested_block(block, visible_classes))

    def lower_declaration(
        self,
        header: LocatedText,
        declaration: tuple[str, list[str], list[str], str],
        *,
        block: LocatedText | None,
    ) -> list[LocatedText]:
        name, inputs, outputs, arrow = declaration
        origin = header.positions[0]
        if arrow != "=>":
            raise_located_token_error("function-assign '->' is not supported; use '=>' with an indented function body", header, "->")
        module_text = self.declaration_module_located(header, name, inputs, outputs)
        declaration_info = CheckDeclaration(
            kind="predicate" if outputs == ["bool"] else "function",
            name=name,
            inputs=tuple(inputs),
            outputs=tuple(outputs),
        )
        self.declarations_by_module[located_key(module_text)] = declaration_info
        classifier = "Predicate" if outputs == ["bool"] else "Function"
        output = [
            concat_located(
                [
                    synthetic_text(classifier + " ~ ", origin),
                    located_name_from_header(header, name),
                ]
            ),
            module_text,
        ]
        if block is not None:
            body_text = self.function_body_module_located(header, name, inputs, outputs, block)
            self.declarations_by_module[located_key(body_text)] = declaration_info
            output.append(body_text)
        return output

    def lower_premise_declaration(
        self,
        header: LocatedText,
        declaration: tuple[str, list[str], list[str], str],
        *,
        block: LocatedText | None,
    ) -> list[LocatedText]:
        return [prefix_premise_located(header, artifact) for artifact in self.lower_declaration(header.slice(1).strip(), declaration, block=block)]

    def lower_class_field_assignment(
        self,
        header: LocatedText,
        assignment,
        rhs: LocatedText,
    ) -> list[LocatedText]:
        origin = header.positions[0]
        field_header = synthetic_text(
            coloncolon_field_declaration(f"{assignment.class_name}::{assignment.field_name}"),
            origin,
        )
        declaration = parse_declaration(field_header.text)
        if declaration is None:
            raise_located_error("unsupported '::' usage; bare class-field shorthand requires ordinary symbol names", header, width=2)
        artifacts = [
            *self.lower_declaration(field_header, declaration, block=None),
            class_field_assignment_module_located(header, assignment, rhs),
        ]
        if assignment.premise:
            return [prefix_premise_located(header, artifact) for artifact in artifacts]
        return artifacts

    def declaration_module_located(self, header: LocatedText, name: str, inputs: list[str], outputs: list[str]) -> LocatedText:
        origin = header.positions[0]
        call = call_text(name, inputs)
        binding = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        marker = f"{DECL_OUTPUT_MARKER}({', '.join(outputs)})"
        binder_line = located_binder_line_from_header(header, inputs + outputs)
        body_parts = [
            synthetic_text("∀{\n", origin),
            binder_line,
            synthetic_text("\n| ", origin),
            synthetic_text(marker, origin),
            synthetic_text("\n| ", origin),
            synthetic_text(binding, origin),
            synthetic_text("\n", origin),
            synthetic_text(marker, origin),
        ]
        body_parts.append(synthetic_text("\n}", origin))
        return concat_located(body_parts)

    def function_body_module_located(
        self,
        header: LocatedText,
        name: str,
        inputs: list[str],
        outputs: list[str],
        block: LocatedText,
    ) -> LocatedText:
        origin = header.positions[0]
        call = call_text(name, inputs)
        binding = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        binder_line = located_binder_line_from_header(header, inputs + outputs)
        return concat_located(
            [
                synthetic_text("∀{\n", origin),
                binder_line,
                synthetic_text("\n| ", origin),
                synthetic_text(binding, origin),
                synthetic_text("\n", origin),
                block,
                synthetic_text("\n}", origin),
            ]
        )

    def lower_class_block(self, header: LocatedText, class_sym: str, block: LocatedText, visible_classes: Iterable[str]) -> list[LocatedText]:
        expanded_lines = class_block_prefix_lines_located(header, class_sym)
        body_lines = logical_lines_located(block)
        index = 0
        while index < len(body_lines):
            line = body_lines[index]
            indent, content = split_indent_located(line)
            if indent != 0 or not content.text.startswith("::"):
                raise_located_error("class-declaration body line must start with '::'", content)
            if content.text.startswith(":::") or content.text.strip() == "::":
                raise_located_error("class-declaration body line must start with '::' followed by a declaration", content)
            expanded_lines.append(concat_located([synthetic_text(class_sym, content.positions[0]), content]))
            nested, next_index = collect_indented_block_located(body_lines, index + 1, indent)
            expanded_lines.extend(nested)
            index = next_index
        return self.lower_line_blocks(expanded_lines, visible_class_names={*visible_classes, class_sym})

    def lower_nested_block(self, block: LocatedText, visible_class_names: Iterable[str] | None = None) -> LocatedText:
        return join_lines_located(self.lower_line_blocks(logical_lines_located(block), visible_class_names=visible_class_names))

    def build_module(
        self,
        module_type: str,
        quantifier: str | None,
        body: LocatedText,
        *,
        declaration: CheckDeclaration | None = None,
        error_position: SourcePosition | None = None,
    ) -> CheckModule:
        body, class_declarations = extract_class_declarations_from_body_located(body)
        sections = split_sections_located(body)
        if not sections:
            if module_type == "set":
                raise CheckError("set module requires non-empty syms", position=error_position or first_position(body))
            return CheckModule(
                type=module_type,
                binders=[],
                predicate_statements=[],
                target_statements=[],
                quantifier=quantifier if module_type == "quantifier" else None,
                declaration=declaration,
                class_declarations=class_declarations,
            )
        target_section = sections[-1]
        before_target = sections[:-1]
        binders: list[Binder] = []
        predicate_sections: list[LocatedText] = []
        suppress_inferred_syms = False
        for section in before_target:
            if section.text == BRANCH_MODULE_MARKER:
                suppress_inferred_syms = True
                continue
            candidates = parse_binder_list_located(section)
            if candidates:
                binders.extend(candidates)
            else:
                predicate_sections.append(section)
        predicate_texts = split_terms_located(join_lines_located(predicate_sections))
        suppress_inferred_syms = suppress_inferred_syms or any(text.text == BRANCH_MODULE_MARKER for text in predicate_texts)
        predicate_texts = [text for text in predicate_texts if text.text != BRANCH_MODULE_MARKER]
        predicate_texts = [text for text in predicate_texts if not is_declaration_marker_text(text.text)]
        target_texts: list[LocatedText] = []
        for text in split_terms_located(target_section):
            if is_declaration_marker_text(text.text):
                continue
            class_declaration = class_declaration_from_plain_target_located(text)
            if class_declaration is not None:
                class_declarations.append(class_declaration)
                continue
            target_texts.append(text)
        if not binders and not suppress_inferred_syms:
            binders = infer_binders(predicate_texts)
        if module_type == "set" and not binders:
            raise CheckError("set module requires non-empty syms", position=error_position or first_position(body))
        if module_type == "set" and not target_texts and declaration is None:
            raise CheckError("module requires non-empty target_statements", position=error_position or first_position(target_section))
        predicate_statements = [self.compile_statement(term) for term in predicate_texts]
        premise_binding_statements: list[CheckStatement] = []
        if declaration is not None and predicate_statements:
            generated_binding = generated_declaration_binding_text(declaration)
            if predicate_statements[0].text == generated_binding:
                premise_binding_statements.append(predicate_statements.pop(0))
        return CheckModule(
            type=module_type,
            quantifier=quantifier if module_type == "quantifier" else None,
            binders=binders,
            predicate_statements=predicate_statements,
            target_statements=[self.compile_statement(term) for term in target_texts],
            class_declarations=dedupe_declarations(class_declarations),
            premise_binding_statements=premise_binding_statements,
            declaration=declaration,
            suppress_inferred_syms=suppress_inferred_syms,
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
        reject_unsupported_coloncolon_located(text)
        stripped = text.strip()
        return CheckStatement(stripped.text, submodules, stripped)

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
            sym = f"{FRESH_PREFIX}{self.fresh_index}"
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
        raise_located_error("unclosed {", join_lines_located(pending))
    return lines


def split_indent_located(line: LocatedText) -> tuple[int, LocatedText]:
    first_line = line.text.splitlines()[0]
    indent = len(first_line) - len(first_line.lstrip(" "))
    return indent, line.strip()


def validate_indentation_levels_located(lines: list[LocatedText]) -> None:
    if not lines:
        return
    stack = [0]
    for index, line in enumerate(lines):
        indent, _ = split_indent_located(line)
        if index == 0 and indent != 0:
            raise_located_error(INDENTATION_BODY_OWNER_ERROR, line)
        if indent > stack[-1]:
            if indent != stack[-1] + INDENT_WIDTH:
                raise_located_error(INDENTATION_LEVEL_ERROR, line)
            stack.append(indent)
            continue
        while stack and indent < stack[-1]:
            stack.pop()
        if not stack or indent != stack[-1]:
            raise_located_error(INDENTATION_LEVEL_ERROR, line)


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
    physical_lines = [physical_line for line in block for physical_line in split_lines_located(line)]
    indents = [len(line.text) - len(line.text.lstrip(" ")) for line in physical_lines if line.text.strip()]
    trim = min(indents) if indents else 0
    return join_lines_located(
        [
            concat_located(
                [
                    physical_line.slice(trim)
                    for physical_line in split_lines_located(line)
                ]
            )
            for line in block
        ]
    )


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


def erase_coloncolon_statement_head_located(located: LocatedText) -> LocatedText:
    stripped = located.strip()
    if stripped.text.startswith("|") and not stripped.text.startswith("|-") and "::" in stripped.text:
        pipe = stripped.slice(0, 1)
        rest = erase_coloncolon_statement_head_located(stripped.slice(1).strip())
        return concat_located([pipe, synthetic_text(" ", pipe.positions[0]), rest])
    try:
        rewritten = erase_coloncolon_statement_head(stripped.text)
    except CompileError as error:
        raise_compile_error_located(error, stripped)
    if rewritten == stripped.text:
        return stripped
    if "::" in stripped.text:
        suffix = stripped.text.split("::", 1)[1]
        suffix_start = len(stripped.text) - len(suffix)
        colon_index = suffix.find(":")
        if colon_index >= 0:
            suffix_name = suffix[:colon_index]
            return concat_located([stripped.slice(suffix_start, suffix_start + len(suffix_name)), stripped.slice(suffix_start + len(suffix_name))])
        return synthetic_text(rewritten, stripped.positions[0])
    return synthetic_text(rewritten, stripped.positions[0])


def parse_class_field_assignment_located(located: LocatedText):
    stripped = located.strip()
    if stripped.text.startswith("|") and not stripped.text.startswith("|-"):
        inner = parse_class_field_assignment_located(stripped.slice(1).strip())
        if inner is None:
            return None
        assignment, rhs = inner
        return replace(assignment, premise=True), rhs

    assignment_index = top_level_assignment_index(stripped.text)
    if assignment_index is None:
        return None
    rhs = stripped.slice(assignment_index + 1).strip()
    try:
        assignment = parse_class_field_assignment(stripped.text)
    except CompileError as error:
        raise_compile_error_located(error, stripped)
    if assignment is None:
        return None
    return assignment, rhs


def class_field_assignment_module_located(header: LocatedText, assignment, rhs: LocatedText) -> LocatedText:
    origin = header.positions[0]
    receiver = "_" + lower_head(assignment.class_name)
    return concat_located(
        [
            synthetic_text(
                "∀{\n| "
                + receiver
                + "\n| "
                + assignment.class_name
                + " ~ "
                + receiver
                + "\n"
                + receiver
                + "."
                + assignment.field_name
                + " = ",
                origin,
            ),
            rhs,
            synthetic_text("\n}", origin),
        ]
    )


def reject_unsupported_coloncolon_located(located: LocatedText) -> None:
    try:
        reject_unsupported_coloncolon(located.text)
    except CompileError as error:
        raise_compile_error_located(error, located)


def class_block_prefix_lines_located(header: LocatedText, class_sym: str) -> list[LocatedText]:
    if explicit_class_header_sym(class_sym) is not None:
        return [synthetic_text(class_sym, header.positions[0])]
    return [synthetic_text(class_declaration_marker(class_sym), header.positions[0])]


def direct_class_header_names_located(lines: list[LocatedText]) -> set[str]:
    class_names: set[str] = set()
    for line in lines:
        indent, content = split_indent_located(line)
        if indent != 0:
            continue
        class_name = class_header_sym(content.text)
        if class_name is not None:
            class_names.add(class_name)
    return class_names


def extract_class_declarations_from_body_located(body: LocatedText) -> tuple[LocatedText, list[Declaration]]:
    if "\n" not in body.text:
        return body, []
    lines: list[LocatedText] = []
    declarations: list[Declaration] = []
    for line in logical_lines_located(body):
        _, stripped = split_indent_located(line)
        if not stripped.text:
            lines.append(line)
            continue
        declaration = class_declaration_from_plain_target_located(stripped)
        if declaration is not None:
            declarations.append(declaration)
            continue
        lines.append(line)
    return join_lines_located(lines), dedupe_declarations(declarations)


def class_declaration_from_plain_target_located(located: LocatedText) -> Declaration | None:
    stripped = located.strip()
    try:
        class_name = class_declaration_from_plain_target(stripped.text)
    except CompileError as error:
        raise_compile_error_located(error, stripped)
    if class_name is None:
        return None
    return Declaration(class_name, stripped.positions[0])


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
        raise_located_error(f"expected top-level {separator}", located)
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
@dataclass(frozen=True)
class TypedParseResult:
    module: Module
    source_loc: SourceLoc


def parse_located_module_text(
    located: LocatedText,
    *,
    visible_class_names: Iterable[str] = (),
) -> TypedParseResult:
    if not located.text:
        raise CompileError("empty module text")
    parser = LocatedModuleParser(visible_class_names=visible_class_names)
    check_module = parser.parse_module(located, default_quantifier="∀")
    return TypedParseResult(module=check_module_to_module(check_module), source_loc=source_loc_from_located(located))


def check_module_to_module(check_module: CheckModule) -> Module:
    syms = dedupe([binder.text for binder in check_module.binders])
    binder_locs_by_name: dict[str, dict[str, object]] = {}
    for binder in check_module.binders:
        binder_locs_by_name.setdefault(binder.text, loc_from_position(binder.position, len(binder.text)))
    predicate_statements = [check_statement_to_statement(statement) for statement in check_module.premise_binding_statements]
    predicate_statements.extend(check_statement_to_statement(statement) for statement in check_module.predicate_statements)
    target_statements = [check_statement_to_statement(statement) for statement in check_module.target_statements]
    declaration_syms: list[str] = []
    if check_module.declaration is not None:
        declaration_syms = [sym for sym in check_module.declaration.outputs if sym in syms]
        marker_name = DECL_BODY_OUTPUT_MARKER if target_statements else DECL_OUTPUT_MARKER
        predicate_statements.insert(0, synthetic_marker_statement(marker_name, list(check_module.declaration.outputs)))
    return Module(
        type=check_module.type,
        syms=syms,
        predicate_statements=predicate_statements,
        target_statements=target_statements,
        quantifier=check_module.quantifier,
        declared_classes=dedupe([declaration.name for declaration in check_module.class_declarations]),
        declaration_syms=dedupe(declaration_syms),
        suppress_inferred_syms=check_module.suppress_inferred_syms,
        bound_sym_locs=[binder_locs_by_name.get(sym) for sym in syms],
        bound_sym_source_names=[source_name_for_bound_sym(sym) for sym in syms],
        declared_class_locs={
            declaration.name: loc_from_position(declaration.position, len(declaration.name))
            for declaration in check_module.class_declarations
        },
    )


def check_statement_to_statement(check_statement: CheckStatement) -> Statement:
    located = check_statement.located
    source_loc = loc_from_located(located) if located is not None else None
    submodules = [check_module_to_module(module) for module in check_statement.sub_modules]
    if located is not None and check_statement.text.strip():
        expr = parse_expr_located(located)
    elif check_statement.text.startswith("$module") and submodules:
        expr = Module_ref_expr(source_loc, value="0")
    else:
        expr = None
    return Statement(
        sub_modules=submodules,
        source_loc=source_loc,
        sym_locs=sym_locs_from_expr(expr),
        source_name=None,
        expr=expr,
    )


def synthetic_marker_statement(marker: str, syms: list[str]) -> Statement:
    return Statement(
        source_loc={"source": "__generated__", "line": 1, "column": 1, "end_line": 1, "end_column": 1},
        marker=marker,
        marker_syms=syms,
    )


def source_name_for_bound_sym(sym: str) -> str | None:
    if is_generated_sym_name(sym):
        return sym[len(GENERATED_SYM_PREFIX) :]
    return None


def parse_expr_located(located: LocatedText) -> ExprNode:
    located = located.strip()
    text = located.text
    if not text:
        return Empty_expr(loc_from_located(located))
    module_ref = re.fullmatch(r"\$module(?P<index>\d+)", text)
    if module_ref is not None:
        return Module_ref_expr(loc_from_located(located), value=module_ref.group("index"))
    assignment_index = top_level_assignment_index(text)
    if assignment_index is not None:
        call_loc = loc_from_position(located.positions[assignment_index], 1)
        return Call_expr(
            loc_from_located(located),
            call_sym=SymNode("=", call_loc),
            args=[
                parse_expr_located(located.slice(0, assignment_index).strip()),
                parse_expr_located(located.slice(assignment_index + 1).strip()),
            ],
        )
    literal = literal_from_text(text)
    if literal is not None:
        if literal.kind == "char":
            return Char_literal_expr(loc_from_located(located), value=literal.value)
        if literal.kind == "string":
            return String_literal_expr(loc_from_located(located), value=literal.value)
        return Value_literal_expr(loc_from_located(located), value=literal.value)
    range_terms = parse_range_literal_located(located)
    if range_terms is not None:
        start, end, op_loc = range_terms
        return Call_expr(loc_from_located(located), call_sym=SymNode("[:]", op_loc), args=[parse_expr_located(start), parse_expr_located(end)])
    tuple_items = parse_tuple_or_list_items_located(located)
    if tuple_items is not None:
        return Tuple_expr(
            loc_from_located(located),
            items=[parse_expr_located(item) for item in tuple_items],
        )
    set_items = parse_set_literal_items_located(located)
    if set_items is not None:
        return Set_expr(
            loc_from_located(located),
            items=[parse_expr_located(item) for item in set_items],
        )
    grouped = strip_outer_grouping_parens_located(located)
    if grouped is not None:
        return parse_expr_located(grouped)
    member = parse_member_call_located(located)
    if member is not None:
        name, call_loc, args = member
        return Call_expr(loc_from_located(located), call_sym=SymNode(name, call_loc), args=[parse_expr_located(arg) for arg in args])
    infix = parse_infix_located(located)
    if infix is not None:
        op, op_loc, lhs, rhs = infix
        return Call_expr(loc_from_located(located), call_sym=SymNode(op, op_loc), args=[parse_expr_located(lhs), parse_expr_located(rhs)])
    prefix = parse_prefix_unary_located(located)
    if prefix is not None:
        op, op_loc, operand = prefix
        return Call_expr(loc_from_located(located), call_sym=SymNode(op, op_loc), args=[parse_expr_located(operand)])
    index = parse_index_call_located(located)
    if index is not None:
        receiver, index_expr, op_loc = index
        range_index = parse_range_terms_located(index_expr)
        if range_index is not None:
            start, end = range_index
            return Call_expr(loc_from_located(located), call_sym=SymNode("[:]", op_loc), args=[parse_expr_located(receiver), parse_expr_located(start), parse_expr_located(end)])
        return Call_expr(loc_from_located(located), call_sym=SymNode("[]", op_loc), args=[parse_expr_located(receiver), parse_expr_located(index_expr)])
    call = parse_call_located(located)
    if call is not None:
        name, name_loc, args = call
        return Call_expr(loc_from_located(located), call_sym=SymNode(name, name_loc), args=[parse_expr_located(arg) for arg in args])
    if is_sym_like(text):
        return Sym_expr(loc_from_located(located), sym=SymNode(text, loc_from_located(located), generated=is_generated_sym_name(text), source_name=source_name_for_bound_sym(text)))
    return Raw_expr(loc_from_located(located), value=text)


def literal_from_text(text: str) -> LiteralValue | None:
    literal = parse_literal_text(text)
    if literal is not None:
        return literal
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return LiteralValue("value", text, text)
    return None


def parse_tuple_or_list_items_located(located: LocatedText) -> list[LocatedText] | None:
    text = located.text.strip()
    if len(text) < 2:
        return None
    pairs = {"(": ")", "[": "]"}
    if text[0] not in pairs or text[-1] != pairs[text[0]]:
        return None
    if find_matching(text, 0, text[0], text[-1]) != len(text) - 1:
        return None
    inner = located.strip().slice(1, -1).strip()
    if not inner.text:
        return [] if text[0] == "(" else None
    items = [part.strip() for part in split_top_level_located(inner, ",") if part.text.strip()]
    if len(items) <= 1 and "," not in inner.text:
        return None
    return items


def parse_set_literal_items_located(located: LocatedText) -> list[LocatedText] | None:
    text = located.text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    if find_matching(text, 0, "{", "}") != len(text) - 1:
        return None
    inner = located.strip().slice(1, -1).strip()
    if "|" in inner.text or "=>" in inner.text:
        return None
    if not inner.text:
        return []
    return [part.strip() for part in split_top_level_located(inner, ",") if part.text.strip()]


def parse_range_literal_located(located: LocatedText) -> tuple[LocatedText, LocatedText, dict[str, object]] | None:
    stripped = located.strip()
    if not (stripped.text.startswith("[") and stripped.text.endswith("]")):
        return None
    if find_matching(stripped.text, 0, "[", "]") != len(stripped.text) - 1:
        return None
    terms = parse_range_terms_located(stripped.slice(1, -1).strip())
    if terms is None:
        return None
    return terms[0], terms[1], loc_from_position(stripped.positions[0], 3)


def parse_range_terms_located(located: LocatedText) -> tuple[LocatedText, LocatedText] | None:
    parts = [part.strip() for part in split_top_level_located(located, ":")]
    if len(parts) != 2 or not parts[0].text or not parts[1].text:
        return None
    return parts[0], parts[1]


def strip_outer_grouping_parens_located(located: LocatedText) -> LocatedText | None:
    text = located.text.strip()
    if len(text) < 2 or not text.startswith("(") or not text.endswith(")"):
        return None
    if find_matching(text, 0, "(", ")") != len(text) - 1:
        return None
    inner = located.strip().slice(1, -1).strip()
    if not inner.text or len(split_top_level(inner.text, ",")) > 1:
        return None
    return inner


INFIX_OPERATORS: tuple[tuple[str, str], ...] = (
    ("||", "||"), ("∨", "∨"), ("&&", "&&"), ("∧", "∧"), ("!=", "!="), ("≠", "!="),
    (">=", ">="), ("≥", ">="), ("<=", "<="), ("≤", "<="), ("∉", "∉"), ("∈", "∈"),
    ("⊄", "⊄"), ("⊂", "⊂"), ("⊈", "⊈"), ("⊆", "⊆"), ("=", "="), (">", ">"),
    ("<", "<"), ("~", "~"), ("∪", "∪"), ("+", "+"), ("-", "-"), ("∩", "∩"),
    ("*", "*"), ("/", "/"),
)


def parse_infix_located(located: LocatedText) -> tuple[str, dict[str, object], LocatedText, LocatedText] | None:
    matches = find_top_level_operator_matches(located.text, INFIX_OPERATORS)
    if not matches:
        return None
    for index, raw, canonical in reversed(matches):
        lhs = located.slice(0, index).strip()
        rhs = located.slice(index + len(raw)).strip()
        if lhs.text and rhs.text:
            return canonical, loc_from_position(located.positions[index], len(raw)), lhs, rhs
    return None


def parse_prefix_unary_located(located: LocatedText) -> tuple[str, dict[str, object], LocatedText] | None:
    text = located.text.strip()
    for op in ("!", "-", "*"):
        if not text.startswith(op):
            continue
        if text[len(op) :].startswith("("):
            return None
        operand = located.strip().slice(len(op)).strip()
        if operand.text and not (op == "!" and operand.text.startswith("=")):
            return op, loc_from_position(located.strip().positions[0], len(op)), operand
    return None


def parse_call_located(located: LocatedText) -> tuple[str, dict[str, object], list[LocatedText]] | None:
    text = located.text.strip()
    if not text.endswith(")"):
        return None
    open_index = text.find("(")
    if open_index <= 0 or find_matching(text, open_index, "(", ")") != len(text) - 1:
        return None
    stripped = located.strip()
    name = stripped.slice(0, open_index).strip()
    if not is_sym_like(name.text):
        return None
    inner = stripped.slice(open_index + 1, -1).strip()
    args = [] if not inner.text else [arg.strip() for arg in split_top_level_located(inner, ",")]
    return name.text, loc_from_located(name), args


def parse_index_call_located(located: LocatedText) -> tuple[LocatedText, LocatedText, dict[str, object]] | None:
    text = located.text.strip()
    if not text.endswith("]"):
        return None
    open_index = text.rfind("[")
    if open_index <= 0 or find_matching(text, open_index, "[", "]") != len(text) - 1:
        return None
    stripped = located.strip()
    index_expr = stripped.slice(open_index + 1, -1).strip()
    if not index_expr.text:
        return None
    return stripped.slice(0, open_index).strip(), index_expr, loc_from_position(stripped.positions[open_index], 2)


def parse_member_call_located(located: LocatedText) -> tuple[str, dict[str, object], list[LocatedText]] | None:
    text = located.text.strip()
    dot_index = top_level_dot_index(text)
    if dot_index is None:
        return None
    stripped = located.strip()
    receiver = stripped.slice(0, dot_index).strip()
    rest = stripped.slice(dot_index + 1).strip()
    match = re.match(r"(?P<name>[^\s.()[\]{}:,]+)(?P<tail>\(.*\))?$", rest.text)
    if match is None:
        return None
    name = match.group("name")
    name_loc = loc_from_position(rest.positions[0], len(name))
    if match.group("tail"):
        tail_start = len(name)
        tail = rest.slice(tail_start).strip()
        if not tail.text.startswith("(") or find_matching(tail.text, 0, "(", ")") != len(tail.text) - 1:
            return None
        inner = tail.slice(1, -1).strip()
        args = [] if not inner.text else [arg.strip() for arg in split_top_level_located(inner, ",")]
    else:
        args = []
    return name, name_loc, [receiver, *args]


def top_level_dot_index(text: str) -> int | None:
    stack: list[str] = []
    found: int | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == ".":
            found = index
        index += 1
    return found


def find_top_level_operator_matches(text: str, operators: tuple[tuple[str, str], ...]) -> list[tuple[int, str, str]]:
    matches: list[tuple[int, str, str]] = []
    stack: list[str] = []
    index = 0
    for raw, canonical in sorted(operators, key=lambda item: len(item[0]), reverse=True):
        pass
    index = 0
    ordered = sorted(operators, key=lambda item: len(item[0]), reverse=True)
    while index < len(text):
        char = text[index]
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
            index += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
            index += 1
            continue
        if stack:
            index += 1
            continue
        matched = False
        for raw, canonical in ordered:
            if text.startswith(raw, index) and is_operator_match(text, index, raw):
                matches.append((index, raw, canonical))
                index += len(raw)
                matched = True
                break
        if not matched:
            index += 1
    return matches


def is_operator_match(text: str, index: int, raw: str) -> bool:
    previous = text[index - 1] if index > 0 else ""
    next_index = index + len(raw)
    nxt = text[next_index] if next_index < len(text) else ""
    if raw in {"+", "-", "*"}:
        previous_token = previous_nonspace_char(text, index)
        next_token = next_nonspace_char(text, next_index)
        return bool(previous_token and next_token) and previous_token not in "([{!+-*/=<>&|∧∨∪∩~"
    if raw == "=":
        return previous not in {"<", ">", "!", "="} and nxt not in {">", "="}
    if raw in {"<", ">"}:
        return previous != "=" and nxt != "="
    return True


def previous_nonspace_char(text: str, index: int) -> str:
    cursor = index - 1
    while cursor >= 0 and text[cursor].isspace():
        cursor -= 1
    return text[cursor] if cursor >= 0 else ""


def next_nonspace_char(text: str, index: int) -> str:
    cursor = index
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return text[cursor] if cursor < len(text) else ""


def split_top_level_located(located: LocatedText, separator: str) -> list[LocatedText]:
    parts: list[LocatedText] = []
    start = 0
    for part in split_top_level(located.text, separator):
        end = start + len(part)
        parts.append(located.slice(start, end))
        start = end + len(separator)
    return parts


def is_sym_like(text: str) -> bool:
    return is_plain_sym(text) or ("^" not in text and re.fullmatch(r"[^\s()\[\]{},]+", text) is not None)


def sym_locs_from_expr(expr: ExprNode | None) -> dict[str, dict[str, object]]:
    locs: dict[str, dict[str, object]] = {}
    if expr is None:
        return locs
    if expr.sym is not None and expr.sym.source_loc is not None:
        locs.setdefault(expr.sym.name, loc_to_json(expr.sym.source_loc))
    if expr.call_sym is not None and expr.call_sym.source_loc is not None:
        locs.setdefault(expr.call_sym.name, loc_to_json(expr.call_sym.source_loc))
    for child in [*expr.args, *expr.items]:
        locs.update(sym_locs_from_expr(child))
    return locs


def loc_from_position(position: SourcePosition, width: int = 1) -> dict[str, object]:
    return {
        "source": position.file,
        "line": position.line,
        "column": position.column,
        "end_line": position.line,
        "end_column": position.column + max(width, 1),
    }


def loc_from_located(located: LocatedText) -> dict[str, object]:
    stripped = located.strip()
    if not stripped.positions:
        return {"source": "__stdin__", "line": 1, "column": 1, "end_line": 1, "end_column": 1}
    first = stripped.positions[0]
    last = stripped.positions[-1]
    return {
        "source": first.file,
        "line": first.line,
        "column": first.column,
        "end_line": last.line,
        "end_column": last.column + 1,
    }


def source_loc_from_located(located: LocatedText) -> SourceLoc:
    loc = loc_from_located(located)
    return SourceLoc(str(loc["source"]), int(loc["line"]), int(loc["column"]), int(loc["end_line"]), int(loc["end_column"]))


def loc_to_json(loc: object) -> dict[str, object]:
    if hasattr(loc, "to_json"):
        return loc.to_json()  # type: ignore[no-any-return]
    return dict(loc)  # type: ignore[arg-type]
