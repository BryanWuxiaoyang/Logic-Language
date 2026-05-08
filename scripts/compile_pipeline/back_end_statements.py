#!/usr/bin/env python3
"""Back-end statement adapter over typed front-end statement nodes."""

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
from compile_pipeline.back_end_sections import ParsedModuleSections


@dataclass(frozen=True)
class ParsedStatements:
    module: Module
    ast: SourceFileAst | None = None

    def summary(self) -> str:
        return json.dumps(
            {
                "stage": "back_end_statements",
                "root": module_summary(self.module),
            },
            ensure_ascii=False,
        )


def run(parsed: ParsedModuleSections) -> ParsedStatements:
    if not isinstance(parsed, ParsedModuleSections):
        raise CompileError("back_end_statements requires ParsedModuleSections")
    return ParsedStatements(module=parsed.module, ast=parsed.ast)


def module_summary(module: Module) -> dict[str, object]:
    child_count = 0
    for statement in module.predicate_statements:
        child_count += len(statement.sub_modules)
    for statement in module.target_statements:
        child_count += len(statement.sub_modules)
    return {
        "type": module.type,
        "bound_syms": len(module.syms),
        "premise_typed_exprs": sum(1 for statement in module.predicate_statements if statement.expr is not None),
        "target_typed_exprs": sum(1 for statement in module.target_statements if statement.expr is not None),
        "markers": sum(1 for statement in [*module.predicate_statements, *module.target_statements] if statement.marker is not None),
        "child_modules": child_count,
    }
