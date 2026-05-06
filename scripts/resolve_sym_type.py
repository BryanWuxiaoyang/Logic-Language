#!/usr/bin/env python3
"""Resolve logic-language source symbol occurrences to semantic symbol types."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from compile_module import run_compile_pipeline
from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import (
    is_generated_sym_name,
    is_plain_sym,
    parse_declaration,
    parse_premise_declaration,
)
from compile_pipeline.source_utils import find_quoted_literal_end, is_literal_quote_start, load_tokens
from inheritance_sources import inheritance_candidate_chain
from syntax_check_common import (
    CheckError,
    LocatedText,
    analyze_module_text,
    expand_for_checking,
    logical_lines_located,
    make_located_text,
    normalize_latex_located,
    parse_binder_list_located,
    remove_comments_located,
    split_indent_located,
    split_lines_located,
    split_top_level_located,
    strip_leading_bom,
)

STDIN_FILE = "__stdin__"
CLASSIFIER_FUNCTION = "Function"
CLASSIFIER_PREDICATE = "Predicate"
OPERATOR_NAMES = {
    "∀",
    "∃",
    "=",
    "~",
    "+",
    "-",
    "*",
    "/",
    "<",
    "<=",
    ">",
    ">=",
    "!=",
    "≠",
    "≤",
    "≥",
    "∈",
    "∉",
    "⊂",
    "⊄",
    "⊆",
    "⊈",
    "∪",
    "∩",
    "∧",
    "∨",
    "&&",
    "||",
    "!",
    "[]",
    "[:]",
}
NORMALIZED_OPERATOR_ALIASES = {
    "!=": {"≠"},
    "≠": {"!="},
    "<=": {"≤"},
    "≤": {"<="},
    ">=": {"≥"},
    "≥": {">="},
}
STRUCTURAL_TOKENS = ("=>", "::", "->", "|-")
STRUCTURAL_CHARS = {":", ".", "|"}
SOURCE_OPERATORS = sorted(
    [
        "[:]",
        "[]",
        "&&",
        "||",
        "!=",
        "≠",
        "≤",
        "<=",
        "≥",
        ">=",
        "∈",
        "∉",
        "⊂",
        "⊄",
        "⊆",
        "⊈",
        "∪",
        "∩",
        "∧",
        "∨",
        "=",
        "~",
        "+",
        "-",
        "*",
        "/",
        "<",
        ">",
        "!",
    ],
    key=len,
    reverse=True,
)
IDENTIFIER_RE = re.compile(r"[^\W\d]\w*'*", flags=re.UNICODE)


@dataclass(frozen=True)
class Occurrence:
    file: str
    lineno: int
    col_start_no: int
    col_end_no: int
    name: str
    member_receiver: str | None = None


@dataclass(frozen=True)
class Definition:
    file: str
    lineno: int
    col_start_no: int
    col_end_no: int
    name: str
    type: str
    order: int
    rank: int = 0
    kind: str = "generic"
    owner_class: str | None = None


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, name: str) -> str:
        parent = self.parent.setdefault(name, name)
        if parent != name:
            self.parent[name] = self.find(parent)
        return self.parent[name]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root

    def groups(self) -> dict[str, set[str]]:
        grouped: dict[str, set[str]] = {}
        for name in list(self.parent):
            grouped.setdefault(self.find(name), set()).add(name)
        return grouped


def empty_payload() -> dict[str, Any]:
    return {"summary": {"symbol_count": 0, "occurrence_count": 0}, "symbols": [], "occurrences": []}


def resolve_text(
    text: str,
    *,
    file_label: str = STDIN_FILE,
    base_dir: Path | str = ".",
) -> dict[str, Any]:
    base_path = Path(base_dir).resolve()
    try:
        analyze_module_text(text, source_label=file_label, base_dir=base_path)
        ast = run_compile_pipeline(text, base_path, source=file_label, allow_imports=True).ast
        expanded = located_import_expansion(text, file_label, base_path)
    except (CheckError, CompileError, OSError, ValueError):
        return empty_payload()

    evidence = collect_type_evidence(ast)
    definitions = collect_definitions(expanded, evidence, ast)
    occurrences = scan_source_occurrences(text, file_label)
    return build_payload(occurrences, evidence, definitions)


def resolve_file(file_path: Path) -> dict[str, Any]:
    absolute = file_path.resolve()
    return resolve_text(
        absolute.read_text(encoding="utf-8"),
        file_label=str(absolute),
        base_dir=absolute.parent,
    )


def collect_type_evidence(ast: dict[str, Any]) -> dict[str, set[str]]:
    aliases = DisjointSet()
    func_evidence: set[str] = set()
    pred_evidence: set[str] = set()
    class_evidence: set[str] = set()
    inheritance_facts: list[tuple[str, str]] = []

    for node in walk_ast(ast):
        if node.get("kind") == "sym":
            name = node.get("name")
            if isinstance(name, str) and name and is_capital_head(name):
                class_evidence.add(name)
                aliases.find(name)
    collect_module_evidence(ast, func_evidence, pred_evidence, class_evidence, aliases, inheritance_facts)

    groups = aliases.groups()
    predicate_classes = alias_closure(CLASSIFIER_PREDICATE, groups)
    function_classes = alias_closure(CLASSIFIER_FUNCTION, groups)
    for class_name, source_name in inheritance_facts:
        class_aliases = aliases_for(class_name, groups)
        if class_aliases & predicate_classes:
            pred_evidence.add(source_name)
        if class_aliases & function_classes:
            func_evidence.add(source_name)

    return {
        "pred": expand_operator_aliases(expand_with_aliases(pred_evidence, groups)),
        "func": expand_operator_aliases(expand_with_aliases(func_evidence, groups)),
        "class": expand_with_aliases(class_evidence, groups),
    }


def collect_module_evidence(
    node: Any,
    func_evidence: set[str],
    pred_evidence: set[str],
    class_evidence: set[str],
    aliases: DisjointSet,
    inheritance_facts: list[tuple[str, str]],
) -> None:
    if not isinstance(node, dict):
        return
    if node.get("kind") not in {"quantified_stmt", "set_stmt"}:
        return
    for binding in node.get("premise_binding_stmts", []):
        if not isinstance(binding, dict):
            continue
        src = binding.get("src_stmt")
        if isinstance(src, dict) and src.get("kind") in {"quantified_stmt", "set_stmt"}:
            collect_module_evidence(src, func_evidence, pred_evidence, class_evidence, aliases, inheritance_facts)
        elif isinstance(src, dict):
            collect_function_call_heads(src, func_evidence, aliases)
    for statement in [*node.get("premise_PSs", []), *node.get("target_PSs", [])]:
        collect_predicate_statement_evidence(statement, func_evidence, pred_evidence, class_evidence, aliases, inheritance_facts)


def collect_predicate_statement_evidence(
    node: Any,
    func_evidence: set[str],
    pred_evidence: set[str],
    class_evidence: set[str],
    aliases: DisjointSet,
    inheritance_facts: list[tuple[str, str]],
) -> None:
    if not isinstance(node, dict):
        return
    if node.get("kind") in {"quantified_stmt", "set_stmt"}:
        collect_module_evidence(node, func_evidence, pred_evidence, class_evidence, aliases, inheritance_facts)
        return
    if node.get("kind") != "func_stmt":
        return
    call_name = sym_name(node.get("call_sym"))
    args = [sym_name(arg) for arg in node.get("arg_sym_list", [])]
    if call_name:
        pred_evidence.add(call_name)
        aliases.find(call_name)
    if call_name == "=" and len(args) == 2 and args[0] and args[1]:
        aliases.union(args[0], args[1])
    if call_name == "~" and len(args) == 2 and args[0] and args[1]:
        class_name, source_name = args
        inheritance_facts.append((class_name, source_name))
        if is_capital_head(class_name):
            class_evidence.add(class_name)
        if is_capital_head(source_name):
            class_evidence.add(source_name)


def collect_function_call_heads(node: Any, output: set[str], aliases: DisjointSet) -> None:
    if isinstance(node, dict):
        if node.get("kind") == "func_stmt":
            call_name = sym_name(node.get("call_sym"))
            if call_name:
                output.add(call_name)
                aliases.find(call_name)
        for value in node.values():
            collect_function_call_heads(value, output, aliases)
    elif isinstance(node, list):
        for item in node:
            collect_function_call_heads(item, output, aliases)


def walk_ast(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_ast(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_ast(item)


def sym_name(node: Any) -> str | None:
    if isinstance(node, dict) and node.get("kind") == "sym":
        name = node.get("name")
        if isinstance(name, str) and name and not is_generated_sym_name(name):
            return name
    return None


def alias_closure(name: str, groups: dict[str, set[str]]) -> set[str]:
    for names in groups.values():
        if name in names:
            return set(names)
    return {name}


def aliases_for(name: str, groups: dict[str, set[str]]) -> set[str]:
    for names in groups.values():
        if name in names:
            return set(names)
    return {name}


def expand_with_aliases(names: set[str], groups: dict[str, set[str]]) -> set[str]:
    expanded = set(names)
    for name in list(names):
        expanded.update(aliases_for(name, groups))
    return expanded


def expand_operator_aliases(names: set[str]) -> set[str]:
    expanded = set(names)
    for name in list(names):
        expanded.update(NORMALIZED_OPERATOR_ALIASES.get(name, set()))
    return expanded


def located_import_expansion(text: str, file_label: str, base_dir: Path) -> LocatedText:
    root = strip_leading_bom(make_located_text(text, file_label, import_origin=False))
    normalized = normalize_latex_located(root, load_tokens())
    return expand_for_checking(normalized, base_dir=base_dir, seen=set())


def collect_definitions(
    expanded: LocatedText,
    evidence: dict[str, set[str]],
    ast: dict[str, Any],
) -> dict[str, list[Definition]]:
    cleaned = remove_comments_located(expanded)
    aliases = DisjointSet()
    class_candidates: list[Definition] = []
    class_type_candidates: list[tuple[str, str, Definition]] = []
    signature_class_candidates: list[tuple[str, int]] = []
    callable_candidates: list[tuple[str, str, Occurrence, int, int, str, str | None]] = []
    pure_candidates: list[Definition] = []
    class_stack: list[tuple[int, str]] = []
    order = 0

    for line in logical_lines_located(cleaned):
        order += 1
        indent, stripped = split_indent_located(line)
        if not stripped.text:
            continue
        while class_stack and indent <= class_stack[-1][0]:
            class_stack.pop()

        explicit_classes = collect_explicit_class_definitions(stripped, order)
        class_candidates.extend(explicit_classes)
        class_candidates.extend(collect_qualified_class_owner_definitions(stripped, order))
        if explicit_classes:
            class_stack.append((indent, explicit_classes[0].name))
        declaration_candidates, signature_candidates = collect_declaration_definitions(
            stripped,
            order,
            owner_class=declaration_owner_class(stripped.text, class_stack),
        )
        callable_candidates.extend(declaration_candidates)
        pure_candidates.extend(signature_candidates)
        signature_class_candidates.extend(collect_declaration_signature_class_candidates(stripped, order))
        callable_candidates.extend(
            collect_class_field_definition(
                stripped,
                order,
                declaration_owner_class(stripped.text, class_stack),
            )
        )
        callable_candidates.extend(collect_classifier_fact_candidates(stripped, aliases, order))
        class_type_candidates.extend(collect_class_type_fact_candidates(stripped, order))
        class_type_candidates.extend(collect_qualified_class_receiver_candidates(stripped, order))
        if class_stack:
            class_type_candidates.extend(collect_class_receiver_candidates(stripped, class_stack[-1][1], order))
        pure_candidates.extend(collect_pure_intro_definitions(stripped, order))

    groups = aliases.groups()
    definitions: dict[str, list[Definition]] = {}
    for definition in class_candidates + pure_candidates:
        definitions.setdefault(definition.name, []).append(definition)
    class_definitions = first_definitions_by_name(class_candidates)
    authored_premise_class_facts = collect_authored_premise_class_facts(cleaned)
    for class_name, sym_name, fallback in class_type_candidates:
        target = class_definitions.get(class_name)
        if target is None:
            definitions.setdefault(sym_name, []).append(fallback)
            continue
        definitions.setdefault(sym_name, []).append(
            definition_for_class_typed_symbol(target, class_name, fallback.order)
        )
    for sym_name, candidate_order in signature_class_candidates:
        target = signature_class_definition(sym_name, class_definitions, groups)
        if target is None:
            continue
        definitions.setdefault(sym_name, []).append(
            definition_for_class_typed_symbol(target, target.name, candidate_order)
        )
    for class_name, sym_name, candidate_order in collect_ast_class_type_candidates(
        ast,
        order + 1,
        authored_premise_class_facts,
    ):
        target = class_definitions.get(class_name)
        if target is None:
            continue
        definitions.setdefault(sym_name, []).append(
            definition_for_class_typed_symbol(target, class_name, candidate_order)
        )

    predicate_classes = alias_closure(CLASSIFIER_PREDICATE, groups)
    function_classes = alias_closure(CLASSIFIER_FUNCTION, groups)
    for classifier, name, occurrence, candidate_order, rank, kind, owner_class in callable_candidates:
        classifier_aliases = aliases_for(classifier, groups)
        sym_type = classify_symbol(name, evidence)
        if classifier_aliases & predicate_classes:
            sym_type = "pred"
        elif classifier_aliases & function_classes:
            sym_type = "func"
        elif sym_type not in {"func", "pred"}:
            continue
        definitions.setdefault(name, []).append(
            Definition(
                file=occurrence.file,
                lineno=occurrence.lineno,
                col_start_no=occurrence.col_start_no,
                col_end_no=occurrence.col_end_no,
                name=name,
                type=sym_type,
                order=candidate_order,
                rank=rank,
                kind=kind,
                owner_class=owner_class,
            )
        )

    for occurrence, candidate_order in collect_call_head_candidates(cleaned):
        sym_type = classify_symbol(occurrence.name, evidence)
        if sym_type not in {"func", "pred"}:
            continue
        definitions.setdefault(occurrence.name, []).append(
            Definition(
                file=occurrence.file,
                lineno=occurrence.lineno,
                col_start_no=occurrence.col_start_no,
                col_end_no=occurrence.col_end_no,
                name=occurrence.name,
                type=sym_type,
                order=candidate_order,
                rank=2,
                kind="call_evidence",
            )
        )

    return dedupe_definitions(definitions)


def collect_ast_class_type_candidates(
    ast: dict[str, Any],
    start_order: int,
    authored_premise_class_facts: set[tuple[str, str]],
) -> list[tuple[str, str, int]]:
    direct_facts: list[tuple[str, str, int]] = []
    target_equalities: list[tuple[str, str]] = []
    order = start_order

    def add_class_fact(statement: Any, *, allow_authored_premise: bool) -> None:
        nonlocal order
        order += 1
        call_name = sym_name(statement.get("call_sym")) if isinstance(statement, dict) else None
        args = [sym_name(arg) for arg in statement.get("arg_sym_list", [])] if isinstance(statement, dict) else []
        if call_name != "~" or len(args) != 2 or not args[0] or not args[1]:
            return
        class_name, source_name = args
        if not is_capital_head(class_name) or is_capital_head(source_name):
            return
        if not allow_authored_premise and (class_name, source_name) in authored_premise_class_facts:
            return
        direct_facts.append((class_name, source_name, order))

    def walk_module(node: Any) -> None:
        nonlocal order
        if not isinstance(node, dict) or node.get("kind") not in {"quantified_stmt", "set_stmt"}:
            return
        for statement in node.get("target_PSs", []):
            add_class_fact(statement, allow_authored_premise=True)
            call_name = sym_name(statement.get("call_sym")) if isinstance(statement, dict) else None
            args = [sym_name(arg) for arg in statement.get("arg_sym_list", [])] if isinstance(statement, dict) else []
            if call_name == "=" and len(args) == 2 and args[0] and args[1]:
                left, right = args
                if not is_capital_head(left) and not is_capital_head(right):
                    target_equalities.append((left, right))
            if isinstance(statement, dict) and statement.get("kind") in {"quantified_stmt", "set_stmt"}:
                walk_module(statement)
        for statement in node.get("premise_PSs", []):
            add_class_fact(statement, allow_authored_premise=False)
            if isinstance(statement, dict) and statement.get("kind") in {"quantified_stmt", "set_stmt"}:
                walk_module(statement)
        for binding in node.get("premise_binding_stmts", []):
            src = binding.get("src_stmt") if isinstance(binding, dict) else None
            if isinstance(src, dict) and src.get("kind") in {"quantified_stmt", "set_stmt"}:
                walk_module(src)

    walk_module(ast)

    aliases = DisjointSet()
    for class_name, source_name, _ in direct_facts:
        aliases.find(class_name)
        aliases.find(source_name)
    for left, right in target_equalities:
        aliases.union(left, right)

    groups = aliases.groups()
    candidates: list[tuple[str, str, int]] = []
    for class_name, source_name, candidate_order in direct_facts:
        for alias in sorted(aliases_for(source_name, groups)):
            if is_capital_head(alias) or is_generated_sym_name(alias):
                continue
            candidates.append((class_name, alias, candidate_order))
    return candidates


def collect_authored_premise_class_facts(cleaned: LocatedText) -> set[tuple[str, str]]:
    facts: set[tuple[str, str]] = set()
    for line in logical_lines_located(cleaned):
        _, stripped = split_indent_located(line)
        if not stripped.text.startswith("|") or stripped.text.startswith("|-"):
            continue
        statement = premise_body(stripped)
        inherit_parts = [part.strip() for part in split_top_level_located(statement, "~")]
        if len(inherit_parts) != 2:
            continue
        class_name, sym_name = inherit_parts[0].text, inherit_parts[1].text
        if not is_plain_sym(class_name) or not is_plain_sym(sym_name):
            continue
        if is_capital_head(class_name) and not is_capital_head(sym_name):
            facts.add((class_name, sym_name))
    return facts


def collect_explicit_class_definitions(line: LocatedText, order: int) -> list[Definition]:
    if not is_plain_sym(line.text) or not is_capital_head(line.text):
        return []
    occurrence = occurrence_from_located(line, line.text)
    if occurrence is None:
        return []
    return [definition_from_occurrence(occurrence, "class", order, kind="class_decl", owner_class=occurrence.name)]


def collect_qualified_class_owner_definitions(line: LocatedText, order: int) -> list[Definition]:
    match = re.match(r"^(?P<class>[^\s:]+)::", line.text)
    if match is None:
        return []
    class_name = match.group("class")
    if not is_plain_sym(class_name) or not is_capital_head(class_name):
        return []
    occurrence = occurrence_from_located(line, class_name)
    if occurrence is None:
        return []
    return [definition_from_occurrence(occurrence, "class", order, kind="class_owner", owner_class=class_name)]


def declaration_owner_class(line_text: str, class_stack: list[tuple[int, str]]) -> str | None:
    match = re.match(r"^(?P<class>[^\s:]+)::.+?:", line_text)
    if match is not None and is_plain_sym(match.group("class")):
        return match.group("class")
    if line_text.startswith("::") and class_stack:
        return class_stack[-1][1]
    return None


def collect_declaration_definitions(
    line: LocatedText,
    order: int,
    *,
    owner_class: str | None = None,
) -> tuple[list[tuple[str, str, Occurrence, int, int, str, str | None]], list[Definition]]:
    declaration = parse_premise_declaration(line.text)
    header = line.slice(1).strip() if declaration is not None and line.text.startswith("|") else line
    if declaration is None:
        declaration = parse_declaration(line.text)
        header = line
    if declaration is None:
        return [], []

    name, inputs, outputs, _ = declaration
    name_occurrence = occurrence_from_located(header, name)
    callable_candidates: list[tuple[str, str, Occurrence, int, int, str, str | None]] = []
    if name_occurrence is not None:
        classifier = CLASSIFIER_PREDICATE if outputs == ["bool"] else CLASSIFIER_FUNCTION
        callable_candidates.append((classifier, name, name_occurrence, order, 0, "callable_decl", owner_class))

    pure_definitions: list[Definition] = []
    for term in inputs + outputs:
        if not is_plain_sym(term):
            continue
        term_occurrence = occurrence_from_located(header, term)
        if term_occurrence is not None:
            pure_definitions.append(definition_from_occurrence(term_occurrence, "pure", order, kind="pure_intro"))
    return callable_candidates, pure_definitions


def collect_declaration_signature_class_candidates(line: LocatedText, order: int) -> list[tuple[str, int]]:
    declaration = parse_premise_declaration(line.text)
    if declaration is None:
        declaration = parse_declaration(line.text)
    if declaration is None:
        return []

    _, inputs, outputs, _ = declaration
    signature_terms = [*inputs, *([] if outputs == ["bool"] else outputs)]
    candidates: list[tuple[str, int]] = []
    for term in signature_terms:
        if not is_plain_sym(term) or is_capital_head(term) or is_generated_sym_name(term):
            continue
        candidates.append((term, order))
    return candidates


def collect_class_field_definition(
    line: LocatedText,
    order: int,
    owner_class: str | None,
) -> list[tuple[str, str, Occurrence, int, int, str, str | None]]:
    if owner_class is None:
        return []
    match = re.fullmatch(r"(?:(?P<class>[^\s:]+)::|::)(?P<name>[^\s:]+)", line.text)
    if match is None:
        return []
    name = match.group("name")
    if not is_plain_sym(name):
        return []
    occurrence = occurrence_from_located(line, name)
    if occurrence is None:
        return []
    return [(CLASSIFIER_FUNCTION, name, occurrence, order, 0, "callable_decl", owner_class)]


def collect_classifier_fact_candidates(
    line: LocatedText,
    aliases: DisjointSet,
    order: int,
) -> list[tuple[str, str, Occurrence, int, int, str, str | None]]:
    statement = premise_body(line)
    equals_parts = [part.strip() for part in split_top_level_located(statement, "=")]
    if len(equals_parts) == 2 and all(is_plain_sym(part.text) for part in equals_parts):
        aliases.union(equals_parts[0].text, equals_parts[1].text)

    inherit_parts = [part.strip() for part in split_top_level_located(statement, "~")]
    if len(inherit_parts) != 2:
        return []
    classifier, name = inherit_parts[0], inherit_parts[1]
    if not is_plain_sym(classifier.text) or not is_plain_sym(name.text):
        return []
    occurrence = occurrence_from_located(name, name.text)
    if occurrence is None:
        return []
    return [(classifier.text, name.text, occurrence, order, 1, "classifier_fact", None)]


def collect_class_type_fact_candidates(line: LocatedText, order: int) -> list[tuple[str, str, Definition]]:
    if line.text.startswith("|"):
        return []
    statement = premise_body(line)
    inherit_parts = [part.strip() for part in split_top_level_located(statement, "~")]
    if len(inherit_parts) != 2:
        return []
    class_name, sym_name = inherit_parts[0].text, inherit_parts[1].text
    if not is_plain_sym(class_name) or not is_plain_sym(sym_name) or not is_capital_head(class_name) or is_capital_head(sym_name):
        return []
    occurrence = occurrence_from_located(inherit_parts[1], sym_name)
    if occurrence is None:
        return []
    return [
        (
            class_name,
            sym_name,
            Definition(
                file=occurrence.file,
                lineno=occurrence.lineno,
                col_start_no=occurrence.col_start_no,
                col_end_no=occurrence.col_end_no,
                name=sym_name,
                type="class",
                order=order,
                rank=-1,
                kind="class_type_fact",
                owner_class=class_name,
            ),
        )
    ]


def collect_class_receiver_candidates(line: LocatedText, class_name: str, order: int) -> list[tuple[str, str, Definition]]:
    declaration = parse_declaration(line.text)
    if declaration is None:
        return []
    _, inputs, _, _ = declaration
    if not inputs or not is_plain_sym(inputs[0]) or is_capital_head(inputs[0]):
        return []
    occurrence = occurrence_from_located(line, inputs[0])
    if occurrence is None:
        return []
    return [(class_name, inputs[0], class_receiver_fallback_definition(occurrence, class_name, order))]


def collect_qualified_class_receiver_candidates(line: LocatedText, order: int) -> list[tuple[str, str, Definition]]:
    declaration = parse_declaration(line.text)
    match = re.match(r"^(?P<class>[^\s:]+)::.+?:", line.text)
    if declaration is None or match is None:
        return []
    class_name = match.group("class")
    _, inputs, _, _ = declaration
    if not is_plain_sym(class_name) or not inputs or not is_plain_sym(inputs[0]) or is_capital_head(inputs[0]):
        return []
    occurrence = occurrence_from_located(line, inputs[0])
    if occurrence is None:
        return []
    return [(class_name, inputs[0], class_receiver_fallback_definition(occurrence, class_name, order))]


def collect_pure_intro_definitions(line: LocatedText, order: int) -> list[Definition]:
    definitions: list[Definition] = []
    if line.text.startswith("|") and not line.text.startswith("|-"):
        binders = parse_binder_list_located(line.slice(1).strip())
        if binders:
            for binder in binders:
                definitions.append(
                    Definition(
                        file=binder.position.file,
                        lineno=binder.position.line - 1,
                        col_start_no=binder.position.column - 1,
                        col_end_no=binder.position.column - 1 + len(binder.text),
                        name=binder.text,
                        type="pure",
                        order=order,
                        kind="pure_intro",
                    )
                )

    statement = premise_body(line)
    parts = [part.strip() for part in split_top_level_located(statement, "=")]
    if len(parts) >= 2:
        binders = parse_binder_list_located(parts[0])
        if binders:
            for binder in binders:
                definitions.append(
                    Definition(
                        file=binder.position.file,
                        lineno=binder.position.line - 1,
                        col_start_no=binder.position.column - 1,
                        col_end_no=binder.position.column - 1 + len(binder.text),
                        name=binder.text,
                        type="pure",
                        order=order,
                        kind="pure_intro",
                    )
                )
    return definitions


def collect_call_head_candidates(cleaned: LocatedText) -> list[tuple[Occurrence, int]]:
    candidates: list[tuple[Occurrence, int]] = []
    order = 0
    for line in split_lines_located(cleaned):
        line_occurrences = scan_located_line_occurrences(line)
        for occurrence, end_index in line_occurrences:
            next_index = next_nonspace_index(line.text, end_index)
            if next_index is not None and next_index < len(line.text) and line.text[next_index] == "(":
                order += 1
                candidates.append((occurrence, order))
    return candidates


def premise_body(line: LocatedText) -> LocatedText:
    stripped = line.strip()
    if stripped.text.startswith("|") and not stripped.text.startswith("|-"):
        return stripped.slice(1).strip()
    return stripped


def occurrence_from_located(line: LocatedText, name: str) -> Occurrence | None:
    match = re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", line.text)
    if match is None:
        return None
    position = line.positions[match.start()]
    return Occurrence(
        file=position.file,
        lineno=position.line - 1,
        col_start_no=position.column - 1,
        col_end_no=position.column - 1 + len(name),
        name=name,
    )


def class_receiver_fallback_definition(occurrence: Occurrence, class_name: str, order: int) -> Definition:
    return Definition(
        file=occurrence.file,
        lineno=occurrence.lineno,
        col_start_no=occurrence.col_start_no,
        col_end_no=occurrence.col_end_no,
        name=occurrence.name,
        type="class",
        order=order,
        rank=-1,
        kind="class_receiver",
        owner_class=class_name,
    )


def definition_for_class_typed_symbol(target: Definition, class_name: str, order: int) -> Definition:
    return Definition(
        file=target.file,
        lineno=target.lineno,
        col_start_no=target.col_start_no,
        col_end_no=target.col_end_no,
        name=target.name,
        type=target.type,
        order=order,
        rank=-1,
        kind="class_type_target",
        owner_class=class_name,
    )


def definition_from_occurrence(
    occurrence: Occurrence,
    sym_type: str,
    order: int,
    rank: int = 0,
    *,
    kind: str = "generic",
    owner_class: str | None = None,
) -> Definition:
    return Definition(
        file=occurrence.file,
        lineno=occurrence.lineno,
        col_start_no=occurrence.col_start_no,
        col_end_no=occurrence.col_end_no,
        name=occurrence.name,
        type=sym_type,
        order=order,
        rank=rank,
        kind=kind,
        owner_class=owner_class,
    )


def dedupe_definitions(definitions: dict[str, list[Definition]]) -> dict[str, list[Definition]]:
    output: dict[str, list[Definition]] = {}
    for name, entries in definitions.items():
        seen: set[tuple[str, int, int, str]] = set()
        unique: list[Definition] = []
        for entry in entries:
            key = (entry.file, entry.lineno, entry.col_start_no, entry.type)
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        output[name] = sorted(unique, key=lambda item: (item.order, item.file, item.lineno, item.col_start_no))
    return output


def first_definitions_by_name(definitions: list[Definition]) -> dict[str, Definition]:
    output: dict[str, Definition] = {}
    for definition in sorted(definitions, key=lambda item: (item.order, item.file, item.lineno, item.col_start_no)):
        output.setdefault(definition.name, definition)
    return output


def signature_class_definition(
    sym_name: str,
    class_definitions: dict[str, Definition],
    groups: dict[str, set[str]],
) -> Definition | None:
    for candidate_name in inheritance_candidate_chain(sym_name):
        target = class_definitions.get(candidate_name)
        if target is not None:
            return target
        alias_targets = [
            class_definitions[alias]
            for alias in aliases_for(candidate_name, groups)
            if alias in class_definitions
        ]
        if alias_targets:
            return min(alias_targets, key=lambda item: (item.order, item.file, item.lineno, item.col_start_no))
    return None


def scan_located_line_occurrences(line: LocatedText) -> list[tuple[Occurrence, int]]:
    entries: list[tuple[Occurrence, int]] = []
    index = 0
    while index < len(line.text):
        char = line.text[index]
        if char == "#":
            break
        if is_literal_quote_start(line.text, index):
            index = find_quoted_literal_end(line.text, index) + 1
            continue
        structural = next((token for token in STRUCTURAL_TOKENS if line.text.startswith(token, index)), None)
        if structural is not None:
            index += len(structural)
            continue
        operator = next((op for op in SOURCE_OPERATORS if line.text.startswith(op, index)), None)
        if operator is not None:
            entries.append((occurrence_at(line, index, index + len(operator), operator), index + len(operator)))
            index += len(operator)
            continue
        if char.isspace() or char in {"(", ")", "{", "}", "[", "]", ",", ";"}:
            index += 1
            continue
        if char in STRUCTURAL_CHARS:
            index += 1
            continue
        match = IDENTIFIER_RE.match(line.text, index)
        if match is not None:
            name = match.group(0)
            if is_source_symbol_name(name):
                entries.append((occurrence_at(line, match.start(), match.end(), name), match.end()))
            index = match.end()
            continue
        if is_plain_sym(char) and char in OPERATOR_NAMES:
            entries.append((occurrence_at(line, index, index + 1, char), index + 1))
        index += 1
    return entries


def occurrence_at(line: LocatedText, start: int, end: int, name: str) -> Occurrence:
    position = line.positions[start]
    return Occurrence(
        file=position.file,
        lineno=position.line - 1,
        col_start_no=position.column - 1,
        col_end_no=position.column - 1 + max(end - start, 1),
        name=name,
    )


def next_nonspace_index(text: str, index: int) -> int | None:
    while index < len(text) and text[index].isspace():
        index += 1
    return index if index < len(text) else None


def scan_source_occurrences(text: str, file_label: str) -> list[Occurrence]:
    tokens = load_tokens()
    latex_keys = sorted(tokens, key=len, reverse=True)
    occurrences: list[Occurrence] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("$import"):
            continue
        index = 0
        while index < len(line):
            char = line[index]
            if char == "#":
                break
            if is_literal_quote_start(line, index):
                index = find_quoted_literal_end(line, index) + 1
                continue
            structural = next((token for token in STRUCTURAL_TOKENS if line.startswith(token, index)), None)
            if structural is not None:
                index += len(structural)
                continue
            latex_key = next((key for key in latex_keys if line.startswith(key, index)), None)
            if latex_key is not None:
                name = tokens[latex_key]
                if name and is_source_symbol_name(name):
                    occurrences.append(make_occurrence(file_label, line_no, index, index + len(latex_key), name))
                index += len(latex_key)
                continue
            operator = next((op for op in SOURCE_OPERATORS if line.startswith(op, index)), None)
            if operator is not None:
                occurrences.append(make_occurrence(file_label, line_no, index, index + len(operator), operator))
                index += len(operator)
                continue
            if char.isspace() or char in {"(", ")", "{", "}", "[", "]", ",", ";"}:
                index += 1
                continue
            if char in STRUCTURAL_CHARS:
                index += 1
                continue
            match = IDENTIFIER_RE.match(line, index)
            if match is not None:
                name = match.group(0)
                if is_source_symbol_name(name):
                    occurrences.append(
                        make_occurrence(
                            file_label,
                            line_no,
                            match.start(),
                            match.end(),
                            name,
                            member_receiver=member_receiver_before(line, match.start()),
                        )
                    )
                index = match.end()
                continue
            if is_plain_sym(char) and char in OPERATOR_NAMES:
                occurrences.append(make_occurrence(file_label, line_no, index, index + 1, char))
            index += 1
    return occurrences


def make_occurrence(
    file_label: str,
    line_no: int,
    start: int,
    end: int,
    name: str,
    *,
    member_receiver: str | None = None,
) -> Occurrence:
    return Occurrence(
        file=file_label,
        lineno=line_no - 1,
        col_start_no=start,
        col_end_no=end,
        name=name,
        member_receiver=member_receiver,
    )


def member_receiver_before(line: str, start: int) -> str | None:
    index = start - 1
    while index >= 0 and line[index].isspace():
        index -= 1
    if index < 0 or line[index] != ".":
        return None
    end = index
    index -= 1
    while index >= 0 and line[index].isspace():
        index -= 1
    receiver_end = index + 1
    while index >= 0 and re.match(r"[\w']", line[index], flags=re.UNICODE):
        index -= 1
    if index >= 0 and line[index] == "^":
        index -= 1
    receiver = line[index + 1 : receiver_end]
    return receiver if is_source_symbol_name(receiver) else None


def is_source_symbol_name(name: str) -> bool:
    return bool(name) and is_plain_sym(name) and not is_generated_sym_name(name)


def build_payload(
    occurrences: list[Occurrence],
    evidence: dict[str, set[str]],
    definitions: dict[str, list[Definition]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    symbol_definitions: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        sym_type = classify_symbol(occurrence.name, evidence)
        colorable = sym_type in {"class", "func", "pred"} and is_colorable_identifier(occurrence.name)
        definition = choose_definition(occurrence, sym_type, definitions)
        counts[occurrence.name] += 1
        entry = {
            "file": occurrence.file,
            "lineno": occurrence.lineno,
            "col_start_no": occurrence.col_start_no,
            "col_end_no": occurrence.col_end_no,
            "name": occurrence.name,
            "type": sym_type,
            "colorable": colorable,
        }
        if definition is not None:
            serialized = serialize_definition(definition)
            entry["definition"] = serialized
            symbol_definitions.setdefault(occurrence.name, serialized)
        entries.append(entry)
    symbols = [
        {
            "name": name,
            "type": classify_symbol(name, evidence),
            "occurrence_count": count,
            **({"definition": symbol_definitions[name]} if name in symbol_definitions else {}),
        }
        for name, count in sorted(counts.items())
    ]
    return {
        "summary": {"symbol_count": len(symbols), "occurrence_count": len(entries)},
        "symbols": symbols,
        "occurrences": entries,
    }


def choose_definition(
    occurrence: Occurrence,
    sym_type: str,
    definitions: dict[str, list[Definition]],
) -> Definition | None:
    candidates = definitions.get(occurrence.name, [])
    if sym_type == "pure":
        class_targets = [
            candidate
            for candidate in candidates
            if candidate.type == "class" and candidate.kind in {"class_type_target", "class_type_fact", "class_receiver"}
        ]
        if class_targets:
            return select_definition(class_targets, occurrence)
        return None
    if sym_type == "class":
        return select_definition([candidate for candidate in candidates if candidate.kind == "class_decl"], occurrence)
    typed = [candidate for candidate in candidates if candidate.type == sym_type]
    if not typed:
        return None
    if sym_type in {"func", "pred"} and occurrence.member_receiver:
        owner_class = receiver_owner_class(occurrence.member_receiver, definitions)
        if owner_class is not None:
            method_targets = [
                candidate
                for candidate in typed
                if candidate.kind == "callable_decl" and candidate.owner_class == owner_class
            ]
            selected = select_definition(method_targets, occurrence)
            if selected is not None:
                return selected
    for kind in ("callable_decl", "classifier_fact", "call_evidence"):
        selected = select_definition([candidate for candidate in typed if candidate.kind == kind], occurrence)
        if selected is not None:
            return selected
    useful = [candidate for candidate in typed if candidate.rank < 2] or typed
    return select_definition(useful, occurrence)


def receiver_owner_class(receiver_name: str, definitions: dict[str, list[Definition]]) -> str | None:
    class_targets = [
        candidate
        for candidate in definitions.get(receiver_name, [])
        if candidate.type == "class"
        and candidate.owner_class is not None
        and candidate.kind in {"class_type_target", "class_type_fact", "class_receiver"}
    ]
    selected = select_definition(class_targets, None)
    return selected.owner_class if selected is not None else None


def select_definition(candidates: list[Definition], occurrence: Occurrence | None) -> Definition | None:
    if not candidates:
        return None
    if occurrence is None:
        return min(candidates, key=lambda item: (item.order, item.file, item.lineno, item.col_start_no))
    useful = candidates
    same_file = [candidate for candidate in useful if candidate.file == occurrence.file]
    if same_file:
        return min(same_file, key=lambda item: (item.rank, item.order, item.lineno, item.col_start_no))
    return min(useful, key=lambda item: (item.rank, item.order, item.file, item.lineno, item.col_start_no))


def serialize_definition(definition: Definition) -> dict[str, Any]:
    return {
        "file": definition.file,
        "lineno": definition.lineno,
        "col_start_no": definition.col_start_no,
        "col_end_no": definition.col_end_no,
        "name": definition.name,
        "type": definition.type,
    }


def classify_symbol(name: str, evidence: dict[str, set[str]]) -> str:
    if name in evidence["class"] or is_capital_head(name):
        return "class"
    if name in evidence["pred"]:
        return "pred"
    if name in evidence["func"]:
        return "func"
    return "pure"


def is_capital_head(name: str) -> bool:
    return bool(name) and name[0].isupper()


def is_colorable_identifier(name: str) -> bool:
    return name not in OPERATOR_NAMES and IDENTIFIER_RE.fullmatch(name) is not None


def read_input(args: argparse.Namespace) -> tuple[str, str, Path]:
    if args.file is not None:
        path = args.file.resolve()
        return path.read_text(encoding="utf-8"), str(path), args.base_dir or path.parent
    if args.text is not None:
        file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
        base_dir = args.base_dir or (args.filename.resolve().parent if args.filename is not None else Path.cwd())
        return args.text, file_label, base_dir
    file_label = str(args.filename.resolve()) if args.filename is not None else STDIN_FILE
    base_dir = args.base_dir or (args.filename.resolve().parent if args.filename is not None else Path.cwd())
    return sys.stdin.read(), file_label, base_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve logic-language symbol types and emit JSON.")
    parser.add_argument("--file", type=Path, help="module file to resolve")
    parser.add_argument("--text", help="module text to resolve; defaults to stdin when --file is omitted")
    parser.add_argument("--filename", type=Path, help="diagnostic/source file label for --text or stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    source, file_label, base_dir = read_input(args)
    payload = resolve_text(source, file_label=file_label, base_dir=base_dir)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
