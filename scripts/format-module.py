#!/usr/bin/env python3
"""Replace latex-code tokens in a logic-language module file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


LATEX_CODE_RE = re.compile(r"\\[A-Za-z_][A-Za-z0-9_]*")


def load_tokens(script_path: Path) -> dict[str, str]:
    skill_dir = script_path.resolve().parents[1]
    token_path = skill_dir / "latex-tokens.json"
    with token_path.open(encoding="utf-8") as token_file:
        tokens = json.load(token_file)

    invalid_keys = [key for key in tokens if not key.startswith("\\")]
    if invalid_keys:
        joined = ", ".join(sorted(invalid_keys))
        raise ValueError(f"latex token keys must start with backslash: {joined}")

    return tokens


def replace_tokens(text: str, tokens: dict[str, str]) -> str:
    formatted = text
    for key in sorted(tokens, key=len, reverse=True):
        formatted = formatted.replace(key, tokens[key])
    return formatted


def find_unknown_codes(text: str) -> list[tuple[int, int, str]]:
    unknowns: list[tuple[int, int, str]] = []
    line_starts = [0]
    for match in re.finditer(r"\n", text):
        line_starts.append(match.end())

    for match in LATEX_CODE_RE.finditer(text):
        offset = match.start()
        line_number = 1
        for index, line_start in enumerate(line_starts):
            if line_start > offset:
                break
            line_number = index + 1
        column = offset - line_starts[line_number - 1] + 1
        unknowns.append((line_number, column, match.group(0)))
    return unknowns


def format_module_file(module_path: Path, tokens: dict[str, str]) -> int:
    original = module_path.read_text(encoding="utf-8")
    formatted = replace_tokens(original, tokens)
    unknowns = find_unknown_codes(formatted)
    if unknowns:
        for line, column, code in unknowns:
            print(f"{module_path}:{line}:{column}: unknown latex code {code}", file=sys.stderr)
        return 1

    if formatted != original:
        module_path.write_text(formatted, encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace latex-code tokens in a logic-language module file in place."
    )
    parser.add_argument("module_file", type=Path)
    args = parser.parse_args()

    try:
        tokens = load_tokens(Path(__file__))
        return format_module_file(args.module_file, tokens)
    except OSError as error:
        print(f"{error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
