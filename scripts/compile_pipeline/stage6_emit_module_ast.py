#!/usr/bin/env python3
"""Stage 6: emit module_AST JSON and readable summaries."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_module import CompileError
from compile_pipeline.stage5_lower_to_module_ast import ModuleAstResult, run as lower_to_ast


@dataclass(frozen=True)
class EmittedModuleAst:
    ast: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return self.ast

    def readable(self) -> str:
        lines: list[str] = []
        summarize(self.ast, lines, 0)
        return "\n".join(lines)

    def summary(self) -> str:
        return "\n".join(["stage: stage6_emit_module_ast", self.readable()])


def run(lowered: ModuleAstResult | str) -> EmittedModuleAst:
    if isinstance(lowered, str):
        lowered = lower_to_ast(lowered)
    return EmittedModuleAst(ast=lowered.ast)


def summarize(node: dict[str, Any], lines: list[str], indent: int) -> None:
    pad = " " * indent
    kind = node.get("kind", "<unknown>")
    if kind in {"set_stmt", "quantified_stmt"}:
        quantifier = node.get("quantifier_sym", {}).get("name")
        suffix = f" quantifier={quantifier}" if quantifier else ""
        lines.append(f"{pad}{kind}{suffix}")
        lines.append(f"{pad}  bound: {', '.join(sym.get('name', '?') for sym in node.get('bound_syms', []))}")
        for field in ("premise_binding_stmts", "premise_PSs", "target_PSs"):
            lines.append(f"{pad}  {field}: {len(node.get(field, []))}")
        return
    if kind == "binding_stmt":
        lines.append(f"{pad}binding {node.get('dst_sym', {}).get('name', '?')} := {node.get('src_stmt', {}).get('kind', '?')}")
        return
    if kind == "func_stmt":
        call = node.get("call_sym", {}).get("name", "?")
        args = ", ".join(arg.get("name", arg.get("kind", "?")) for arg in node.get("arg_sym_list", []))
        lines.append(f"{pad}{call}({args})")
        return
    lines.append(f"{pad}{kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 6 AST emission.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument("--readable", action="store_true", help="print readable summary")
    args = parser.parse_args()
    source = args.text if args.text is not None else args.file.read_text(encoding="utf-8") if args.file is not None else sys.stdin.read()
    try:
        result = run(source)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.readable:
        sys.stdout.write(result.readable())
        sys.stdout.write("\n")
        return 0
    json.dump(result.to_json(), sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
