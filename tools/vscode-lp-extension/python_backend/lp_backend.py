from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from interactive_analyzer import LogicProgramAnalyzer
    from semantic_parser import (
        Import,
        ParserError,
        TokenizerError,
        _build_semantic_index,
        parse_program_text,
    )
except ImportError as exc:  # pragma: no cover - runtime wiring failure
    raise SystemExit(
        "failed to import logic-language backend modules; "
        "ensure PYTHONPATH points at skills/logic-language/scripts"
    ) from exc


@dataclass(slots=True)
class Diagnostic:
    file: str
    line: int
    column: int
    severity: str
    source: str
    message: str

    def to_json(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
            "source": self.source,
            "message": self.message,
        }


@dataclass(slots=True)
class ImportRef:
    module_path: str
    line: int
    column: int


@dataclass(slots=True)
class ParseResult:
    path: Path
    root: object | None
    diagnostics: list[Diagnostic]
    imports: list[ImportRef]
    classes: list[str]
    members: list[str]

    @property
    def ok(self) -> bool:
        return not any(
            diagnostic.source in {"tokenizer", "parser"}
            for diagnostic in self.diagnostics
        )


_ERROR_RE = re.compile(
    r"^(?:(?P<file>.*):)?(?P<line>\d+):(?P<column>\d+): (?P<message>.*)$"
)


def _load_source(path: Path, *, source_text: str | None) -> str:
    if source_text is not None:
        return source_text
    return path.read_text(encoding="utf-8")


def _parse_exception(
    exc: Exception,
    *,
    fallback_file: Path,
    source: str,
) -> Diagnostic:
    text = str(exc).strip()
    match = _ERROR_RE.match(text)
    if match is None:
        return Diagnostic(
            file=str(fallback_file),
            line=1,
            column=1,
            severity="error",
            source=source,
            message=text,
        )

    file_name = match.group("file") or str(fallback_file)
    return Diagnostic(
        file=file_name,
        line=int(match.group("line")),
        column=int(match.group("column")),
        severity="error",
        source=source,
        message=match.group("message"),
    )


def _iter_imports(node) -> list[ImportRef]:
    imports: list[ImportRef] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Import):
            imports.append(
                ImportRef(
                    module_path=current.module_path,
                    line=current.line,
                    column=current.column,
                )
            )
        children = getattr(current, "children", None)
        if callable(children):
            stack.extend(reversed(children()))
    return imports


def _collect_members(index) -> list[str]:
    members = {
        member_name
        for member_names in index.member_names_by_class.values()
        for member_name in member_names
    }
    return sorted(members)


def _parse_program(
    path: Path,
    *,
    source_text: str | None = None,
) -> ParseResult:
    try:
        root = parse_program_text(
            _load_source(path, source_text=source_text),
            source_name=str(path),
        )
    except TokenizerError as exc:
        return ParseResult(
            path=path,
            root=None,
            diagnostics=[_parse_exception(exc, fallback_file=path, source="tokenizer")],
            imports=[],
            classes=[],
            members=[],
        )
    except ParserError as exc:
        return ParseResult(
            path=path,
            root=None,
            diagnostics=[_parse_exception(exc, fallback_file=path, source="parser")],
            imports=[],
            classes=[],
            members=[],
        )

    diagnostics = [
        Diagnostic(
            file=str(path),
            line=issue.line,
            column=issue.column,
            severity="error",
            source="semantic",
            message=issue.message,
        )
        for issue in root.collect_semantic_issues()
    ]
    semantic_index = _build_semantic_index(root)
    return ParseResult(
        path=path,
        root=root,
        diagnostics=diagnostics,
        imports=_iter_imports(root),
        classes=sorted(semantic_index.class_names),
        members=_collect_members(semantic_index),
    )


def _candidate_base_paths(module_path: str, importer_path: Path) -> list[Path]:
    if not module_path:
        return []

    raw_path = Path(module_path)
    if raw_path.is_absolute():
        return [raw_path]

    if module_path.startswith("./") or module_path.startswith("../"):
        return [importer_path.parent / module_path]

    if module_path.startswith(".") and not module_path.startswith("./") and not module_path.startswith("../"):
        return [importer_path.parent / module_path[1:]]

    return [importer_path.parent / module_path, raw_path]


def _resolve_import_path(module_path: str, importer_path: Path) -> Path | None:
    checked: set[str] = set()
    for base_path in _candidate_base_paths(module_path, importer_path):
        candidates = [base_path]
        if base_path.suffix == "":
            candidates.append(base_path.with_suffix(".lp"))

        for candidate in candidates:
            normalized = str(candidate.resolve(strict=False))
            if normalized in checked:
                continue
            checked.add(normalized)
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
    return None


def _normalized_path(path: Path) -> str:
    return str(path.resolve(strict=False))


def collect_diagnostics(path: Path, *, source_text: str | None = None) -> list[dict[str, object]]:
    diagnostics: list[Diagnostic] = []
    parse_cache: dict[str, ParseResult] = {}
    visited: set[str] = set()

    def visit(current_path: Path, *, current_source_text: str | None, stack: list[str]) -> None:
        normalized = _normalized_path(current_path)
        if current_source_text is None and normalized in visited:
            return

        if current_source_text is None and normalized in parse_cache:
            result = parse_cache[normalized]
        else:
            result = _parse_program(current_path, source_text=current_source_text)
            if current_source_text is None:
                parse_cache[normalized] = result

        diagnostics.extend(result.diagnostics)
        if current_source_text is None:
            visited.add(normalized)

        if result.root is None:
            return

        next_stack = stack + [normalized]
        for import_ref in result.imports:
            resolved_path = _resolve_import_path(import_ref.module_path, current_path)
            if resolved_path is None:
                diagnostics.append(
                    Diagnostic(
                        file=str(current_path),
                        line=import_ref.line,
                        column=import_ref.column,
                        severity="error",
                        source="import-resolver",
                        message=f"could not resolve import '{import_ref.module_path}'",
                    )
                )
                continue

            resolved_key = _normalized_path(resolved_path)
            if resolved_key in next_stack:
                cycle = " -> ".join(next_stack + [resolved_key])
                diagnostics.append(
                    Diagnostic(
                        file=str(current_path),
                        line=import_ref.line,
                        column=import_ref.column,
                        severity="error",
                        source="import-resolver",
                        message=f"import cycle detected: {cycle}",
                    )
                )
                continue

            visit(resolved_path, current_source_text=None, stack=next_stack)

    visit(path.resolve(), current_source_text=source_text, stack=[])
    return [diagnostic.to_json() for diagnostic in diagnostics]


def index_file(path: Path) -> dict[str, object]:
    result = _parse_program(path.resolve())
    return {
        "file": str(path.resolve()),
        "imports": [import_ref.module_path for import_ref in result.imports],
        "classes": result.classes,
        "members": result.members,
        "ok": result.ok,
        "diagnosticsCount": len(result.diagnostics),
    }


def query_class(path: Path, class_name: str, *, full: bool) -> dict[str, object]:
    analyzer = LogicProgramAnalyzer(path.resolve())
    return {
        "title": f"Class: {class_name}",
        "content": analyzer.show_class(class_name, full=full),
    }


def query_inheritance(path: Path, class_name: str | None) -> dict[str, object]:
    analyzer = LogicProgramAnalyzer(path.resolve())
    if class_name:
        title = f"Inheritance: {class_name}"
    else:
        title = f"Inheritance: {path.name}"
    return {
        "title": title,
        "content": analyzer.show_class_inheritance_graph(class_name),
    }


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JSON backend for the Logic LP VSCode extension."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnostics_parser = subparsers.add_parser("diagnostics")
    diagnostics_parser.add_argument("--file", required=True)
    diagnostics_parser.add_argument("--stdin", action="store_true")

    index_parser = subparsers.add_parser("index-file")
    index_parser.add_argument("--file", required=True)

    query_class_parser = subparsers.add_parser("query-class")
    query_class_parser.add_argument("--file", required=True)
    query_class_parser.add_argument("--class", dest="class_name", required=True)
    query_class_parser.add_argument("--full", action="store_true")

    query_inheritance_parser = subparsers.add_parser("query-inheritance")
    query_inheritance_parser.add_argument("--file", required=True)
    query_inheritance_parser.add_argument("--class", dest="class_name")

    args = parser.parse_args(argv)

    try:
        if args.command == "diagnostics":
            source_text = sys.stdin.read() if args.stdin else None
            _print_json(
                collect_diagnostics(Path(args.file), source_text=source_text)
            )
            return 0

        if args.command == "index-file":
            _print_json(index_file(Path(args.file)))
            return 0

        if args.command == "query-class":
            _print_json(
                query_class(
                    Path(args.file),
                    args.class_name,
                    full=args.full,
                )
            )
            return 0

        if args.command == "query-inheritance":
            _print_json(query_inheritance(Path(args.file), args.class_name))
            return 0

        parser.error(f"unknown command: {args.command}")
    except (OSError, TokenizerError, ParserError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
