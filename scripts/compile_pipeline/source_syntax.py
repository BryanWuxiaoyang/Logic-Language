"""Source syntax helper functions used by the stage1 parser."""

from __future__ import annotations

import re

from AST import (
    CLASS_DECL_MARKER,
    GENERATED_SYM_PREFIX,
    INFER_OPERATORS,
    PREMISE_QUANTIFIER_HEADERS,
    SPECIAL_IDENTIFIER_SYMS,
    ClassFieldAssignment,
    dedupe,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.source_utils import (
    find_quoted_literal_end,
    is_literal_quote_start,
    literal_quote_index,
)


def strip_outer_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def brace_delta(line: str) -> int:
    delta = 0
    index = 0
    while index < len(line):
        char = line[index]
        if is_literal_quote_start(line, index):
            index = find_quoted_literal_end(line, index) + 1
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        index += 1
    return delta


def premise_quantifier_header(text: str) -> str | None:
    return PREMISE_QUANTIFIER_HEADERS.get(text.strip())


def split_terms(text: str) -> list[str]:
    terms: list[str] = []
    start = 0
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
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
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and text.startswith(separator, index):
            if separator == "|":
                previous_char = text[index - 1] if index > 0 else ""
                next_char = text[index + 1] if index + 1 < len(text) else ""
                if previous_char == "|" or next_char == "|":
                    index += 1
                    continue
            parts.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(text[start:])
    return parts


def has_top_level(text: str, separator: str) -> bool:
    return len(split_top_level(text, separator)) > 1


def find_matching(text: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise CompileError(f"unclosed {open_char}")


def find_next_module_start(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        char = text[index]
        if char in {"∀", "∃"} and index + 1 < len(text) and text[index + 1] == "{":
            return index
        if char == "{":
            try:
                end = find_matching(text, index, "{", "}")
            except CompileError:
                return index
            body = text[index + 1 : end].strip()
            if body.startswith("|") or has_top_level(body, "|") or has_top_level(body, "=>"):
                return index
            index = end + 1
            continue
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
    if text in SPECIAL_IDENTIFIER_SYMS:
        return True
    if is_generated_sym_name(text):
        return True
    if "^" in text:
        return False
    if re.fullmatch(r"[^\W\d]\w*'*", text, flags=re.UNICODE) is not None:
        return True
    return len(text) == 1 and not text.isspace() and not text.isdigit() and text not in {"(", ")", "[", "]", "{", "}", ",", '"', "'", "^"}


def is_generated_sym_name(text: str) -> bool:
    if not text.startswith(GENERATED_SYM_PREFIX) or text == GENERATED_SYM_PREFIX:
        return False
    base = text[len(GENERATED_SYM_PREFIX) :]
    if base.startswith(GENERATED_SYM_PREFIX) or GENERATED_SYM_PREFIX in base:
        return False
    if re.fullmatch(r"[^\W\d]\w*'*", base, flags=re.UNICODE) is not None:
        return True
    return False


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


def class_declaration_marker(name: str) -> str:
    return f"{CLASS_DECL_MARKER}({name})"


def class_declaration_from_marker(text: str) -> str | None:
    match = re.fullmatch(rf"{re.escape(CLASS_DECL_MARKER)}\((?P<name>[^\s()]+)\)", text.strip())
    if match is None:
        return None
    name = match.group("name")
    return name if is_plain_sym(name) else None


def class_declaration_from_plain_target(text: str) -> str | None:
    stripped = text.strip()
    marker_name = class_declaration_from_marker(stripped)
    if marker_name is not None:
        return marker_name
    if not is_plain_sym(stripped):
        return None
    class_name = explicit_class_header_sym(stripped)
    return class_name


def class_header_sym(header: str) -> str | None:
    header = header.strip()
    if is_plain_sym(header) and re.fullmatch(r"[^\W\d]\w*'*", header, flags=re.UNICODE) is not None:
        return header
    return None


def is_capital_sym(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and stripped[0].isalpha() and stripped[0].isupper())


def explicit_class_header_sym(header: str) -> str | None:
    class_sym = class_header_sym(header)
    if class_sym is not None and is_capital_sym(class_sym):
        return class_sym
    return None


def class_block_prefix_lines(header: str, class_sym: str) -> list[str]:
    if explicit_class_header_sym(class_sym) is not None:
        return [class_sym]
    return [class_declaration_marker(class_sym)]


def class_member_owner_name(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("|") and not stripped.startswith("|-"):
        return class_member_owner_name(stripped[1:].strip())
    if "::" not in stripped:
        return None
    try:
        assignment = parse_class_field_assignment(stripped)
    except CompileError:
        assignment = None
    if assignment is not None:
        return assignment.class_name
    assignment_index = top_level_assignment_index(stripped)
    if assignment_index is not None and "::" in stripped[:assignment_index]:
        return None

    colon_index = declaration_colon_index(stripped)
    if colon_index is not None:
        name = stripped[:colon_index].strip()
        if is_coloncolon_name(name):
            return name.split("::", 1)[0].strip()
        return None

    if is_bare_coloncolon_field_shorthand(stripped):
        return stripped.split("::", 1)[0].strip()
    return None


def erase_coloncolon_statement_head(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("|") and not stripped.startswith("|-") and "::" in stripped:
        return "| " + erase_coloncolon_statement_head(stripped[1:].strip())
    if "::" not in stripped:
        return stripped
    assignment_index = top_level_assignment_index(stripped)
    if assignment_index is not None and "::" in stripped[:assignment_index]:
        raise CompileError("unsupported '::' usage; class-field assignment must be lowered before erasing '::'")

    colon_index = declaration_colon_index(stripped)
    if colon_index is not None:
        name = stripped[:colon_index].strip()
        if "::" in name:
            return erase_coloncolon_name(name) + stripped[colon_index:]
        reject_unsupported_coloncolon(stripped)
        return stripped

    if is_bare_coloncolon_field_shorthand(stripped):
        return coloncolon_field_declaration(stripped)
    reject_unsupported_coloncolon(stripped)
    return stripped


def reject_unsupported_coloncolon(text: str) -> None:
    if "::" in text:
        raise CompileError("unsupported '::' usage; '::' is only supported in declaration heads")


def erase_coloncolon_name(name: str) -> str:
    if not is_coloncolon_name(name):
        raise CompileError("unsupported '::' usage; '::' is only supported in declaration heads")
    suffix = name.split("::", 1)[1].strip()
    if not suffix:
        raise CompileError("unsupported '::' usage; missing declaration name after '::'")
    return suffix


def coloncolon_field_declaration(name: str) -> str:
    if not is_bare_coloncolon_field_shorthand(name):
        raise CompileError("unsupported '::' usage; bare class-field shorthand requires ordinary symbol names")
    class_name, field_name = (part.strip() for part in name.split("::", 1))
    param_name = "_" + lower_head(class_name)
    output_name = "_" + field_name
    return f"{field_name}: {param_name} => {output_name}"


def parse_class_field_assignment(text: str) -> ClassFieldAssignment | None:
    stripped = text.strip()
    if stripped.startswith("|") and not stripped.startswith("|-"):
        inner = parse_class_field_assignment(stripped[1:].strip())
        if inner is None:
            return None
        return ClassFieldAssignment(inner.class_name, inner.field_name, inner.rhs, premise=True)

    assignment_index = top_level_assignment_index(stripped)
    if assignment_index is None:
        return None
    lhs = stripped[:assignment_index].strip()
    rhs = stripped[assignment_index + 1 :].strip()
    if "::" not in lhs:
        return None
    if not is_bare_coloncolon_field_shorthand(lhs):
        raise CompileError("unsupported '::' usage; class-field assignment requires bare Class::field")
    if not rhs:
        raise CompileError("class-field assignment requires a value")
    class_name, field_name = (part.strip() for part in lhs.split("::", 1))
    return ClassFieldAssignment(class_name, field_name, rhs)



def lower_head(name: str) -> str:
    return name[:1].lower() + name[1:]


def is_bare_coloncolon_field_shorthand(name: str) -> bool:
    if name.count("::") != 1:
        return False
    prefix, suffix = (part.strip() for part in name.split("::", 1))
    return bool(prefix and suffix and is_plain_sym(prefix) and is_plain_sym(suffix))


def is_coloncolon_name(name: str) -> bool:
    if name.count("::") != 1:
        return False
    prefix, suffix = (part.strip() for part in name.split("::", 1))
    return bool(prefix and suffix and is_plain_sym(prefix) and is_declaration_head_name(suffix))


def is_declaration_head_name(name: str) -> bool:
    if is_plain_sym(name):
        return True
    return bool(re.fullmatch(r"[^\s:(),{}]+", name))


def parse_declaration(text: str) -> tuple[str, list[str], list[str], str] | None:
    colon_index = declaration_colon_index(text)
    if colon_index is None:
        return None
    name = text[:colon_index].strip()
    rest = text[colon_index + 1 :].strip()
    if re.match(r"^.+?\s*->\s*.+$", rest):
        raise CompileError("function-assign '->' is not supported; use '=>' with an indented function body")
    match = re.match(r"^(?P<inputs>.+?)\s*(?P<arrow>=>)\s*(?P<outputs>.+)$", rest)
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


def parse_premise_declaration(text: str) -> tuple[str, list[str], list[str], str] | None:
    stripped = text.strip()
    if not stripped.startswith("|") or stripped.startswith("|-"):
        return None
    return parse_declaration(stripped[1:].strip())


def declaration_kind_fact(name: str, outputs: list[str]) -> str:
    classifier = "Predicate" if outputs == ["bool"] else "Function"
    return f"{classifier} ~ {name}"


def declaration_colon_index(text: str) -> int | None:
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == ":":
            previous_char = text[index - 1] if index > 0 else ""
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if previous_char == ":" or next_char == ":":
                index += 1
                continue
            return index
        index += 1
    return None


def top_level_assignment_index(text: str) -> int | None:
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if is_literal_quote_start(text, index):
            index = find_quoted_literal_end(text, index) + 1
            continue
        if char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char == "=":
            previous_char = text[index - 1] if index > 0 else ""
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if previous_char in {"<", ">", "!", "="} or next_char in {">", "="}:
                index += 1
                continue
            return index
        index += 1
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
    text = lower_compound_member_calls(text)
    pattern = re.compile(r"(?<![\w'^])(?P<recv>\^?[A-Za-z_][A-Za-z0-9_']*)\.(?P<name>[A-Za-z_][A-Za-z0-9_']*)(?:\((?P<args>[^()]*)\))?")

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


def lower_compound_member_calls(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = lower_one_compound_member_call(current)
    return current


def lower_one_compound_member_call(text: str) -> str:
    index = 0
    while index < len(text):
        if text[index] != ".":
            index += 1
            continue
        name_start = index + 1
        name_end = scan_identifier(text, name_start)
        if name_end is None:
            index += 1
            continue
        args_start = name_end
        args = None
        args_end = name_end
        if args_start < len(text) and text[args_start] == "(":
            close = find_matching(text, args_start, "(", ")")
            args = text[args_start + 1 : close].strip()
            args_end = close + 1
        recv_start = compound_member_receiver_start(text, index)
        if recv_start is None:
            index += 1
            continue
        receiver = text[recv_start:index].strip()
        if is_simple_member_receiver(receiver):
            index += 1
            continue
        name = text[name_start:name_end]
        if args is None or not args:
            replacement = f"{name}({receiver})"
        else:
            replacement = f"{name}({receiver}, {args})"
        return text[:recv_start] + replacement + text[args_end:]
    return text


def compound_member_receiver_start(text: str, dot_index: int) -> int | None:
    end = dot_index
    while end > 0 and text[end - 1].isspace():
        end -= 1
    if end <= 0:
        return None
    close_char = text[end - 1]
    pairs = {")": "(", "]": "[", "}": "{"}
    if close_char in pairs:
        start = find_matching_open(text, end - 1, pairs[close_char], close_char)
        if start is None:
            return None
        prefix_start = start - 1
        while prefix_start >= 0 and is_member_receiver_char(text[prefix_start]):
            prefix_start -= 1
        return prefix_start + 1
    start = end - 1
    while start >= 0 and is_member_receiver_char(text[start]):
        start -= 1
    return start + 1


def find_matching_open(text: str, close_index: int, open_char: str, close_char: str) -> int | None:
    depth = 0
    index = close_index
    while index >= 0:
        char = text[index]
        if is_literal_quote_start(text, index):
            quote_start = literal_quote_index(text[: index + 1])
            if quote_start is not None:
                index = quote_start - 1
                continue
        if char == close_char:
            depth += 1
        elif char == open_char:
            depth -= 1
            if depth == 0:
                return index
        index -= 1
    return None


def is_simple_member_receiver(text: str) -> bool:
    return re.fullmatch(r"\^?[A-Za-z_][A-Za-z0-9_']*", text) is not None


def is_member_receiver_char(char: str) -> bool:
    return char.isalnum() or char in {"_", "'", GENERATED_SYM_PREFIX}


def scan_identifier(text: str, start: int) -> int | None:
    if start >= len(text) or not re.match(r"[A-Za-z_]", text[start]):
        return None
    index = start + 1
    while index < len(text) and re.match(r"[A-Za-z0-9_']", text[index]):
        index += 1
    return index
