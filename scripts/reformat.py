from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LATEX_NAME_TO_SYMBOL: dict[str, str] = {
    # Quantifiers / logic
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "land": "∧",
    "lor": "∨",
    # Set / relation
    "ge": "≥",
    "le": "≤",
    "neq": "≠",
    "in": "∈",
    "notin": "∉",
    "subseteq": "⊆",
    "subset_eq": "⊆",
    "subset": "⊂",
    "supseteq": "⊇",
    "supset": "⊃",
    "cup": "∪",
    "cap": "∩",
    "emptyset": "∅",
    # Arrows / implication
    "to": "→",
    "Rightarrow": "⇒",
    "implies": "⇒",
    # Existing aliases
    "included_in": "⊆",
    "concat": "৹",
}
NORMALIZED_ASCII_SYMBOLS: dict[str, str] = {
    "｜": "|",
}
LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z_][A-Za-z0-9_]*)")


def reformat_text(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False

    while i < len(text):
        ch = text[i]

        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                i += 1
                out.append(text[i])
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "#":
            newline = text.find("\n", i)
            if newline == -1:
                out.append(text[i:])
                break
            out.append(text[i:newline + 1])
            i = newline + 1
            continue

        mapped = NORMALIZED_ASCII_SYMBOLS.get(ch)
        if mapped is not None:
            out.append(mapped)
            i += 1
            continue

        if ch == "\\":
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            name = text[i + 1 : j]
            if name:
                out.append(LATEX_NAME_TO_SYMBOL.get(name, text[i:j]))
                i = j
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def find_unconverted_latex_commands(text: str) -> list[tuple[int, int, str]]:
    pending: list[tuple[int, int, str]] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        index = 0
        in_string = False
        while index < len(line):
            ch = line[index]
            if in_string:
                if ch == "\\" and index + 1 < len(line):
                    index += 2
                    continue
                if ch == '"':
                    in_string = False
                index += 1
                continue
            if ch == "#":
                break
            if ch == '"':
                in_string = True
                index += 1
                continue
            if ch == "\\":
                match = LATEX_COMMAND_RE.match(line, index)
                if match is not None:
                    pending.append((line_no, index + 1, match.group(1)))
                    index = match.end()
                    continue
            index += 1
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reformat a .lp file by normalizing symbols while preserving original spaces/newlines."
        )
    )
    parser.add_argument("lp_path", help="Path to the input .lp file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.lp_path)
    text = source_path.read_text(encoding="utf-8")
    normalized = reformat_text(text)
    unresolved = find_unconverted_latex_commands(normalized)
    if unresolved:
        first_line, first_column, first_name = unresolved[0]
        print(
            (
                f"{source_path}:{first_line}:{first_column}: "
                f"unconverted LaTeX command '\\{first_name}'. "
                "Extend LATEX_NAME_TO_SYMBOL in scripts/reformat.py."
            ),
            file=sys.stderr,
        )
        return 1

    reformatted = normalized

    if args.output:
        Path(args.output).write_text(reformatted, encoding="utf-8")
    else:
        sys.stdout.write(reformatted)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
