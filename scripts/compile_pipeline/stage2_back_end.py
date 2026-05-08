#!/usr/bin/env python3
"""Stage 2 back-end: lower front-end AST to semantic object AST."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import Module_stmt, SourceFileAst, Stmt, object_ast_to_json
from compile_pipeline.errors import CompileError
from compile_pipeline.back_end_sections import run as parse_sections
from compile_pipeline.back_end_statements import run as parse_statements
from compile_pipeline.back_end_lower_object import run as lower_to_object_ast
from compile_pipeline.stage1_front_end import FrontEndResult


@dataclass(frozen=True)
class ObjectAstResult:
    ast: Stmt

    def to_json(self) -> dict[str, object]:
        return object_ast_to_json(self.ast)

    def summary(self) -> str:
        root = self.ast if isinstance(self.ast, Module_stmt) else None
        return json.dumps(
            {
                "stage": "stage2_back_end",
                "root": {
                    "kind": type(self.ast).__name__,
                    "bound_syms": len(root.bound_syms) if root is not None else 0,
                    "premise_binding_stmts": len(root.premise_binding_stmts) if root is not None else 0,
                    "premise_proposition_stmts": len(root.premise_proposition_stmts) if root is not None else 0,
                    "target_proposition_stmts": len(root.target_proposition_stmts) if root is not None else 0,
                },
            },
            ensure_ascii=False,
        )


def run(front_end: FrontEndResult) -> ObjectAstResult:
    if not isinstance(front_end, FrontEndResult):
        raise CompileError("stage2_back_end requires FrontEndResult")
    if not isinstance(front_end.ast, SourceFileAst):
        raise CompileError("stage2_back_end requires FrontEndResult.ast to be an AST.SourceFileAst")
    sections = parse_sections(front_end.ast)
    statements = parse_statements(sections)
    lowered = lower_to_object_ast(statements, front_end.ast.source_loc)
    return ObjectAstResult(ast=lowered.ast)
