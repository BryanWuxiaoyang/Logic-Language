#!/usr/bin/env python3
"""Stage 1 source loader: parse source text into located typed AST."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import (
    SourceFileAst,
    SourceModule,
)
from compile_pipeline.errors import CompileError
from compile_pipeline.source_utils import IMPORT_RE, load_tokens, resolve_import_path
from compile_pipeline.module_parser import (
    expand_for_checking,
    LocatedText,
    make_located_text,
    normalize_latex_located,
    parse_located_source_module_text,
    remove_comments_located,
    strip_leading_bom,
    strip_outer_blank_lines_located,
)

STDIN_SOURCE = "__stdin__"


def run(text: str, base_dir: Path | str = ".", *, source: str = STDIN_SOURCE, allow_imports: bool = True) -> SourceFileAst:
    parse_ast = run_parse_ast(text, base_dir, source=source, allow_imports=allow_imports)
    from compile_pipeline.stage1_front_end import lower_source_file_ast

    return lower_source_file_ast(parse_ast)


def run_parse_ast(text: str, base_dir: Path | str = ".", *, source: str = STDIN_SOURCE, allow_imports: bool = True) -> SourceFileAst:
    cleaned, expanded, imports = prepare_located_source(text, base_dir, source=source, allow_imports=allow_imports)
    ast = build_source_file_ast(cleaned, source, imports, include_lowered=False)
    ast.import_count = len({position.file for position in expanded.positions if position.import_origin})
    ast.line_count = len(cleaned.text.splitlines())
    return ast


def prepare_located_source(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = STDIN_SOURCE,
    allow_imports: bool = True,
) -> tuple[LocatedText, LocatedText, list[str]]:
    if not allow_imports and any(IMPORT_RE.match(line) for line in text.splitlines()):
        raise CompileError("$import is not supported when reading module text from stdin")
    tokens = load_tokens()
    root = strip_leading_bom(make_located_text(text, source, import_origin=False))
    normalized = normalize_latex_located(root, tokens)
    expanded = expand_for_checking(normalized, base_dir=Path(base_dir).resolve(), seen=set())
    cleaned = strip_outer_blank_lines_located(remove_comments_located(expanded))
    return cleaned, expanded, import_paths(text, Path(base_dir).resolve())


def build_source_file_ast(
    located: LocatedText,
    source: str,
    imports: list[str] | None = None,
    *,
    include_lowered: bool = True,
) -> SourceFileAst:
    parsed_source = parse_located_source_module_text(located)
    root = SourceFileAst(source=source, source_loc=parsed_source.source_loc, imports=imports or [], line_count=len(located.text.splitlines()))
    module = parsed_source.module
    root.modules.append(module)
    return root


def import_paths(text: str, base_dir: Path) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if match is None:
            continue
        raw_path = match.group("path").strip().strip("\"'")
        paths.append(str(resolve_import_path(raw_path, base_dir)))
    return paths
