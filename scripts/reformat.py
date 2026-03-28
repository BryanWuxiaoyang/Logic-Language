from __future__ import annotations

import argparse
import sys
from pathlib import Path


LATEX_NAME_TO_SYMBOL: dict[str, str] = {
    "ge": "≥",
    "le": "≤",
    "in": "∈",
    "notin": "∉",
    "included_in": "⊆",
    "subset": "⊂",
    "concat": "৹",
}


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite \\name function/operator aliases in a .lp file to symbol forms."
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
    reformatted = reformat_text(text)

    if args.output:
        Path(args.output).write_text(reformatted, encoding="utf-8")
    else:
        sys.stdout.write(reformatted)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
