#!/usr/bin/env python3
"""Normalize source declaration ordering without compiling declarations away."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import (
    collect_indented_block,
    declaration_colon_index,
    find_matching,
    is_bare_coloncolon_field_shorthand,
    is_plain_sym,
    logical_lines,
    parse_class_field_assignment,
    parse_declaration,
    split_indent,
    split_top_level,
    strip_outer_blank_lines,
    top_level_assignment_index,
    unindent_block,
    undeclared_class_member_owner_reason,
)
from compile_pipeline.stage1_normalize_source import STDIN_SOURCE, run as normalize_source


INDENT = 4
QUANTIFIERS = {"∀", "∃"}


@dataclass
class SourceUnit:
    kind: str
    text: str = ""
    header: str = ""
    body: str | None = None
    name: str = ""
    class_name: str = ""
    members: list["ClassMember"] = field(default_factory=list)


@dataclass
class ClassMember:
    header: str
    body: str | None = None
    name: str = ""
    is_method: bool = False


@dataclass
class ClassGroup:
    name: str
    members: list[ClassMember] = field(default_factory=list)


def normalize_module_declarations_text(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = STDIN_SOURCE,
    allow_imports: bool = True,
) -> str:
    normalized = normalize_source(text, base_dir, source=source, allow_imports=allow_imports).text
    body = strip_outer_blank_lines(normalized)
    if not body:
        return ""
    body = unwrap_root_for_implicit_render(body)
    units = parse_body_units(body)
    rendered = render_units(normalize_units(units), 0)
    return rendered.rstrip() + "\n"


def unwrap_root_for_implicit_render(text: str) -> str:
    stripped = strip_outer_blank_lines(text).strip()
    wrapped = wrapped_module_body(stripped)
    if wrapped is not None and wrapped[0] == "∀":
        return wrapped[1]

    lines = logical_lines(strip_outer_blank_lines(text))
    if len(lines) == 1:
        return text
    indent, content = split_indent(lines[0])
    if content == "∀":
        block, next_index = collect_indented_block(lines, 1, indent)
        if block and next_index == len(lines):
            return unindent_block(block)
    return text


def parse_body_units(text: str) -> list[SourceUnit]:
    body = expand_inline_module_body(strip_outer_blank_lines(text))
    if not body:
        return []
    lines = logical_lines(body)
    units: list[SourceUnit] = []
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        indent, content = split_indent(raw_line)
        block: list[str] = []
        next_index = index + 1
        if index + 1 < len(lines):
            block, next_index = collect_indented_block(lines, index + 1, indent)
        if block:
            units.append(classify_block_unit(content, unindent_block(block)))
            index = next_index
            continue
        units.append(classify_single_unit(content))
        index += 1
    return units


def expand_inline_module_body(text: str) -> str:
    if "\n" in text:
        return text
    sections = [section.strip() for section in split_top_level(text, "|")]
    if len(sections) <= 1:
        return text
    sections = [section for section in sections if section]
    if len(sections) <= 1:
        return text
    return "\n".join([*(f"| {section}" for section in sections[:-1]), sections[-1]])


def classify_block_unit(header: str, body: str) -> SourceUnit:
    if header in QUANTIFIERS or header.startswith("@"):
        quantifier = "∀" if header.startswith("@") else header
        if quantifier == "∀":
            return SourceUnit(kind="forall", body=body)
        return SourceUnit(kind="opaque", header=header, body=body)
    if header.startswith("|-"):
        return SourceUnit(kind="opaque", header=header, body=body)
    member = explicit_class_field_member(header)
    if member is not None:
        raise CompileError("class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration")
    if is_class_header(header):
        return SourceUnit(kind="class", name=header.strip(), members=parse_class_members(body))
    declaration = declaration_info(header)
    if declaration is not None:
        name, class_name = declaration
        if class_name:
            return SourceUnit(
                kind="class_member",
                class_name=class_name,
                members=[ClassMember(header=method_header_for_class(header, class_name), body=body, name=name, is_method=True)],
            )
        return SourceUnit(kind="function", name=name, header=header.strip(), body=body)
    return SourceUnit(kind="opaque", header=header, body=body)


def classify_single_unit(text: str) -> SourceUnit:
    stripped = text.strip()
    wrapped = wrapped_module_body(stripped)
    if wrapped is not None:
        quantifier, body = wrapped
        if quantifier == "∀":
            return SourceUnit(kind="forall", body=body)
        return SourceUnit(kind="opaque", text=stripped)
    if is_class_header(stripped):
        return SourceUnit(kind="class", name=stripped)
    if is_class_inheritance(stripped):
        return SourceUnit(kind="inheritance", text=stripped)
    member = explicit_class_field_member(stripped)
    if member is not None:
        class_name, class_member = member
        return SourceUnit(kind="class_member", class_name=class_name, members=[class_member])
    declaration = declaration_info(stripped)
    if declaration is not None:
        name, class_name = declaration
        if class_name:
            return SourceUnit(
                kind="class_member",
                class_name=class_name,
                members=[ClassMember(header=method_header_for_class(stripped, class_name), name=name, is_method=True)],
            )
        return SourceUnit(kind="function", name=name, header=stripped)
    if is_bound_sym_line(stripped):
        return SourceUnit(kind="bound", text=stripped)
    return SourceUnit(kind="other", text=stripped)


def parse_class_members(body: str) -> list[ClassMember]:
    members: list[ClassMember] = []
    lines = logical_lines(strip_outer_blank_lines(body))
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        indent, content = split_indent(raw_line)
        if indent != 0 or not content.startswith("::"):
            raise CompileError("class-declaration body line must start with '::'")
        block, next_index = collect_indented_block(lines, index + 1, indent)
        member_body = unindent_block(block) if block else None
        members.append(class_member_from_header(content, member_body))
        index = next_index
    return members


def class_member_from_header(header: str, body: str | None = None) -> ClassMember:
    if body is not None and top_level_assignment_index(header.strip()) is not None:
        raise CompileError("class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration")
    name = member_name(header)
    return ClassMember(header=header.strip(), body=body, name=name, is_method=declaration_colon_index(header) is not None)


def explicit_class_field_member(text: str) -> tuple[str, ClassMember] | None:
    assignment = parse_class_field_assignment(text)
    if assignment is not None and not assignment.premise:
        return assignment.class_name, ClassMember(
            header=f"::{assignment.field_name} = {assignment.rhs}",
            name=assignment.field_name,
            is_method=False,
        )
    if not is_bare_coloncolon_field_shorthand(text):
        return None
    class_name, field_name = (part.strip() for part in text.split("::", 1))
    return class_name, ClassMember(header=f"::{field_name}", name=field_name, is_method=False)


def declaration_info(text: str) -> tuple[str, str | None] | None:
    if text.startswith("|"):
        return None
    colon_index = declaration_colon_index(text)
    if colon_index is None:
        return None
    head = text[:colon_index].strip()
    if not head:
        return None
    try:
        parsed = parse_declaration(text)
    except CompileError:
        raise
    if parsed is None:
        return None
    if "::" in head:
        class_name, method_name = (part.strip() for part in head.split("::", 1))
        return method_name, class_name
    return parsed[0], None


def method_header_for_class(header: str, class_name: str) -> str:
    colon_index = declaration_colon_index(header)
    if colon_index is None:
        return header.strip()
    head = header[:colon_index].strip()
    if "::" not in head:
        return header.strip()
    prefix, method_name = (part.strip() for part in head.split("::", 1))
    if prefix != class_name:
        return header.strip()
    return "::" + method_name + header[colon_index:]


def member_name(header: str) -> str:
    stripped = header.strip()
    if stripped.startswith("::"):
        stripped = stripped[2:].strip()
    assignment_index = top_level_assignment_index(stripped)
    if assignment_index is not None:
        stripped = stripped[:assignment_index].strip()
    colon_index = declaration_colon_index(stripped)
    if colon_index is not None:
        return stripped[:colon_index].strip()
    return stripped


def normalize_units(units: list[SourceUnit]) -> list[SourceUnit]:
    units = merge_direct_class_units(units)
    output: list[SourceUnit] = []
    segment: list[SourceUnit] = []
    for unit in units:
        if is_barrier(unit):
            output.extend(normalize_segment(segment))
            segment = []
            output.append(normalize_barrier(unit))
            continue
        segment.append(unit)
    output.extend(normalize_segment(segment))
    return output


def merge_direct_class_units(units: list[SourceUnit]) -> list[SourceUnit]:
    first_class: dict[str, SourceUnit] = {}
    collected_members: dict[str, list[ClassMember]] = {}
    for unit in units:
        if unit.kind == "class" and unit.name not in first_class:
            first_class[unit.name] = unit

    for unit in units:
        if unit.kind == "class":
            collected_members.setdefault(unit.name, []).extend(unit.members)
        elif unit.kind == "class_member":
            first = first_class.get(unit.class_name)
            if first is None:
                raise CompileError(undeclared_class_member_owner_reason(unit.class_name))
            collected_members.setdefault(unit.class_name, []).extend(unit.members)

    for name, first in first_class.items():
        first.members = collected_members.get(name, [])

    output: list[SourceUnit] = []
    for unit in units:
        if unit.kind == "class":
            first = first_class[unit.name]
            if unit is first:
                output.append(unit)
            continue
        if unit.kind == "class_member":
            continue
        output.append(unit)
    return output


def normalize_barrier(unit: SourceUnit) -> SourceUnit:
    if unit.kind == "forall" and unit.body is not None:
        unit.body = render_units(normalize_units(parse_body_units(unit.body)), 0).rstrip()
    return unit


def is_barrier(unit: SourceUnit) -> bool:
    return unit.kind in {"forall", "opaque"}


def normalize_segment(units: list[SourceUnit]) -> list[SourceUnit]:
    if not units:
        return []
    bounds: list[SourceUnit] = []
    inheritances: list[SourceUnit] = []
    functions: dict[str, list[SourceUnit]] = {}
    function_order: list[str] = []
    classes: dict[str, ClassGroup] = {}
    class_order: list[str] = []
    others: list[SourceUnit] = []

    for unit in units:
        if unit.kind == "bound":
            bounds.append(unit)
        elif unit.kind == "class":
            group = classes.setdefault(unit.name, ClassGroup(unit.name))
            if unit.name not in class_order:
                class_order.append(unit.name)
            group.members.extend(unit.members)
        elif unit.kind == "class_member":
            group = classes.setdefault(unit.class_name, ClassGroup(unit.class_name))
            if unit.class_name not in class_order:
                class_order.append(unit.class_name)
            group.members.extend(unit.members)
        elif unit.kind == "inheritance":
            inheritances.append(unit)
        elif unit.kind == "function":
            if unit.name not in functions:
                function_order.append(unit.name)
                functions[unit.name] = []
            functions[unit.name].append(unit)
        else:
            others.append(unit)

    bare_classes: list[SourceUnit] = []
    member_classes: list[SourceUnit] = []
    member_class_names: set[str] = set()
    for name in class_order:
        class_unit = SourceUnit(kind="class", name=name, members=normalize_class_members(classes[name].members))
        if class_unit.members:
            member_classes.append(class_unit)
            member_class_names.add(name)
        else:
            bare_classes.append(class_unit)

    leading_inheritances: list[SourceUnit] = []
    member_inheritances: dict[str, list[SourceUnit]] = {}
    for inheritance in inheritances:
        child_name = inheritance_child_name(inheritance.text)
        if child_name in member_class_names:
            member_inheritances.setdefault(child_name, []).append(inheritance)
        else:
            leading_inheritances.append(inheritance)

    normalized: list[SourceUnit] = []
    normalized.extend(bounds)
    normalized.extend(bare_classes)
    normalized.extend(leading_inheritances)
    for class_unit in member_classes:
        normalized.extend(member_inheritances.get(class_unit.name, []))
        normalized.append(class_unit)
    for name in function_order:
        normalized.extend(functions[name])
    normalized.extend(others)
    return normalized


def normalize_class_members(members: list[ClassMember]) -> list[ClassMember]:
    grouped: dict[tuple[str, str, int], list[ClassMember]] = {}
    order: list[tuple[str, str, int]] = []
    field_index = 0
    for member in members:
        if member.is_method:
            key = ("method", member.name, 0)
        else:
            key = ("field", member.name, field_index)
            field_index += 1
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(member)
    output: list[ClassMember] = []
    for key in order:
        output.extend(grouped[key])
    return output


def render_units(units: list[SourceUnit], indent: int) -> str:
    lines: list[str] = []
    for unit in units:
        rendered = render_unit(unit, indent)
        if rendered:
            lines.extend(rendered.splitlines())
    return "\n".join(lines)


def render_unit(unit: SourceUnit, indent: int) -> str:
    if unit.kind == "forall":
        return render_block("∀", unit.body or "", indent)
    if unit.kind == "opaque":
        if unit.text:
            return reindent_text(unit.text, indent)
        return render_block(unit.header, unit.body or "", indent)
    if unit.kind == "class":
        return render_class_group(unit, indent)
    if unit.kind == "function":
        if unit.body is not None:
            return render_block(unit.header, unit.body, indent)
        return " " * indent + unit.header
    return " " * indent + unit.text


def render_class_group(unit: SourceUnit, indent: int) -> str:
    lines = [" " * indent + unit.name]
    for member in unit.members:
        lines.append(" " * (indent + INDENT) + member.header)
        if member.body:
            lines.extend(reindent_text(member.body, indent + INDENT * 2).splitlines())
    return "\n".join(lines)


def render_block(header: str, body: str, indent: int) -> str:
    lines = [" " * indent + header.strip()]
    body = strip_outer_blank_lines(body)
    if body:
        lines.extend(reindent_text(body, indent + INDENT).splitlines())
    return "\n".join(lines)


def reindent_text(text: str, indent: int) -> str:
    pad = " " * indent
    return "\n".join(pad + line if line.strip() else "" for line in strip_outer_blank_lines(text).splitlines())


def wrapped_module_body(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    quantifier = ""
    body_start = 0
    if stripped[0] in QUANTIFIERS:
        quantifier = stripped[0]
        body_start = 1
    if body_start >= len(stripped) or stripped[body_start] != "{":
        return None
    close = find_matching(stripped, body_start, "{", "}")
    if close != len(stripped) - 1:
        return None
    return quantifier, stripped[body_start + 1 : close]


def is_bound_sym_line(text: str) -> bool:
    return is_plain_sym(text) and not is_capital_sym(text)


def is_class_header(text: str) -> bool:
    return is_plain_sym(text) and is_capital_sym(text)


def is_class_inheritance(text: str) -> bool:
    if text.startswith("|"):
        return False
    parts = split_top_level(text, "~")
    if len(parts) != 2:
        return False
    left, right = (part.strip() for part in parts)
    return is_plain_sym(left) and is_plain_sym(right) and is_capital_sym(left) and is_capital_sym(right)


def inheritance_child_name(text: str) -> str | None:
    parts = split_top_level(text, "~")
    if len(parts) != 2:
        return None
    return parts[1].strip()


def is_capital_sym(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and stripped[0].isalpha() and stripped[0].isupper())


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize logic-language declaration ordering.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    args = parser.parse_args()

    if args.text is not None:
        source = args.text
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()
    elif args.file is not None:
        try:
            source = args.file.read_text(encoding="utf-8")
        except OSError as error:
            print(error, file=sys.stderr)
            return 1
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
    else:
        source = sys.stdin.read()
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()

    try:
        sys.stdout.write(normalize_module_declarations_text(source, base_dir, source=source_name, allow_imports=True))
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
