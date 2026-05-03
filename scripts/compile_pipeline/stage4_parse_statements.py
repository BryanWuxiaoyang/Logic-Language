#!/usr/bin/env python3
"""Stage 4: expose parsed statement text for AST lowering."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_pipeline.errors import CompileError
from compile_pipeline.module_sections import Module
from compile_pipeline.stage3_parse_module_sections import ParsedModuleSections, run as parse_sections


@dataclass(frozen=True)
class ParsedStatements:
    module: Module

    def summary(self) -> str:
        lines = ["stage: stage4_parse_statements"]
        summarize_statements(self.module, lines, 0)
        return "\n".join(lines)


def run(parsed: ParsedModuleSections | str) -> ParsedStatements:
    if isinstance(parsed, str):
        parsed = parse_sections(parsed)
    return ParsedStatements(module=parsed.module)


def summarize_statements(module: Module, lines: list[str], indent: int) -> None:
    pad = " " * indent
    lines.append(f"{pad}{module.type}:")
    for statement in module.predicate_statements:
        lines.append(f"{pad}  premise: {statement.text}")
        for submodule in statement.sub_modules:
            summarize_statements(submodule, lines, indent + 4)
    for statement in module.target_statements:
        lines.append(f"{pad}  target: {statement.text}")
        for submodule in statement.sub_modules:
            summarize_statements(submodule, lines, indent + 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 4 statement parsing.")
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
