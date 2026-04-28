from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from expand_module import (
        ParserError,
        TokenizerError,
        collect_full_module_sections,
        is_expanded_module,
        load_module_closure,
        parse_expanded_module,
        render_expanded_module,
    )
    from semantic_parser import Comment, Heading, source_to_program
except ImportError:  # pragma: no cover - module execution fallback
    from .expand_module import (
        ParserError,
        TokenizerError,
        collect_full_module_sections,
        is_expanded_module,
        load_module_closure,
        parse_expanded_module,
        render_expanded_module,
    )
    from .semantic_parser import Comment, Heading, source_to_program


def _has_only_headings(program) -> bool:
    saw_content = False
    for item in program.items:
        if isinstance(item, Comment):
            continue
        if not isinstance(item, Heading):
            return False
        saw_content = True
    return saw_content


def _normalize_module_sections(module_file: str | Path) -> tuple[list[str], list[str]]:
    input_path = Path(module_file).resolve()
    program = source_to_program(input_path, force_file=True)

    if is_expanded_module(program):
        return parse_expanded_module(program)

    if _has_only_headings(program):
        raise ValueError(
            f"{input_path}: unsupported expanded artifact format; expected @named_syms/@conds"
        )

    modules = load_module_closure(input_path)
    return collect_full_module_sections(modules)


def _format_issue(issue) -> str:
    return f"{issue.line}:{issue.column}: {issue.message}"


def merge_module_files(
    module_a: str | Path,
    module_b: str | Path,
    *,
    output_file: str | Path | None = None,
) -> Path:
    module_a_path = Path(module_a).resolve()
    module_b_path = Path(module_b).resolve()

    named_syms_a, conds_a = _normalize_module_sections(module_a_path)
    named_syms_b, conds_b = _normalize_module_sections(module_b_path)

    merged_named_syms = sorted(set(named_syms_a) | set(named_syms_b))
    merged_conds = [*conds_a, *conds_b]
    merged_text = render_expanded_module(merged_named_syms, merged_conds)

    merged_program = source_to_program(merged_text)
    issues = merged_program.collect_semantic_issues()
    if issues:
        issue_text = "\n".join(_format_issue(issue) for issue in issues)
        raise ValueError(f"link failed:\n{issue_text}")

    output_path = (
        module_a_path.with_suffix(".merged.lp")
        if output_file is None
        else Path(output_file).resolve()
    )
    output_path.write_text(merged_text, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Link two logic-language modules into one merged expanded artifact."
        )
    )
    parser.add_argument("module_a", help="Path to the first input .lp module or artifact.")
    parser.add_argument("module_b", help="Path to the second input .lp module or artifact.")
    parser.add_argument(
        "--output",
        help="Path to output merged .lp file (default: <module_a>.merged.lp).",
    )
    args = parser.parse_args(argv)

    try:
        out = merge_module_files(
            args.module_a,
            args.module_b,
            output_file=args.output,
        )
    except (OSError, ValueError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
