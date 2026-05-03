"""Source-level normalization and literal utilities for the compiler pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compile_pipeline.errors import CompileError

try:
    from lark import Lark, UnexpectedInput
except ModuleNotFoundError:  # pragma: no cover - exercised by CLI environments.
    Lark = None  # type: ignore[assignment]
    UnexpectedInput = Exception  # type: ignore[assignment]


LATEX_CODE_RE = re.compile(r"\\[A-Za-z_][A-Za-z0-9_]*")
IMPORT_RE = re.compile(r"^(?P<indent>[ \t]*)\$import\s+(?P<path>.+?)\s*$")
BASIC_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "\\": "\\",
    '"': '"',
    "'": "'",
}
ESCAPE_OUTPUTS = {
    "\n": r"\n",
    "\r": r"\r",
    "\t": r"\t",
    "\\": r"\\",
    "'": r"\'",
}


@dataclass(frozen=True)
class LiteralValue:
    kind: str
    value: str
    raw: str


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[2]


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


def normalize_latex(text: str, tokens: dict[str, str]) -> str:
    output: list[str] = []
    keys = sorted(tokens, key=len, reverse=True)
    index = 0
    while index < len(text):
        if is_literal_quote_start(text, index):
            end = find_quoted_literal_end(text, index)
            output.append(normalize_literal_latex(text[index : end + 1], tokens, keys))
            index = end + 1
            continue
        if text[index] == "#":
            end = text.find("\n", index)
            if end == -1:
                output.append(text[index:])
                break
            output.append(text[index:end])
            index = end
            continue
        matched_key = next((key for key in keys if text.startswith(key, index)), None)
        if matched_key is not None:
            output.append(tokens[matched_key])
            index += len(matched_key)
            continue
        if text[index] == "\\":
            match = LATEX_CODE_RE.match(text, index)
            if match is not None:
                line, column = line_column(text, match.start())
                raise CompileError(f"{line}:{column}: unknown latex code {match.group(0)}")
        output.append(text[index])
        index += 1
    return "".join(output)


def normalize_literal_latex(text: str, tokens: dict[str, str], keys: list[str] | None = None) -> str:
    if is_raw_string_literal_start(text, 0):
        return text
    quote_index = literal_quote_index(text, 0)
    if quote_index is None:
        return text
    keys = sorted(tokens, key=len, reverse=True) if keys is None else keys
    output = [text[: quote_index + 1]]
    index = quote_index + 1
    end = len(text) - 1
    while index < end:
        if text[index] == "\\":
            escape = text[index + 1] if index + 1 < end else ""
            if escape in BASIC_ESCAPES:
                output.append(text[index : index + 2])
                index += 2
                continue
            matched_key = next((key for key in keys if text.startswith(key, index)), None)
            if matched_key is not None:
                output.append(tokens[matched_key])
                index += len(matched_key)
                continue
            match = LATEX_CODE_RE.match(text, index)
            if match is not None:
                output.append(match.group(0))
                index = match.end()
                continue
        output.append(text[index])
        index += 1
    output.append(text[-1])
    return "".join(output)


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


def remove_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(strip_comment(line).rstrip())
    return "\n".join(lines)


def strip_comment(line: str) -> str:
    index = 0
    while index < len(line):
        if is_literal_quote_start(line, index):
            index = find_quoted_literal_end(line, index) + 1
            continue
        if line[index] == "#":
            return line[:index]
        index += 1
    return line


def find_quoted_literal_end(text: str, start: int) -> int:
    quote_index = literal_quote_index(text, start)
    if quote_index is None:
        raise CompileError("expected quoted literal")
    quote = text[quote_index]
    kind = "string" if quote == '"' else "char"
    index = quote_index + 1
    raw = is_raw_string_literal_start(text, start)
    while index < len(text):
        char = text[index]
        if not raw and char == "\\":
            index += 2
            continue
        if raw and char == "\\":
            index += 1
            continue
        if char == quote and (not raw or not is_escaped_quote(text, index)):
            return index
        if char == "\n":
            raise CompileError(f"unterminated {kind} literal")
        index += 1
    raise CompileError(f"unterminated {kind} literal")


def decode_literal_body(body: str, *, allow_unknown_escapes: bool = True) -> str:
    output: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(body):
            raise CompileError("unterminated escape sequence")
        escape = body[index + 1]
        if escape not in BASIC_ESCAPES:
            if allow_unknown_escapes:
                output.append("\\" + escape)
                index += 2
                continue
            raise CompileError(f"invalid escape sequence \\{escape}")
        output.append(BASIC_ESCAPES[escape])
        index += 2
    return "".join(output)


def parse_literal_text(text: str) -> LiteralValue | None:
    if len(text) < 2:
        return None
    quote_index = literal_quote_index(text, 0)
    if quote_index is None or text[-1] != text[quote_index]:
        return None
    quote = text[quote_index]
    if find_quoted_literal_end(text, 0) != len(text) - 1:
        return None
    if is_raw_string_literal_start(text, 0):
        return LiteralValue(kind="string", value=text[quote_index + 1 : -1], raw=text)
    value = decode_literal_body(text[quote_index + 1 : -1], allow_unknown_escapes=quote == '"')
    if quote == "'":
        if len(value) != 1:
            raise CompileError("char literal must contain exactly one character")
        return LiteralValue(kind="char", value=value, raw=text)
    return LiteralValue(kind="string", value=value, raw=text)


def is_literal_text(text: str) -> bool:
    return parse_literal_text(text.strip()) is not None


def encode_char_literal(value: str) -> str:
    if len(value) != 1:
        raise CompileError("char literal must contain exactly one character")
    return "'" + ESCAPE_OUTPUTS.get(value, value) + "'"


def is_literal_quote_start(text: str, index: int) -> bool:
    if index >= len(text):
        return False
    if is_raw_string_literal_start(text, index):
        return True
    quote = text[index]
    if quote == '"':
        return True
    if quote != "'":
        return False
    previous = text[index - 1] if index > 0 else ""
    if previous.isalnum() or previous == "_" or previous == "$":
        return False
    return True


def is_raw_string_literal_start(text: str, index: int) -> bool:
    if index + 1 >= len(text) or text[index] not in {"r", "R"} or text[index + 1] != '"':
        return False
    previous = text[index - 1] if index > 0 else ""
    return not (previous.isalnum() or previous == "_" or previous == "$")


def literal_quote_index(text: str, start: int) -> int | None:
    if start >= len(text):
        return None
    if is_raw_string_literal_start(text, start):
        return start + 1
    if text[start] in {'"', "'"}:
        return start
    return None


def is_escaped_quote(text: str, quote_index: int) -> bool:
    backslash_count = 0
    index = quote_index - 1
    while index >= 0 and text[index] == "\\":
        backslash_count += 1
        index -= 1
    return backslash_count % 2 == 1


def format_lark_error(error: Any) -> str:
    line = getattr(error, "line", None)
    column = getattr(error, "column", None)
    if line is not None and column is not None:
        return f"{line}:{column}: parse error"
    return "parse error"
