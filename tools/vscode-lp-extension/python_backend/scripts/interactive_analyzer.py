from __future__ import annotations

import argparse
import shlex
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

try:
    from semantic_parser import (
        AttributeExpr,
        BinaryExpr,
        Comment,
        Declaration,
        ExpressionStatement,
        Heading,
        ParserError,
        Program,
        Statement,
        TokenizerError,
        _build_semantic_index,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _resolve_relation_expression,
        _scoped_block_owner_class,
        build_class_inheritance_graph,
        parse_program_text,
        program_to_source,
    )
except ImportError:  # pragma: no cover - module execution fallback
    from .semantic_parser import (
        AttributeExpr,
        BinaryExpr,
        Comment,
        Declaration,
        ExpressionStatement,
        Heading,
        ParserError,
        Program,
        Statement,
        TokenizerError,
        _build_semantic_index,
        _declaration_owner_class,
        _extract_member_owner_and_name,
        _resolve_relation_expression,
        _scoped_block_owner_class,
        build_class_inheritance_graph,
        parse_program_text,
        program_to_source,
    )


def _format_names(names: Iterable[str]) -> str:
    items = tuple(sorted(set(names)))
    if not items:
        return "(none)"
    return ", ".join(items)


def _indent_block(text: str, *, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.splitlines())


def _expression_member_name(expression) -> str | None:
    if isinstance(expression, AttributeExpr) and expression.base is None:
        return expression.attribute
    if isinstance(expression, BinaryExpr):
        return _expression_member_name(expression.left)
    return None


class LogicProgramAnalyzer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.source = path.read_text(encoding="utf-8")
        self.root = parse_program_text(self.source, source_name=str(path))
        self.semantic_index = _build_semantic_index(self.root)
        self.class_graph = build_class_inheritance_graph(self.root)
        self.class_conditions_by_class: dict[str, list[Statement]] = defaultdict(list)
        self.member_statements_by_key: dict[tuple[str, str], list[Statement]] = defaultdict(list)
        self._collect_from_block(self.root.items, current_class=None)

    def class_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.semantic_index.class_names))

    def ensure_class(self, class_name: str) -> None:
        if class_name in self.semantic_index.class_names:
            return
        raise ValueError(
            f"unknown class {class_name!r}; available classes: {_format_names(self.class_names())}"
        )

    def show_class_inheritance_graph(self, class_name: str | None = None) -> str:
        if class_name is None:
            relations = self.class_graph.relations()
            if not relations:
                return "(none)"
            return "\n".join(f"{parent}~{child}" for parent, child in relations)

        self.ensure_class(class_name)
        relation = self.class_graph.relation_for(class_name)
        lines = [
            f"class: {relation.class_name}",
            f"direct_parent_classes: {_format_names(relation.direct_parent_classes)}",
            f"parent_classes: {_format_names(relation.parent_classes)}",
            f"direct_sub_classes: {_format_names(relation.direct_sub_classes)}",
            f"sub_classes: {_format_names(relation.sub_classes)}",
        ]
        return "\n".join(lines)

    def show_class(self, class_name: str, *, full: bool) -> str:
        self.ensure_class(class_name)
        relation = self.class_graph.relation_for(class_name)
        direct_members = tuple(
            sorted(self.semantic_index.member_names_by_class.get(class_name, set()))
        )
        inherited_only = tuple(
            sorted(
                {
                    member_name
                    for owner in relation.parent_classes
                    for member_name in self.semantic_index.member_names_by_class.get(
                        owner, set()
                    )
                }
                - set(direct_members)
            )
        )

        lines = [
            f"class: {class_name}",
            f"direct_parent_classes: {_format_names(relation.direct_parent_classes)}",
            f"parent_classes: {_format_names(relation.parent_classes)}",
            f"direct_sub_classes: {_format_names(relation.direct_sub_classes)}",
            f"sub_classes: {_format_names(relation.sub_classes)}",
            f"declared_members: {_format_names(direct_members)}",
            f"inherited_members: {_format_names(inherited_only)}",
        ]
        if not full:
            return "\n".join(lines)

        lines.append("")
        lines.append("class_conditions:")
        lines.extend(self._format_class_conditions(class_name, relation.parent_classes))
        lines.append("")
        lines.append("member_definitions:")
        lines.extend(self._format_member_definitions(class_name, relation.parent_classes))
        return "\n".join(lines)

    def _collect_from_block(
        self,
        items: list[Statement],
        *,
        current_class: str | None,
    ) -> None:
        for item in items:
            if isinstance(item, Heading):
                self._collect_from_block(item.body, current_class=current_class)
                continue

            if isinstance(item, Comment):
                continue

            if isinstance(item, Declaration):
                owner_class = _declaration_owner_class(item, current_class=current_class)
                if owner_class is not None:
                    _, member_name = _extract_member_owner_and_name(
                        item.head,
                        current_class=owner_class,
                    )
                    if item.head is None:
                        member_name = "call"
                    if member_name is not None:
                        self.member_statements_by_key[(owner_class, member_name)].append(item)
                continue

            if isinstance(item, ExpressionStatement):
                scoped_owner = _scoped_block_owner_class(
                    item.expression,
                    item.body,
                    self.semantic_index,
                )
                if scoped_owner is not None:
                    self._collect_from_block(item.body, current_class=scoped_owner)
                    continue

                if current_class is None:
                    continue

                member_name = _expression_member_name(item.expression)
                if member_name is not None:
                    self.member_statements_by_key[(current_class, member_name)].append(item)
                    continue

                if not self._is_class_relation_statement(item.expression):
                    self.class_conditions_by_class[current_class].append(item)
                continue

            if current_class is not None:
                self.class_conditions_by_class[current_class].append(item)

    def _is_class_relation_statement(self, expression) -> bool:
        if not isinstance(expression, BinaryExpr):
            return False
        relation = _resolve_relation_expression(expression, self.semantic_index)
        return relation is not None and relation[0] == "class_inheritance"

    def _format_class_conditions(
        self,
        class_name: str,
        parent_classes: tuple[str, ...],
    ) -> list[str]:
        lines: list[str] = []
        for owner in (class_name, *parent_classes):
            conditions = self.class_conditions_by_class.get(owner, [])
            if not conditions:
                continue
            label = "declared" if owner == class_name else f"inherited from {owner}"
            lines.append(f"{owner} ({label})")
            for statement in conditions:
                lines.append(_indent_block(program_to_source(statement)))
        if not lines:
            lines.append("(none)")
        return lines

    def _format_member_definitions(
        self,
        class_name: str,
        parent_classes: tuple[str, ...],
    ) -> list[str]:
        lines: list[str] = []
        all_owner_classes = (class_name, *parent_classes)
        all_member_names = sorted(
            {
                member_name
                for owner in all_owner_classes
                for member_name in self.semantic_index.member_names_by_class.get(
                    owner, set()
                )
            }
        )
        if not all_member_names:
            return ["(none)"]

        for member_name in all_member_names:
            owners = [
                owner
                for owner in all_owner_classes
                if member_name in self.semantic_index.member_names_by_class.get(owner, set())
            ]
            origin = "declared" if class_name in owners else "inherited"
            lines.append(f"{member_name} ({origin}; owners: {', '.join(owners)})")
            for owner in owners:
                statements = self.member_statements_by_key.get((owner, member_name), [])
                if not statements:
                    continue
                lines.append(f"  [{owner}]")
                for statement in statements:
                    lines.append(_indent_block(program_to_source(statement), prefix="    "))
            if owners:
                lines.append("")

        if lines and lines[-1] == "":
            lines.pop()
        return lines


def _print_help() -> None:
    print("commands:")
    print("  help")
    print("  quit")
    print("  exit")
    print("  show-class-inheritance-graph")
    print("  show-class-inheritance-graph <class>")
    print("  show-class <class>")
    print("  show-class -full <class>")


def _dispatch_command(analyzer: LogicProgramAnalyzer, line: str) -> bool:
    parts = shlex.split(line)
    if not parts:
        return False

    command = parts[0]
    if command in {"quit", "exit"}:
        return True

    if command in {"help", "?"}:
        _print_help()
        return False

    if command == "show-class-inheritance-graph":
        if len(parts) == 1:
            print(analyzer.show_class_inheritance_graph())
            return False
        if len(parts) == 2:
            print(analyzer.show_class_inheritance_graph(parts[1]))
            return False
        raise ValueError("usage: show-class-inheritance-graph [class]")

    if command == "show-class":
        full = False
        arguments = parts[1:]
        if "-full" in arguments:
            full = True
            arguments = [argument for argument in arguments if argument != "-full"]
        if len(arguments) != 1:
            raise ValueError("usage: show-class [-full] <class>")
        print(analyzer.show_class(arguments[0], full=full))
        return False

    raise ValueError(f"unknown command {command!r}; type 'help' for commands")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Interactive analyzer for .lp logic programs."
    )
    parser.add_argument("logic_program", help="Path to the input .lp file.")
    args = parser.parse_args(argv)

    path = Path(args.logic_program)
    try:
        analyzer = LogicProgramAnalyzer(path)
    except (OSError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"loaded: {path}")
    print(f"classes: {len(analyzer.class_names())}")
    print("type 'help' for commands")

    while True:
        try:
            line = input("logic-analyzer> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue

        try:
            should_exit = _dispatch_command(analyzer, line.strip())
        except ValueError as exc:
            print(exc, file=sys.stderr)
            continue

        if should_exit:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
