#!/usr/bin/env python3
"""Stage 1 front-end: parse imports/source and perform surface desugaring."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from AST import SourceFileAst
from compile_pipeline.errors import CompileError
from compile_pipeline.front_end_source_loader import run as parse_source
from compile_pipeline.front_end_desugar import run as desugar_source


@dataclass(frozen=True)
class FrontEndResult:
    ast: SourceFileAst
    import_count: int
    diagnostics: list[dict[str, object]]

    def summary(self) -> str:
        module = self.ast.modules[0].lowered_module if self.ast.modules else None
        return json.dumps(
            {
                "stage": "stage1_front_end",
                "imports": self.import_count,
                "diagnostics": len(self.diagnostics),
                "root": {
                    "kind": getattr(module, "type", None),
                    "bound_syms": len(getattr(module, "syms", []) or []),
                    "premise_statements": len(getattr(module, "predicate_statements", []) or []),
                    "target_statements": len(getattr(module, "target_statements", []) or []),
                },
            },
            ensure_ascii=False,
        )


def run(
    text: str,
    base_dir: Path | str = ".",
    *,
    source: str = "__stdin__",
    allow_imports: bool = True,
) -> FrontEndResult:
    source_ast = parse_source(text, base_dir, source=source, allow_imports=allow_imports)
    desugared = desugar_source(source_ast, Path(base_dir).resolve())
    if any(entry.get("type") == "error" for entry in desugared.diagnostics):
        raise CompileError(format_diagnostics(desugared.diagnostics))
    return FrontEndResult(
        ast=desugared.ast,
        import_count=desugared.import_count,
        diagnostics=desugared.diagnostics,
    )


def format_diagnostics(diagnostics: list[dict[str, object]]) -> str:
    lines = ["stage1 front-end diagnostics failed:"]
    for entry in diagnostics:
        file = str(entry.get("file", "<ast>"))
        line = int(entry.get("lineno", 0) or 0) + 1
        column = int(entry.get("col_start_no", 0) or 0) + 1
        code = str(entry.get("code", "front_end_error"))
        reason = str(entry.get("reason", "front-end diagnostic failed"))
        lines.append(f"{file}:{line}:{column}: {code}: {reason}")
    return "\n".join(lines)
