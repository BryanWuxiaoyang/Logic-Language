from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    line: int
    column: int


TokenStream = list[Token]

_MULTI_CHAR_SYMBOLS: Final[tuple[str, ...]] = (
    ":=:",
    "=>",
    "::",
    "|-",
    "->",
    "&&",
    "||",
    ">=",
    "<=",
    "!=",
    "==",
)
_SINGLE_CHAR_SYMBOLS: Final[set[str]] = {
    "{",
    "}",
    "(",
    ")",
    "[",
    "]",
    ",",
    ".",
    ":",
    ";",
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "^",
    "~",
    "<",
    ">",
    "!",
    "|",
    "∀",
    "∃",
    "∈",
    "∉",
    "⊆",
    "⊂",
    "⊈",
    "⊄",
    "∪",
    "∩",
    "≤",
    "≥",
    "≠",
    "→",
    "⇒",
}
_ESCAPE_SEQUENCES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class TokenizerError(SyntaxError):
    """Raised when a `.lp` source file cannot be tokenized."""


def tokenizer(logic_program_path: str) -> TokenStream:
    source_path = Path(logic_program_path)
    source_text = source_path.read_text(encoding="utf-8")
    return tokenize_text(source_text, source_name=str(source_path))


def tokenize_text(logic_program: str, *, source_name: str = "<string>") -> TokenStream:
    tokens: TokenStream = []
    indent_stack = [0]
    lines = logic_program.splitlines()

    for line_number, raw_line in enumerate(lines, start=1):
        indent = _leading_spaces(raw_line, source_name, line_number)
        content = raw_line[indent:]
        if not content.strip():
            continue

        tokens.extend(_indent_tokens(indent_stack, indent, source_name, line_number))

        if content.startswith("@"):
            tokens.append(Token("HEADING", content[1:].strip(), line_number, indent + 1))
        elif content.startswith("$"):
            directive_text = content[1:].strip()
            if directive_text == "import" or directive_text.startswith("import "):
                import_text = directive_text[len("import") :].lstrip()
                if not import_text:
                    _raise_tokenizer_error(
                        source_name,
                        line_number,
                        indent + 1,
                        "import path must not be empty",
                    )
                if import_text.startswith("{") and import_text.endswith("}"):
                    _raise_tokenizer_error(
                        source_name,
                        line_number,
                        indent + 1,
                        "import path must not use braces; use '$import module_path'",
                    )
                tokens.append(Token("IMPORT", import_text, line_number, indent + 1))
            else:
                directive_name = directive_text.split(None, 1)[0] if directive_text else ""
                if directive_name:
                    message = f"unknown directive '${directive_name}'; use '$import'"
                else:
                    message = "unknown directive '$'; use '$import'"
                _raise_tokenizer_error(
                    source_name,
                    line_number,
                    indent + 1,
                    message,
                )
        else:
            tokens.extend(
                _tokenize_content(
                    content=content,
                    line_number=line_number,
                    start_column=indent + 1,
                    source_name=source_name,
                )
            )

        tokens.append(Token("NEWLINE", "", line_number, len(raw_line) + 1))

    final_line = len(lines) + 1
    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token("DEDENT", "", final_line, 1))

    tokens.append(Token("EOF", "", final_line, 1))
    return tokens


def _leading_spaces(raw_line: str, source_name: str, line_number: int) -> int:
    indent = 0
    while indent < len(raw_line) and raw_line[indent].isspace():
        if raw_line[indent] == "\t":
            _raise_tokenizer_error(
                source_name,
                line_number,
                indent + 1,
                "tabs are not allowed for indentation",
            )
        indent += 1
    return indent


def _indent_tokens(
    indent_stack: list[int],
    indent: int,
    source_name: str,
    line_number: int,
) -> TokenStream:
    if indent == indent_stack[-1]:
        return []

    if indent > indent_stack[-1]:
        indent_stack.append(indent)
        return [Token("INDENT", "", line_number, 1)]

    tokens: TokenStream = []
    while indent < indent_stack[-1]:
        indent_stack.pop()
        tokens.append(Token("DEDENT", "", line_number, 1))

    if indent != indent_stack[-1]:
        _raise_tokenizer_error(
            source_name,
            line_number,
            1,
            f"inconsistent indentation: got {indent} spaces",
        )

    return tokens


def _tokenize_content(
    *,
    content: str,
    line_number: int,
    start_column: int,
    source_name: str,
) -> TokenStream:
    tokens: TokenStream = []
    index = 0

    while index < len(content):
        char = content[index]
        column = start_column + index

        if char == "\t":
            _raise_tokenizer_error(source_name, line_number, column, "tabs are not allowed")

        if char == "｜":
            _raise_tokenizer_error(
                source_name,
                line_number,
                column,
                "full-width separator '｜' is not allowed; use ASCII '|'",
            )

        if char.isspace():
            index += 1
            continue

        if char == "#":
            tokens.append(Token("COMMENT", content[index + 1 :].strip(), line_number, column))
            break

        if char == '"':
            literal, next_index = _read_string(
                content,
                start_index=index,
                line_number=line_number,
                source_name=source_name,
                start_column=start_column,
            )
            tokens.append(Token("STRING", literal, line_number, column))
            index = next_index
            continue

        symbol = _match_multi_char_symbol(content, index)
        if symbol is not None:
            tokens.append(Token("SYMBOL", symbol, line_number, column))
            index += len(symbol)
            continue

        if char in _SINGLE_CHAR_SYMBOLS:
            tokens.append(Token("SYMBOL", char, line_number, column))
            index += 1
            continue

        if _is_custom_symbol_char(char):
            tokens.append(Token("SYMBOL", char, line_number, column))
            index += 1
            continue

        if char.isdigit():
            number, next_index = _read_number(content, index)
            tokens.append(Token("NUMBER", number, line_number, column))
            index = next_index
            continue

        if _is_identifier_start(char):
            identifier, next_index = _read_identifier(content, index)
            tokens.append(Token("IDENT", identifier, line_number, column))
            index = next_index
            continue

        _raise_tokenizer_error(
            source_name,
            line_number,
            column,
            f"unsupported character {char!r}",
        )

    return tokens


def _read_string(
    content: str,
    *,
    start_index: int,
    line_number: int,
    source_name: str,
    start_column: int,
) -> tuple[str, int]:
    index = start_index + 1
    chars: list[str] = []

    while index < len(content):
        char = content[index]

        if char == "\\":
            if index + 1 >= len(content):
                _raise_tokenizer_error(
                    source_name,
                    line_number,
                    start_column + index,
                    "unterminated escape sequence",
                )

            escaped = content[index + 1]
            chars.append(_ESCAPE_SEQUENCES.get(escaped, escaped))
            index += 2
            continue

        if char == '"':
            return "".join(chars), index + 1

        chars.append(char)
        index += 1

    _raise_tokenizer_error(
        source_name,
        line_number,
        start_column + start_index,
        "unterminated string literal",
    )


def _read_number(content: str, start_index: int) -> tuple[str, int]:
    index = start_index
    while index < len(content) and content[index].isdigit():
        index += 1

    if index + 1 < len(content) and content[index] == "." and content[index + 1].isdigit():
        index += 1
        while index < len(content) and content[index].isdigit():
            index += 1

    return content[start_index:index], index


def _read_identifier(content: str, start_index: int) -> tuple[str, int]:
    if content[start_index] == "\\":
        index = start_index + 1
        while index < len(content) and (
            content[index].isalnum() or content[index] == "_" or content[index] == "'"
        ):
            index += 1
        return content[start_index:index], index

    index = start_index + 1
    while index < len(content) and _is_identifier_part(content[index]):
        index += 1

    return content[start_index:index], index


def _match_multi_char_symbol(content: str, start_index: int) -> str | None:
    for symbol in _MULTI_CHAR_SYMBOLS:
        if content.startswith(symbol, start_index):
            return symbol
    return None


def _is_custom_symbol_char(char: str) -> bool:
    if len(char) != 1 or char.isascii():
        return False
    if char.isspace() or char in {'"', "#", "@", "$"}:
        return False
    return not char.isalpha() and not char.isdigit() and char != "_"


def _is_identifier_start(char: str) -> bool:
    return char in {"_", "\\"} or (char.isalnum() and not char.isdigit())


def _is_identifier_part(char: str) -> bool:
    return char == "_" or char.isalnum() or char == "'"


def _raise_tokenizer_error(
    source_name: str,
    line_number: int,
    column: int,
    message: str,
) -> None:
    raise TokenizerError(f"{source_name}:{line_number}:{column}: {message}")


def _format_token(token: Token) -> str:
    return f"{token.line}:{token.column} {token.kind} {token.value!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tokenize a .lp logic program and print its token stream."
    )
    parser.add_argument("logic_program", help="Path to the input .lp file.")
    args = parser.parse_args(argv)

    try:
        tokens = tokenizer(args.logic_program)
    except TokenizerError as exc:
        print(exc, file=sys.stderr)
        return 1

    for token in tokens:
        print(_format_token(token))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
