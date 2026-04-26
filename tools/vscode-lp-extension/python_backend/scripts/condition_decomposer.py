from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from semantic_parser import (
        ParserError,
        TokenizerError,
        condition_to_source,
        parse_condition_text,
    )
except ImportError:  # pragma: no cover - module execution fallback
    from .semantic_parser import (
        ParserError,
        TokenizerError,
        condition_to_source,
        parse_condition_text,
    )


def condition_decomposer(condition: str) -> list[str]:
    condition_node = parse_condition_text(condition)
    return [condition_to_source(item) for item in condition_node.decompose()]


def _read_condition_source(argument: str | None, *, force_file: bool) -> str:
    if argument is None or argument == "-":
        return sys.stdin.read()

    path = Path(argument)
    if force_file or path.exists():
        return path.read_text(encoding="utf-8")

    return argument


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Decompose a logic-language condition by fully flattening branch and "
            "target clauses."
        )
    )
    parser.add_argument(
        "condition",
        nargs="?",
        help="Condition text, a path to a file containing one condition, or '-' for stdin.",
    )
    parser.add_argument(
        "--file",
        action="store_true",
        help="Interpret the positional argument as a file path even if it does not exist yet.",
    )
    args = parser.parse_args(argv)

    try:
        source = _read_condition_source(args.condition, force_file=args.file)
        for index, text in enumerate(condition_decomposer(source)):
            if index:
                print()
            print(text)
    except (OSError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
