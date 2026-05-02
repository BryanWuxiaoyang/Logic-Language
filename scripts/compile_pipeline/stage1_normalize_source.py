#!/usr/bin/env python3
"""Stage 1: normalize source text and expand explicit imports."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compile_module import CompileError, IMPORT_RE, load_tokens, normalize_latex, remove_comments

STDIN_SOURCE = "__stdin__"


@dataclass(frozen=True)
class SourceLoc:
    source: str
    line: int
    column: int
    end_line: int
    end_column: int

    def to_json(self) -> dict[str, int | str]:
        return {
            "source": self.source,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True)
class NormalizedSource:
    text: str
    source: str
    loc: SourceLoc
    import_count: int

    def summary(self) -> str:
        return "\n".join(
            [
                "stage: stage1_normalize_source",
                f"source: {self.source}",
                f"imports: {self.import_count}",
                f"lines: {len(self.text.splitlines())}",
                "normalized_text:",
                self.text.rstrip(),
            ]
        )


def run(text: str, base_dir: Path | str = ".", *, source: str = STDIN_SOURCE, allow_imports: bool = True) -> NormalizedSource:
    if not allow_imports and any(IMPORT_RE.match(line) for line in text.splitlines()):
        raise CompileError("$import is not supported when reading module text from stdin")
    tokens = load_tokens()
    effective_source = imported_only_source(text, Path(base_dir).resolve()) or source
    expanded, import_count = expand_imports_text(text, Path(base_dir).resolve(), set())
    normalized = normalize_latex(expanded, tokens)
    normalized = remove_comments(normalized)
    loc = whole_text_loc(normalized, effective_source)
    return NormalizedSource(text=normalized, source=effective_source, loc=loc, import_count=import_count)


def imported_only_source(text: str, base_dir: Path) -> str | None:
    imports: list[Path] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = IMPORT_RE.match(line)
        if match is None:
            return None
        raw_path = match.group("path").strip().strip("\"'")
        import_path = Path(raw_path)
        if not import_path.is_absolute():
            import_path = base_dir / import_path
        imports.append(import_path.resolve())
    if len(imports) == 1:
        return str(imports[0])
    return None


def expand_imports_text(text: str, base_dir: Path, seen: set[Path]) -> tuple[str, int]:
    output_lines: list[str] = []
    import_count = 0
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if not match:
            output_lines.append(line)
            continue
        raw_path = match.group("path").strip().strip("\"'")
        import_path = Path(raw_path)
        if not import_path.is_absolute():
            import_path = base_dir / import_path
        import_path = import_path.resolve()
        if import_path in seen:
            raise CompileError(f"cyclic import: {import_path}")
        if not import_path.exists():
            raise CompileError(f"import not found: {import_path}")
        imported_text = import_path.read_text(encoding="utf-8")
        imported, nested_count = expand_imports_text(imported_text, import_path.parent, seen | {import_path})
        indent = match.group("indent")
        output_lines.extend(indent + imported_line if imported_line else imported_line for imported_line in imported.splitlines())
        import_count += 1 + nested_count
    return "\n".join(output_lines), import_count


def whole_text_loc(text: str, source: str) -> SourceLoc:
    lines = text.splitlines() or [""]
    return SourceLoc(source=source, line=1, column=1, end_line=len(lines), end_column=len(lines[-1]) + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run compile pipeline stage 1 normalization.")
    parser.add_argument("file", nargs="?", type=Path, help="module file; defaults to stdin")
    parser.add_argument("--text", help="module text; overrides file/stdin")
    parser.add_argument("--base-dir", type=Path, default=None, help="base directory for $import")
    args = parser.parse_args()

    if args.text is not None:
        source = args.text
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    elif args.file is not None:
        source = args.file.read_text(encoding="utf-8")
        source_name = str(args.file.resolve())
        base_dir = args.base_dir or args.file.resolve().parent
        allow_imports = True
    else:
        source = sys.stdin.read()
        source_name = STDIN_SOURCE
        base_dir = args.base_dir or Path.cwd()
        allow_imports = False
    try:
        result = run(source, base_dir, source=source_name, allow_imports=allow_imports)
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.write(result.summary())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
