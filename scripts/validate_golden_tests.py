#!/usr/bin/env python3
"""Report compile/disassemble differences for golden_tests.md pairs."""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_module import CompileError, run_compile_pipeline
from translate_AST_to_source import translate_ast_to_source


PAIR_RE = re.compile(
    r"^##\s+(?P<name>[^\n]+)\n\s*\"(?P<source>.*?)\"\s*=\s*\"(?P<expected>.*?)\"",
    flags=re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class GoldenPair:
    name: str
    source: str
    expected: str


def parse_pairs(text: str) -> list[GoldenPair]:
    return [
        GoldenPair(
            match.group("name").strip(),
            trim_snippet(match.group("source")),
            trim_snippet(match.group("expected")),
        )
        for match in PAIR_RE.finditer(text)
    ]


def trim_snippet(text: str) -> str:
    return text.strip("\n") + "\n"


def compile_disassemble(text: str, *, base_dir: Path) -> tuple[bool, str]:
    try:
        ast = run_compile_pipeline(text, base_dir=base_dir, allow_imports=True).ast
    except (CompileError, OSError) as error:
        return False, str(error)
    return True, translate_ast_to_source(ast).rstrip() + "\n"


def report_pair(pair: GoldenPair, *, base_dir: Path) -> str:
    actual_ok, actual = compile_disassemble(pair.source, base_dir=base_dir)
    expected_ok, expected = compile_disassemble(pair.expected, base_dir=base_dir)
    lines = [f"## {pair.name}", f"source_compile: {'ok' if actual_ok else 'failed'}", f"expected_compile: {'ok' if expected_ok else 'failed'}"]
    if not actual_ok or not expected_ok:
        if not actual_ok:
            lines.extend(["actual_error:", actual])
        if not expected_ok:
            lines.extend(["expected_error:", expected])
        return "\n".join(lines)
    if actual == expected:
        lines.append("status: equivalent after compile/disassemble")
        return "\n".join(lines)
    lines.append("status: differs after compile/disassemble")
    lines.extend(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{pair.name}: expected",
            tofile=f"{pair.name}: actual",
            lineterm="",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report golden compile/disassemble differences.")
    parser.add_argument("file", type=Path, help="golden_tests.md file")
    args = parser.parse_args()
    try:
        text = args.file.read_text(encoding="utf-8")
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    pairs = parse_pairs(text)
    if not pairs:
        print("no golden pairs found", file=sys.stderr)
        return 1
    base_dir = args.file.resolve().parent
    print(f"golden_pairs: {len(pairs)}")
    for index, pair in enumerate(pairs):
        if index:
            print()
        print(report_pair(pair, base_dir=base_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
