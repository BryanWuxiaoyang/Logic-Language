#!/usr/bin/env python3
"""Stage 1: normalize source text and expand explicit imports."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_pipeline.ast_nodes import (
    ClassDecl,
    ClassFieldAssign,
    ClassFieldDecl,
    ClassMethodDecl,
    ExprNode,
    FunctionDecl,
    SourceFileAst,
    SourceLoc,
    SourceModule,
    SourceStatement,
    SymNode,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import (
    collect_indented_block,
    class_header_sym,
    explicit_class_header_sym,
    is_bare_coloncolon_field_shorthand,
    logical_lines,
    parse_class_field_assignment,
    parse_declaration,
    parse_premise_declaration,
    parse_signature_terms,
    split_indent,
    top_level_assignment_index,
    unindent_block,
)
from compile_pipeline.source_utils import IMPORT_RE, load_tokens, normalize_latex, remove_comments, resolve_import_path

STDIN_SOURCE = "__stdin__"
SOURCE_AST_INFIX_OPERATORS = ("&&", "||", "!=", "?", "?", "?", "?", "?", "?", "?", "?", "~", "=", ">", "<", "+", "-", "*", "/", "?", "?", "?", "?")


@dataclass(frozen=True)
class NormalizedSource:
    text: str
    source: str
    loc: SourceLoc
    import_count: int
    ast: SourceFileAst

    def summary(self) -> str:
        return "\n".join(
            [
                "stage: stage1_normalize_source",
                f"source: {self.source}",
                f"imports: {self.import_count}",
                f"lines: {len(self.text.splitlines())}",
                "normalized_text:",
                self.text.rstrip(),
            ]
        )


def run(text: str, base_dir: Path | str = ".", *, source: str = STDIN_SOURCE, allow_imports: bool = True) -> NormalizedSource:
    if not allow_imports and any(IMPORT_RE.match(line) for line in text.splitlines()):
        raise CompileError("$import is not supported when reading module text from stdin")
    tokens = load_tokens()
    effective_source = imported_only_source(text, Path(base_dir).resolve()) or source
    expanded, import_count = expand_imports_text(text, Path(base_dir).resolve(), stack=set(), expanded=set())
    normalized = normalize_latex(expanded, tokens)
    normalized = remove_comments(normalized)
    loc = whole_text_loc(normalized, effective_source)
    ast = build_source_file_ast(normalized, effective_source, loc, import_paths(text, Path(base_dir).resolve()))
    return NormalizedSource(text=normalized, source=effective_source, loc=loc, import_count=import_count, ast=ast)


def imported_only_source(text: str, base_dir: Path) -> str | None:
    imports: list[Path] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = IMPORT_RE.match(line)
        if match is None:
            return None
        raw_path = match.group("path").strip().strip("\"'")
        imports.append(resolve_import_path(raw_path, base_dir))
    if len(imports) == 1:
        return str(imports[0])
    return None


def expand_imports_text(text: str, base_dir: Path, *, stack: set[Path], expanded: set[Path]) -> tuple[str, int]:
    output_lines: list[str] = []
    import_count = 0
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if not match:
            output_lines.append(line)
            continue
        raw_path = match.group("path").strip().strip("\"'")
        import_path = resolve_import_path(raw_path, base_dir)
        if import_path in stack:
            raise CompileError(f"cyclic import: {import_path}")
        if import_path in expanded:
            continue
        if not import_path.exists():
            raise CompileError(f"import not found: {import_path}")
        expanded.add(import_path)
        imported_text = import_path.read_text(encoding="utf-8")
        imported, nested_count = expand_imports_text(imported_text, import_path.parent, stack=stack | {import_path}, expanded=expanded)
        indent = match.group("indent")
        output_lines.extend(indent + imported_line if imported_line else imported_line for imported_line in imported.splitlines())
        import_count += 1 + nested_count
    return "\n".join(output_lines), import_count


def whole_text_loc(text: str, source: str) -> SourceLoc:
    lines = text.splitlines() or [""]
    return SourceLoc(source=source, line=1, column=1, end_line=len(lines), end_column=len(lines[-1]) + 1)



def import_paths(text: str, base_dir: Path) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if match is None:
            continue
        raw_path = match.group("path").strip().strip("\"'")
        paths.append(str(resolve_import_path(raw_path, base_dir)))
    return paths


def build_source_file_ast(text: str, source: str, loc: SourceLoc, imports: list[str] | None = None) -> SourceFileAst:
    root = SourceFileAst(text=text, source=source, source_loc=loc, imports=imports or [])
    root.modules.append(parse_source_module(text, loc))
    return root


def parse_source_module(text: str, loc: SourceLoc, module_type: str = "source_file") -> SourceModule:
    module = SourceModule(type=module_type, text=text, source_loc=loc)
    lines = logical_lines(text)
    index = 0
    while index < len(lines):
        line = lines[index]
        indent, content = split_indent(line)
        line_loc = line_source_loc(loc.source, text, line)
        block: list[str] = []
        next_index = index + 1
        if index + 1 < len(lines):
            block, next_index = collect_indented_block(lines, index + 1, indent)
        class_name = class_header_sym(content)
        if class_name is not None and block:
            module.classes.append(parse_class_decl(class_name, block, loc.source, text, line_loc))
            index = next_index
            continue
        premise_decl = parse_premise_declaration(content)
        declaration = premise_decl or parse_declaration(content)
        if declaration is not None:
            name, inputs, outputs, _arrow = declaration
            body_text = unindent_block(block) if block else ""
            body = parse_statement_list(body_text, loc.source) if body_text else []
            module.declarations.append(
                FunctionDecl(
                    name=SymNode(name, line_loc),
                    inputs=[SymNode(sym, line_loc) for sym in inputs],
                    outputs=[SymNode(sym, line_loc) for sym in outputs],
                    body=body,
                    source_loc=line_loc,
                    premise=premise_decl is not None,
                )
            )
            index = next_index if block else index + 1
            continue
        module.statements.append(SourceStatement(content, line_loc, parse_expr_ast(content, line_loc)))
        index += 1
    return module


def parse_class_decl(class_name: str, block: list[str], source: str, full_text: str, loc: SourceLoc) -> ClassDecl:
    class_sym = SymNode(class_name, loc)
    decl = ClassDecl(name=class_sym, source_loc=loc)
    lines = logical_lines(unindent_block(block))
    index = 0
    while index < len(lines):
        line = lines[index]
        indent, content = split_indent(line)
        line_loc = line_source_loc(source, full_text, content)
        nested: list[str] = []
        next_index = index + 1
        if index + 1 < len(lines):
            nested, next_index = collect_indented_block(lines, index + 1, indent)
        member = content[2:].strip() if content.startswith("::") else content
        assignment = parse_class_field_assignment(f"{class_name}::{member}")
        if assignment is not None:
            decl.members.append(
                ClassFieldAssign(
                    name=SymNode(assignment.field_name, line_loc),
                    owner=class_sym,
                    rhs_text=assignment.rhs,
                    rhs=parse_expr_ast(assignment.rhs, line_loc),
                    source_loc=line_loc,
                    premise=assignment.premise,
                )
            )
            index = next_index
            continue
        parsed_decl = parse_declaration(f"{class_name}::{member}")
        if parsed_decl is not None:
            name, inputs, outputs, _arrow = parsed_decl
            body_text = unindent_block(nested) if nested else ""
            func = FunctionDecl(
                name=SymNode(name, line_loc),
                inputs=[SymNode(sym, line_loc) for sym in inputs],
                outputs=[SymNode(sym, line_loc) for sym in outputs],
                owner=class_sym,
                body=parse_statement_list(body_text, source) if body_text else [],
                source_loc=line_loc,
            )
            decl.members.append(ClassMethodDecl(func, line_loc))
        elif is_bare_coloncolon_field_shorthand(f"{class_name}::{member}"):
            decl.members.append(ClassFieldDecl(name=SymNode(member, line_loc), owner=class_sym, source_loc=line_loc))
        else:
            decl.members.append(ClassFieldDecl(name=SymNode(member, line_loc), owner=class_sym, source_loc=line_loc))
        index = next_index if nested else index + 1
    return decl


def parse_statement_list(text: str, source: str) -> list[SourceStatement]:
    statements: list[SourceStatement] = []
    for line in logical_lines(text):
        loc = line_source_loc(source, text, line)
        _, content = split_indent(line)
        statements.append(SourceStatement(content, loc, parse_expr_ast(content, loc)))
    return statements


def parse_expr_ast(text: str, loc: SourceLoc) -> ExprNode:
    stripped = text.strip()
    if not stripped:
        return ExprNode("empty", loc, text=stripped)
    if stripped.startswith("|") and not stripped.startswith("|-"):
        return parse_expr_ast(stripped[1:].strip(), loc)
    assignment = top_level_assignment_index(stripped)
    if assignment is not None:
        lhs = stripped[:assignment].strip()
        rhs = stripped[assignment + 1 :].strip()
        return ExprNode("call", loc, text=stripped, call_sym=SymNode("=", loc), args=[parse_expr_ast(lhs, loc), parse_expr_ast(rhs, loc)])
    infix = parse_top_level_infix(stripped)
    if infix is not None:
        lhs, op, rhs = infix
        return ExprNode("call", loc, text=stripped, call_sym=SymNode(op, loc), args=[parse_expr_ast(lhs, loc), parse_expr_ast(rhs, loc)])
    index_call = parse_index_expr(stripped)
    if index_call is not None:
        receiver, index_text = index_call
        return ExprNode("call", loc, text=stripped, call_sym=SymNode("[]", loc), args=[parse_expr_ast(receiver, loc), parse_expr_ast(index_text, loc)])
    call = parse_simple_call(stripped)
    if call is not None:
        name, args = call
        return ExprNode("call", loc, text=stripped, call_sym=SymNode(name, loc), args=[parse_expr_ast(arg, loc) for arg in args])
    if stripped.startswith("(") and stripped.endswith(")"):
        return ExprNode("tuple", loc, text=stripped, items=[parse_expr_ast(item, loc) for item in parse_signature_terms(stripped[1:-1])])
    if stripped.startswith("{") and stripped.endswith("}"):
        return ExprNode("set", loc, text=stripped, items=[parse_expr_ast(item, loc) for item in parse_signature_terms(stripped[1:-1])])
    if stripped.startswith("'") or stripped.startswith('"') or stripped.replace(".", "", 1).isdigit():
        return ExprNode("literal", loc, text=stripped, value=stripped)
    return ExprNode("sym", loc, text=stripped, sym=SymNode(stripped, loc))


def parse_simple_call(text: str) -> tuple[str, list[str]] | None:
    if not text.endswith(")"):
        return None
    open_index = text.find("(")
    if open_index <= 0:
        return None
    name = text[:open_index].strip()
    if not name:
        return None
    inner = text[open_index + 1 : -1]
    return name, parse_signature_terms(inner)



def parse_index_expr(text: str) -> tuple[str, str] | None:
    if not text.endswith("]"):
        return None
    start = text.rfind("[")
    if start <= 0:
        return None
    receiver = text[:start].strip()
    index_text = text[start + 1 : -1].strip()
    if not receiver or not index_text:
        return None
    return receiver, index_text


def parse_top_level_infix(text: str) -> tuple[str, str, str] | None:
    match = find_top_level_infix(text)
    if match is None:
        return None
    index, op = match
    lhs = text[:index].strip()
    rhs = text[index + len(op) :].strip()
    if not lhs or not rhs:
        return None
    return lhs, op, rhs


def find_top_level_infix(text: str) -> tuple[int, str] | None:
    depth = 0
    quote: str | None = None
    candidates: list[tuple[int, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote and (index == 0 or text[index - 1] != "\\"):
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in "([{":
            depth += 1
            index += 1
            continue
        if char in ")]}":
            depth = max(depth - 1, 0)
            index += 1
            continue
        if depth == 0:
            for op in SOURCE_AST_INFIX_OPERATORS:
                if text.startswith(op, index):
                    if op == "-" and (index == 0 or text[index - 1].isspace() and index + 1 < len(text) and text[index + 1].isdigit()):
                        continue
                    candidates.append((index, op))
                    break
        index += 1
    return candidates[-1] if candidates else None


def line_source_loc(source: str, full_text: str, line_text: str) -> SourceLoc:
    needle = line_text.strip()
    if not needle:
        return SourceLoc(source, 1, 1, 1, 1)
    for line_no, line in enumerate(full_text.splitlines() or [full_text], start=1):
        column = line.find(needle)
        if column >= 0:
            return SourceLoc(source, line_no, column + 1, line_no, column + len(needle) + 1)
    return SourceLoc(source, 1, 1, 1, len(needle) + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 1 normalization.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    args = parser.parse_args()

    if args.text is not None:
        source = args.text
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    elif args.file is not None:
        source = args.file.read_text(encoding="utf-8")
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
        allow_imports = True
    else:
        source = sys.stdin.read()
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    try:
        result = run(source, base_dir, source=source_name, allow_imports=allow_imports)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(result.summary())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
