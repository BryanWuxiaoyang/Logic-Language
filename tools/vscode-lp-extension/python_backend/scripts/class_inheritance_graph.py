from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from semantic_parser import (
        ParserError,
        TokenizerError,
        build_class_inheritance_graph,
        parse_program_text,
    )
except ImportError:  # pragma: no cover - module execution fallback
    from .semantic_parser import (
        ParserError,
        TokenizerError,
        build_class_inheritance_graph,
        parse_program_text,
    )


def class_inheritance_graph(logic_program: str):
    root_node = parse_program_text(logic_program)
    return build_class_inheritance_graph(root_node)


def _read_logic_program_source(argument: str | None, *, force_file: bool) -> str:
    if argument is None or argument == "-":
        return sys.stdin.read()

    path = Path(argument)
    if force_file or path.exists():
        return path.read_text(encoding="utf-8")

    return argument


def _format_names(names: tuple[str, ...]) -> str:
    if not names:
        return "(none)"
    return ", ".join(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze class inheritance relations in a .lp program and dump either "
            "all direct edges or the relation closure for one class."
        )
    )
    parser.add_argument(
        "logic_program",
        nargs="?",
        help="Logic program text, a path to a .lp file, or '-' for stdin.",
    )
    parser.add_argument(
        "--file",
        action="store_true",
        help="Interpret the positional argument as a file path even if it does not exist yet.",
    )
    parser.add_argument(
        "--class",
        dest="class_name",
        help="Show parent-classes and sub-classes for one class name.",
    )
    args = parser.parse_args(argv)

    try:
        source = _read_logic_program_source(args.logic_program, force_file=args.file)
        graph = class_inheritance_graph(source)
    except (OSError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.class_name:
        relation = graph.relation_for(args.class_name)
        print(f"class: {relation.class_name}")
        print(
            f"direct_parent_classes: {_format_names(relation.direct_parent_classes)}"
        )
        print(f"parent_classes: {_format_names(relation.parent_classes)}")
        print(f"direct_sub_classes: {_format_names(relation.direct_sub_classes)}")
        print(f"sub_classes: {_format_names(relation.sub_classes)}")
        return 0

    for parent_class, child_class in graph.relations():
        print(f"{parent_class}~{child_class}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
