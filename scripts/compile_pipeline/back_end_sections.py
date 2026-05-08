#!/usr/bin/env python3
"""Back-end section adapter over the front-end module model."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import Module, SourceFileAst
from compile_pipeline.errors import CompileError


@dataclass(frozen=True)
class ParsedModuleSections:
    module: Module
    ast: SourceFileAst | None = None

    def summary(self) -> str:
        return json.dumps(
            {
                "stage": "back_end_sections",
                "root": module_summary(self.module),
            },
            ensure_ascii=False,
        )


def run(source_ast: SourceFileAst) -> ParsedModuleSections:
    if not isinstance(source_ast, SourceFileAst):
        raise CompileError("back_end_sections requires SourceFileAst")
    module = lowered_module_from_ast(source_ast)
    if module is None:
        raise CompileError("back_end_sections requires SourceFileAst with lowered Module")
    return ParsedModuleSections(module=module, ast=source_ast)


def lowered_module_from_ast(source_ast: SourceFileAst | None) -> Module | None:
    if source_ast is None or not source_ast.modules:
        return None
    module = source_ast.modules[0].lowered_module
    return module if isinstance(module, Module) else None


def module_summary(module: Module) -> dict[str, object]:
    child_count = 0
    for statement in [*module.predicate_statements, *module.target_statements]:
        child_count += len(statement.sub_modules)
    return {
        "type": module.type,
        "quantifier": module.quantifier,
        "bound_syms": len(module.syms),
        "premise_statements": len(module.predicate_statements),
        "target_statements": len(module.target_statements),
        "child_modules": child_count,
    }
