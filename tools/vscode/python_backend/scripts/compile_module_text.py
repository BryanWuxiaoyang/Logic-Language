#!/usr/bin/env python3
"""Compile logic-language module text to JSON Module data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from lark import Lark, UnexpectedInput
except ModuleNotFoundError:  # pragma: no cover - exercised by CLI environments.
    Lark = None  # type: ignore[assignment]
    UnexpectedInput = Exception  # type: ignore[assignment]


LATEX_CODE_RE = re.compile(r"\\[A-Za-z_][A-Za-z0-9_]*")
IMPORT_RE = re.compile(r"^(?P<indent>[ \t]*)\$import\s+(?P<path>.+?)\s*$")
INTRINSIC_SYMS = {"tuple", "set", "function", "value", "true", "false", "bool", "sym"}
INFER_OPERATORS = ("=", ">", "<", ">=", "<=", "≤", "≥", "∈", "∉", "⊂", "⊄", "⊆", "⊈", "≠")
FRESH_PREFIX = "__logic_language_out"


class CompileError(Exception):
    """Raised when module text cannot be compiled."""


@dataclass
class Statement:
    text: str
    sub_modules: list["Module"] = field(default_factory=list)

    def to_json(self, output_tokens: dict[str, str] | None = None) -> dict[str, Any]:
        return {
            "text": encode_output_text(self.text, output_tokens),
            "sub_modules": [module.to_json(output_tokens) for module in self.sub_modules],
        }

    def to_readable_json(self, output_tokens: dict[str, str] | None = None) -> Any:
        text = encode_output_text(self.text, output_tokens)
        if not self.sub_modules:
            return text
        data: dict[str, Any] = {
            "text": text,
            "sub_modules": [module.to_readable_json(output_tokens) for module in self.sub_modules],
        }
        return data


@dataclass
class Module:
    type: str
    syms: list[str]
    predicate_statements: list[Statement]
    target_statements: list[Statement]
    quantifier: str | None = None

    def to_json(self, output_tokens: dict[str, str] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
        }
        if self.quantifier is not None:
            data["quantifier"] = encode_output_text(self.quantifier, output_tokens)
        data.update(
            {
                "syms": [encode_output_text(sym, output_tokens) for sym in self.syms],
                "predicate_statements": [statement.to_json(output_tokens) for statement in self.predicate_statements],
                "target_statements": [statement.to_json(output_tokens) for statement in self.target_statements],
            }
        )
        return data

    def to_readable_json(self, output_tokens: dict[str, str] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
        }
        if self.quantifier is not None:
            data["quantifier"] = encode_output_text(self.quantifier, output_tokens)
        data.update(
            {
                "syms": [encode_output_text(sym, output_tokens) for sym in self.syms],
                "predicate_statements": [statement.to_readable_json(output_tokens) for statement in self.predicate_statements],
                "target_statements": [statement.to_readable_json(output_tokens) for statement in self.target_statements],
            }
        )
        return data


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def load_lark_parser() -> Any:
    if Lark is None:
        raise CompileError("missing dependency: install skills/logic-language/requirements.txt")
    grammar_path = skill_dir() / "grammar.ebnf"
    return Lark(grammar_path.read_text(encoding="utf-8"), start="start", parser="earley")


def load_tokens() -> dict[str, str]:
    token_path = skill_dir() / "latex-tokens.json"
    with token_path.open(encoding="utf-8") as token_file:
        tokens = json.load(token_file)
    invalid_keys = [key for key in tokens if not key.startswith("\\")]
    if invalid_keys:
        joined = ", ".join(sorted(invalid_keys))
        raise CompileError(f"latex token keys must start with backslash: {joined}")
    return tokens


def make_output_tokens(tokens: dict[str, str]) -> dict[str, str]:
    output_tokens: dict[str, str] = {}
    for latex_code, identifier in tokens.items():
        if not identifier or identifier.isascii():
            continue
        output_tokens.setdefault(identifier, latex_code)
    return output_tokens


def normalize_latex(text: str, tokens: dict[str, str]) -> str:
    normalized = text
    for key in sorted(tokens, key=len, reverse=True):
        normalized = normalized.replace(key, tokens[key])
    unknowns = list(LATEX_CODE_RE.finditer(normalized))
    if unknowns:
        match = unknowns[0]
        line, column = line_column(normalized, match.start())
        raise CompileError(f"{line}:{column}: unknown latex code {match.group(0)}")
    return normalized


def encode_output_text(text: str, output_tokens: dict[str, str] | None) -> str:
    if not output_tokens:
        return text
    encoded = text
    for identifier in sorted(output_tokens, key=len, reverse=True):
        encoded = encoded.replace(identifier, output_tokens[identifier])
    return encoded


def line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1


def expand_imports(text: str, base_dir: Path, seen: set[Path] | None = None) -> str:
    seen = set() if seen is None else seen
    output_lines: list[str] = []
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if not match:
            output_lines.append(line)
            continue
        import_path = Path(match.group("path").strip().strip("\"'"))
        if not import_path.is_absolute():
            import_path = base_dir / import_path
        import_path = import_path.resolve()
        if import_path in seen:
            raise CompileError(f"cyclic import: {import_path}")
        if not import_path.exists():
            raise CompileError(f"import not found: {import_path}")
        imported = expand_imports(import_path.read_text(encoding="utf-8"), import_path.parent, seen | {import_path})
        indent = match.group("indent")
        output_lines.extend(indent + imported_line if imported_line else imported_line for imported_line in imported.splitlines())
    return "\n".join(output_lines)


def compile_module_text(text: str, base_dir: Path | str = ".") -> Module:
    from expand_module import expand_module_text

    parser = load_lark_parser()
    expanded = expand_module_text(text, Path(base_dir).resolve())
    return ModuleCompiler(parser).compile(strip_artifact_imports(expanded))


def strip_artifact_imports(text: str) -> str:
    lines = [line for line in text.splitlines() if not IMPORT_RE.match(line)]
    return "\n".join(lines)


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
        return ["function~" + name, "∀{\n| " + ", ".join(inputs + outputs) + "\n| " + target + "\n" + block + "\n}"]

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
            if candidates and not syms:
                syms = candidates
            else:
                predicate_sections.append(section)
        predicate_texts = split_terms("\n".join(predicate_sections))
        target_texts = split_terms(target_section)
        if not syms:
            inferred = infer_syms(predicate_texts)
            syms = inferred
        syms = dedupe([sym for sym in syms if sym not in INTRINSIC_SYMS])
        if module_type == "set" and not syms:
            raise CompileError("set module requires non-empty syms")
        if not target_texts:
            raise CompileError("module requires non-empty target_statements")
        predicate_statements = [self.compile_statement(term) for term in predicate_texts]
        target_statements = [self.compile_statement(term) for term in target_texts]
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

    def compile_statement(self, text: str) -> Statement:
        text = text.strip()
        text = lower_member_calls(text)
        rewritten, sub_modules = self.extract_sub_modules(text)
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


def remove_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(strip_comment(line).rstrip())
    return "\n".join(lines)


def strip_comment(line: str) -> str:
    in_string = False
    escaped = False
    for index, char in enumerate(line):
        if char == "\\" and in_string:
            escaped = not escaped
            continue
        if char == '"' and not escaped:
            in_string = not in_string
        escaped = False
        if char == "#" and not in_string:
            return line[:index]
    return line


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
    in_string = False
    for char in line:
        if char == '"':
            in_string = not in_string
        if in_string:
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
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
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
        elif not in_string:
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
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char in "({[":
                stack.append({ "(": ")", "{": "}", "[": "]" }[char])
            elif stack and char == stack[-1]:
                stack.pop()
            elif not stack and text.startswith(separator, index):
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
    raise CompileError(f"unclosed {open_char}")


def find_next_module_start(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        char = text[index]
        if char in {"∀", "∃"} and index + 1 < len(text) and text[index + 1] == "{":
            return index
        if char == "{":
            return index
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
    return re.fullmatch(r"[^\W\d]\w*'?", text, flags=re.UNICODE) is not None


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
    for index, char in enumerate(text):
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == ":":
            previous_char = text[index - 1] if index > 0 else ""
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if previous_char == ":" or next_char == ":":
                continue
            return index
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


def format_lark_error(error: Any) -> str:
    line = getattr(error, "line", None)
    column = getattr(error, "column", None)
    if line is not None and column is not None:
        return f"{line}:{column}: parse error"
    return "parse error"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile logic-language module text to JSON.")
    parser.add_argument("--text", help="module text to compile; defaults to stdin")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    parser.add_argument("--readable", action="store_true", help="emit compact readable JSON output")
    args = parser.parse_args()

    source = args.text if args.text is not None else sys.stdin.read()
    try:
        tokens = load_tokens()
        module = compile_module_text(source, args.base_dir)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    output_tokens = make_output_tokens(tokens)
    output = module.to_readable_json(output_tokens) if args.readable else module.to_json(output_tokens)
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
