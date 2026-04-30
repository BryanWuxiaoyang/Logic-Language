#!/usr/bin/env python3
"""Expand local logic-language module-text rewrite rules."""

from __future__ import annotations

import re
from pathlib import Path

from compile_module_text import (
    CompileError,
    IMPORT_RE,
    INTRINSIC_SYMS,
    Module,
    ModuleCompiler,
    Statement,
    dedupe,
    expand_imports,
    infer_syms,
    is_plain_sym,
    load_lark_parser,
    load_tokens,
    lower_member_calls,
    normalize_latex,
    parse_binder_list,
    parse_declaration,
    parse_signature_terms,
    remove_comments,
    skill_dir,
    strip_outer_blank_lines,
    tuple_or_single,
    call_text,
)


NUMERIC_LITERAL_RE = re.compile(r"(?<![\w'])\d+(?:\.\d+)?(?![\w'])")
STDLIB_IMPORT = "$import standard_library.lp"


class ExpandError(CompileError):
    """Raised when module text cannot be expanded."""


def expand_module_text(text: str, base_dir: Path | str = ".") -> str:
    base_path = Path(base_dir).resolve()
    tokens = load_tokens()
    import_lines, body_text = split_imports(text)
    output_imports = dedupe([STDLIB_IMPORT, *[normalize_latex(line, tokens) for line in import_lines]])

    normalized_body = normalize_latex(body_text, tokens)
    visible_text = visible_context_text(text, base_path, tokens)
    visible_syms = collect_visible_syms(visible_text + "\n" + normalized_body)

    body = strip_outer_blank_lines(remove_comments(normalized_body))
    if not body:
        return "\n".join(output_imports) + "\n"

    compiler = AliasModuleCompiler(load_lark_parser(), visible_syms)
    module = compiler.compile(body)
    expander = ModuleExpander(visible_syms)
    expanded_body = expander.render_module(module, outer_syms=set(), indent=0)
    return "\n".join([*output_imports, expanded_body]) + "\n"


def split_imports(text: str) -> tuple[list[str], str]:
    imports: list[str] = []
    body_lines: list[str] = []
    for line in text.splitlines():
        if IMPORT_RE.match(line):
            imports.append(line.strip())
        else:
            body_lines.append(line)
    return imports, "\n".join(body_lines)


def visible_context_text(text: str, base_dir: Path, tokens: dict[str, str]) -> str:
    import_lines, _ = split_imports(text)
    context_parts: list[str] = []
    stdlib_path = skill_dir() / "standard_library.lp"
    if stdlib_path.exists():
        context_parts.append(stdlib_path.read_text(encoding="utf-8"))
    for import_line in import_lines:
        context_parts.append(expand_visible_import(import_line, base_dir))
    return normalize_latex("\n".join(context_parts), tokens)


def expand_visible_import(import_line: str, base_dir: Path) -> str:
    match = IMPORT_RE.match(import_line)
    if not match:
        return ""
    raw_path = match.group("path").strip().strip("\"'")
    if Path(raw_path).name == "standard_library.lp":
        return (skill_dir() / "standard_library.lp").read_text(encoding="utf-8")
    return expand_imports(import_line, base_dir)


def collect_visible_syms(text: str) -> set[str]:
    syms = set(INTRINSIC_SYMS)
    cleaned = remove_comments(text)
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("$import"):
            continue
        if stripped.startswith("|"):
            binders = parse_binder_list(stripped[1:].strip())
            if binders:
                syms.update(binders)
        declaration = parse_declaration(stripped)
        if declaration is not None:
            name, _, _, _ = declaration
            syms.add(name)
        if "::" in stripped:
            left = stripped.split("::", 1)[0].strip()
            if is_plain_sym(left):
                syms.add(left)
        if "~" in stripped:
            left, _ = stripped.split("~", 1)
            if is_plain_sym(left.strip()):
                syms.add(left.strip())
        if is_plain_sym(stripped):
            syms.add(stripped)
    return syms


class AliasModuleCompiler(ModuleCompiler):
    def __init__(self, parser: object, visible_syms: set[str]) -> None:
        super().__init__(parser)
        self.visible_syms = set(visible_syms) | set(INTRINSIC_SYMS)

    def lower_header_with_block(self, header: str, block: str) -> list[str]:
        if header.startswith("@") or header.startswith("|-"):
            return super().lower_header_with_block(header, block)
        declaration = parse_declaration(header)
        if declaration is None:
            return super().lower_header_with_block(header, block)

        name, inputs, outputs, arrow = declaration
        inputs, outputs, aliases = self.alias_signature(inputs, outputs)
        block = replace_symbols(block, aliases)
        if arrow == "->":
            outputs = [replace_symbols(output, aliases) for output in outputs]
            call = call_text(name, inputs)
            target = f"{tuple_or_single(outputs)} = {call}"
            return [f"{name}: {tuple_or_single(inputs)} => {tuple_or_single(outputs)}", "∀{\n" + target + "\n" + block + "\n}"]
        call = call_text(name, inputs)
        target = f"{tuple_or_single(outputs)} = {call}" if outputs != ["bool"] else call
        return ["function~" + name, "∀{\n| " + ", ".join(inputs + outputs) + "\n| " + target + "\n" + block + "\n}"]

    def alias_signature(self, inputs: list[str], outputs: list[str]) -> tuple[list[str], list[str], dict[str, str]]:
        aliases: dict[str, str] = {}
        reserved = set(inputs + outputs) | self.visible_syms

        def alias_term(term: str) -> str:
            if not is_plain_sym(term) or term not in self.visible_syms or self.class_for_alias(term) is not None:
                return term
            if term not in aliases:
                aliases[term] = self.fresh_alias(term, reserved)
                reserved.add(aliases[term])
            return aliases[term]

        return [alias_term(term) for term in inputs], [alias_term(term) for term in outputs], aliases

    def class_for_alias(self, sym: str) -> str | None:
        classes = sorted(self.visible_syms, key=len, reverse=True)
        for class_sym in classes:
            if class_sym == sym:
                continue
            if re.fullmatch(re.escape(class_sym) + r"\d+", sym):
                return class_sym
            if sym.endswith("_" + class_sym):
                return class_sym
            if sym == class_sym + "_class":
                return class_sym
        return None

    def fresh_alias(self, sym: str, reserved: set[str]) -> str:
        preferred = "__" + sym
        candidate = preferred
        suffix = 1
        while candidate in reserved:
            candidate = f"{preferred}{suffix}"
            suffix += 1
        self.visible_syms.add(candidate)
        return candidate


class ModuleExpander:
    def __init__(self, visible_syms: set[str]) -> None:
        self.visible_syms = set(visible_syms) | set(INTRINSIC_SYMS)
        self.fresh_index = 0

    def render_module(self, module: Module, outer_syms: set[str], indent: int) -> str:
        original_syms = dedupe([*module.syms, *self.infer_statement_syms(module.predicate_statements)])
        local_syms = [sym for sym in original_syms if sym not in INTRINSIC_SYMS]
        if module.type == "quantifier":
            local_syms = [sym for sym in local_syms if sym not in outer_syms]
        child_outer = outer_syms | set(local_syms)

        predicates = self.implicit_predicates(local_syms)
        rendered_predicates = [self.render_statement(statement, child_outer) for statement in module.predicate_statements]
        targets = [self.render_statement(statement, child_outer) for statement in module.target_statements]
        predicates.extend(rendered_predicates)
        predicates.extend(self.local_wrapper_predicates([statement.text for statement in module.predicate_statements + module.target_statements]))
        predicates = dedupe([predicate for predicate in predicates if predicate])

        opener = module.quantifier + "{" if module.type == "quantifier" else "{"
        return self.format_module(opener, local_syms, predicates, targets, indent)

    def infer_statement_syms(self, statements: list[Statement]) -> list[str]:
        return infer_syms([statement.text for statement in statements])

    def render_statement(self, statement: Statement, outer_syms: set[str]) -> str:
        text = lower_member_calls(statement.text)
        for index, submodule in enumerate(statement.sub_modules):
            rendered = self.render_module(submodule, outer_syms, indent=0)
            text = text.replace(f"$module{index}", rendered)
        return text

    def implicit_predicates(self, syms: list[str]) -> list[str]:
        predicates: list[str] = []
        for sym in syms:
            predicates.append(f"sym~{sym}")
            predicates.append(f"{sym}~{sym}")
            predicates.extend(self.naming_inheritance(sym))
        return predicates

    def naming_inheritance(self, sym: str) -> list[str]:
        predicates: list[str] = []
        class_sym = self.class_for_sym(sym)
        if class_sym is not None and class_sym != sym:
            predicates.append(f"{class_sym}~{sym}")

        collection = self.collection_inheritance(sym)
        if collection is not None:
            item = self.fresh_sym(f"{sym}_item")
            predicates.append(f"{collection[0]}~{sym}")
            predicates.append(f"∀{{| {item} | {item} ∈ {sym} | {collection[1]}~{item}}}")
        return predicates

    def class_for_sym(self, sym: str) -> str | None:
        classes = sorted(self.visible_syms, key=len, reverse=True)
        for class_sym in classes:
            if class_sym.startswith("__"):
                continue
            if re.fullmatch("__" + re.escape(class_sym) + r"\d*", sym):
                return class_sym
        for class_sym in classes:
            if class_sym == sym:
                continue
            if re.fullmatch(re.escape(class_sym) + r"\d+", sym):
                return class_sym
            if sym.endswith("_" + class_sym):
                return class_sym
            if sym == class_sym + "_class":
                return class_sym
        return None

    def collection_inheritance(self, sym: str) -> tuple[str, str] | None:
        classes = sorted(self.visible_syms, key=len, reverse=True)
        for class_sym in classes:
            if sym.endswith("_" + class_sym + "_list"):
                return ("tuple", class_sym)
            if sym.endswith("_" + class_sym + "s"):
                return ("set", class_sym)
        return None

    def local_wrapper_predicates(self, texts: list[str]) -> list[str]:
        predicates: list[str] = []
        joined = "\n".join(texts)
        for literal in NUMERIC_LITERAL_RE.findall(joined):
            predicates.append(f"value~{literal}")
        for tuple_text in tuple_literals(joined):
            predicates.append(f"tuple~{tuple_text}")
        for set_text in set_module_literals(joined):
            predicates.append(f"set~{set_text}")
        return predicates

    def fresh_sym(self, preferred: str) -> str:
        candidate = preferred
        while candidate in self.visible_syms:
            candidate = f"{preferred}{self.fresh_index}"
            self.fresh_index += 1
        self.visible_syms.add(candidate)
        return candidate

    def format_module(
        self,
        opener: str,
        syms: list[str],
        predicates: list[str],
        targets: list[str],
        indent: int,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 4)
        lines = [pad + opener]
        if syms:
            lines.append(inner + "| " + ", ".join(syms))
        for predicate in predicates:
            lines.extend(format_section_line(predicate, inner, prefix="| "))
        for target in targets:
            lines.extend(format_section_line(target, inner, prefix=""))
        lines.append(pad + "}")
        return "\n".join(lines)


def tuple_literals(text: str) -> list[str]:
    literals: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "(":
            index += 1
            continue
        previous = text[index - 1] if index > 0 else ""
        if previous == "'" or previous == "_" or previous.isalnum():
            index += 1
            continue
        try:
            end = matching_close(text, index, "(", ")")
        except ExpandError:
            index += 1
            continue
        candidate = text[index : end + 1]
        inner = candidate[1:-1]
        terms = parse_signature_terms(inner)
        if len(terms) > 1 and "," in inner:
            literals.append(candidate)
        index = end + 1
    return dedupe(literals)


def set_module_literals(text: str) -> list[str]:
    literals: list[str] = []
    index = 0
    while index < len(text):
        if text[index] not in {"{", "∀", "∃"}:
            index += 1
            continue
        start = index
        module_start = index + 1 if text[index] in {"∀", "∃"} else index
        if module_start >= len(text) or text[module_start] != "{":
            index += 1
            continue
        try:
            end = matching_close(text, module_start, "{", "}")
        except ExpandError:
            index += 1
            continue
        if text[start] == "{":
            literals.append(text[start : end + 1])
        index = end + 1
    return dedupe(literals)


def replace_symbols(text: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return text
    output: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
            output.append(char)
            index += 1
            continue
        if in_string:
            output.append(char)
            index += 1
            continue
        match = re.match(r"[^\W\d]\w*'?", text[index:], flags=re.UNICODE)
        if match is None:
            output.append(char)
            index += 1
            continue
        token = match.group(0)
        output.append(replacements.get(token, token))
        index += len(token)
    return "".join(output)


def matching_close(text: str, start: int, open_char: str, close_char: str) -> int:
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
    raise ExpandError(f"unclosed {open_char}")


def format_section_line(text: str, indent: str, prefix: str) -> list[str]:
    lines = text.splitlines() or [text]
    if len(lines) == 1:
        return [indent + prefix + lines[0]]
    output = [indent + prefix + lines[0]]
    output.extend(indent + line for line in lines[1:])
    return output
