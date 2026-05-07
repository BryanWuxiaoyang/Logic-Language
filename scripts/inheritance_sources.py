"""Shared inheritance-source naming helpers."""

from __future__ import annotations

import re


SYMBOL_SOURCE = "Symbol"
LITERAL_CLASSIFIERS = {
    "tuple_literal_stmt": "Tuple",
    "set_literal_stmt": "Set",
    "value_literal_stmt": "Value",
    "char_literal_stmt": "Char",
    "str_literal_stmt": "String",
}
CAPITAL_INTRINSIC_SYMS = {
    SYMBOL_SOURCE,
    "Value",
    "Set",
    "Tuple",
    "List",
    "Function",
    "Bool",
    "Char",
    "String",
}


def is_capital_head(name: str) -> bool:
    return bool(name) and name[0].isupper()


def visible_inheritance_sources(visible_syms: set[str]) -> set[str]:
    return {sym for sym in visible_syms if is_capital_head(sym) and not sym.startswith("^")}


def inheritance_candidate_chain(name: str) -> list[str]:
    if name.startswith("^"):
        return []
    base = name.rstrip("'")
    base = re.sub(r"\d+$", "", base)
    if not base:
        return []
    candidates = base_candidate_chain(base)
    if base.endswith("_class"):
        candidates.extend(base_candidate_chain(base[: -len("_class")]))
    return dedupe(candidates)


def base_candidate_chain(base: str) -> list[str]:
    candidates: list[str] = []
    parts = base.split("_")
    for index in range(len(parts)):
        candidate = "_".join(parts[index:])
        if not candidate:
            continue
        candidates.append(candidate[0].upper() + candidate[1:])
    return candidates


def matched_inheritance_sources(name: str, visible_syms: set[str]) -> list[str]:
    visible = visible_inheritance_sources(visible_syms)
    return [candidate for candidate in inheritance_candidate_chain(name) if candidate in visible]


def selected_inheritance_source(name: str, visible_syms: set[str]) -> str | None:
    matches = matched_inheritance_sources(name, visible_syms)
    return matches[0] if matches else None


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
