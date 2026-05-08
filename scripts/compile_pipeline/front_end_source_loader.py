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
    parse_located_module_text,
    remove_comments_located,
    strip_leading_bom,
    strip_outer_blank_lines_located,
)

STDIN_SOURCE = "__stdin__"


def run(text: str, base_dir: Path | str = ".", *, source: str = STDIN_SOURCE, allow_imports: bool = True) -> SourceFileAst:
    if not allow_imports and any(IMPORT_RE.match(line) for line in text.splitlines()):
        raise CompileError("$import is not supported when reading module text from stdin")
    tokens = load_tokens()
    root = strip_leading_bom(make_located_text(text, source, import_origin=False))
    normalized = normalize_latex_located(root, tokens)
    expanded = expand_for_checking(normalized, base_dir=Path(base_dir).resolve(), seen=set())
    cleaned = strip_outer_blank_lines_located(remove_comments_located(expanded))
    ast = build_source_file_ast(cleaned, source, import_paths(text, Path(base_dir).resolve()))
    ast.import_count = len({position.file for position in expanded.positions if position.import_origin})
    ast.line_count = len(cleaned.text.splitlines())
    return ast


def build_source_file_ast(located: LocatedText, source: str, imports: list[str] | None = None) -> SourceFileAst:
    parsed = parse_located_module_text(located)
    root = SourceFileAst(source=source, source_loc=parsed.source_loc, imports=imports or [], line_count=len(located.text.splitlines()))
    root.modules.append(SourceModule(type="source_file", source_loc=parsed.source_loc, lowered_module=parsed.module))
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
