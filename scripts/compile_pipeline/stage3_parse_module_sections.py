#!/usr/bin/env python3
"""Stage 3: parse module sections into the legacy structural module model."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_pipeline.ast_nodes import SourceFileAst
from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import Module, ModuleCompiler
from compile_pipeline.source_utils import load_lark_parser


@dataclass(frozen=True)
class ParsedModuleSections:
    module: Module
    ast: SourceFileAst | None = None

    def summary(self) -> str:
        lines: list[str] = ["stage: stage3_parse_module_sections"]
        summarize_module(self.module, lines, 0)
        return "\n".join(lines)


def run(text: str | SourceFileAst | object, parser: Any | None = None) -> ParsedModuleSections:
    source_ast = input_source_ast(text)
    module = lowered_module_from_ast(source_ast)
    if module is not None:
        return ParsedModuleSections(module=module, ast=source_ast)
    parser = load_lark_parser() if parser is None else parser
    source_text = source_ast.text if source_ast is not None else str(text)
    module = ModuleCompiler(parser).compile(strip_artifact_imports(source_text))
    if source_ast is not None and source_ast.modules:
        source_ast.modules[0].lowered_module = module
    return ParsedModuleSections(module=module, ast=source_ast)


def input_source_ast(value: object) -> SourceFileAst | None:
    if isinstance(value, SourceFileAst):
        return value
    ast = getattr(value, "ast", None)
    return ast if isinstance(ast, SourceFileAst) else None


def lowered_module_from_ast(source_ast: SourceFileAst | None) -> Module | None:
    if source_ast is None or not source_ast.modules:
        return None
    module = source_ast.modules[0].lowered_module
    return module if isinstance(module, Module) else None


def strip_artifact_imports(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.strip().startswith("$import")]
    return "\n".join(lines)


def summarize_module(module: Module, lines: list[str], indent: int) -> None:
    pad = " " * indent
    label = module.type
    if module.quantifier:
        label += f"({module.quantifier})"
    lines.append(f"{pad}{label}: bound={module.syms}")
    lines.append(f"{pad}  premise_statements={len(module.predicate_statements)}")
    lines.append(f"{pad}  target_statements={len(module.target_statements)}")
    for statement in [*module.predicate_statements, *module.target_statements]:
        for submodule in statement.sub_modules:
            summarize_module(submodule, lines, indent + 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 3 module-section parsing.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    args = parser.parse_args()
    source = args.text if args.text is not None else args.file.read_text(encoding="utf-8") if args.file is not None else sys.stdin.read()
    try:
        result = run(source)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(result.summary())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
