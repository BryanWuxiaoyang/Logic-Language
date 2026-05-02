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

from compile_module import CompileError, Module, ModuleCompiler, load_lark_parser, strip_artifact_imports


@dataclass(frozen=True)
class ParsedModuleSections:
    module: Module

    def summary(self) -> str:
        lines: list[str] = ["stage: stage3_parse_module_sections"]
        summarize_module(self.module, lines, 0)
        return "\n".join(lines)


def run(text: str, parser: Any | None = None) -> ParsedModuleSections:
    parser = load_lark_parser() if parser is None else parser
    module = ModuleCompiler(parser).compile(strip_artifact_imports(text))
    return ParsedModuleSections(module=module)


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
