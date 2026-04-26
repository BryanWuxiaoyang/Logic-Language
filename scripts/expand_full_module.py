from __future__ import annotations

import argparse
import sys

try:
    from expand_module import (
        ParserError,
        TokenizerError,
        expand_full_module_file,
    )
except ImportError:  # pragma: no cover - module execution fallback
    from .expand_module import (
        ParserError,
        TokenizerError,
        expand_full_module_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand a .lp module into full named-symbol and condition sections, "
            "including recursive imports."
        )
    )
    parser.add_argument("input_module", help="Path to input .lp module file.")
    parser.add_argument(
        "--output",
        help="Path to output expanded .lp file (default: <input>.full.expanded.lp).",
    )
    args = parser.parse_args(argv)

    try:
        out = expand_full_module_file(
            args.input_module,
            output_file=args.output,
        )
    except (OSError, ValueError, TokenizerError, ParserError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
