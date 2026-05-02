#!/usr/bin/env python3
"""Smoke tests for the staged module_AST compiler."""

from __future__ import annotations

import tempfile
from pathlib import Path

from compile_module import CompileError, run_compile_pipeline


def compile_text(text: str, *, base_dir: Path | str = ".", source: str = "__stdin__", allow_imports: bool = False) -> dict:
    return run_compile_pipeline(text, base_dir, source=source, allow_imports=allow_imports).ast


def all_nodes(node: object) -> list[dict]:
    output: list[dict] = []
    if isinstance(node, dict):
        output.append(node)
        for value in node.values():
            output.extend(all_nodes(value))
    elif isinstance(node, list):
        for item in node:
            output.extend(all_nodes(item))
    return output


def calls(ast: dict, name: str) -> list[dict]:
    return [node for node in all_nodes(ast) if node.get("kind") == "func_stmt" and node.get("call_sym", {}).get("name") == name]


def bindings(ast: dict) -> list[dict]:
    return [node for node in all_nodes(ast) if node.get("kind") == "binding_stmt"]


def assert_no_legacy_top_level(ast: dict) -> None:
    assert "predicate_statements" not in ast
    assert "target_statements" not in ast
    assert "premise_PSs" in ast
    assert "target_PSs" in ast
    assert "loc" in ast


def test_simple_quantified() -> None:
    ast = compile_text("∀{| x | x = x}")
    assert ast["kind"] == "quantified_stmt"
    assert calls(ast, "=")
    assert_no_legacy_top_level(ast)


def test_set_module() -> None:
    ast = compile_text("{| x | x = x}")
    assert ast["kind"] == "set_stmt"
    assert calls(ast, "=")


def test_binding_call() -> None:
    ast = compile_text("∀{| x, y | x = f(y)}")
    assert any(binding["dst_sym"]["name"] == "x" and binding["src_stmt"]["kind"] == "func_stmt" for binding in bindings(ast))


def test_nested_call_anf() -> None:
    ast = compile_text("∀{| x | P(f(x))}")
    assert any(sym["name"].startswith("__tmpf") for sym in ast["bound_syms"])
    assert any(binding.get("generated") for binding in ast["premise_binding_stmts"])


def test_compound_lhs() -> None:
    ast = compile_text("∀{| a, b, x | (a, b) = f(x)}")
    assert any(binding["dst_sym"]["name"] == "a" for binding in ast["premise_binding_stmts"])
    assert any(binding["dst_sym"]["name"] == "b" for binding in ast["target_PSs"] if binding.get("kind") == "binding_stmt")
    assert calls(ast, "[]")


def test_literals() -> None:
    for text, kind in [
        ("∀{| x | x = 'a'}", "char_literal_stmt"),
        ("∀{| x | x = 1}", "value_literal_stmt"),
        ("∀{| x, a, b | x = (a, b)}", "tuple_literal_stmt"),
        ("∀{| x, a, b | x = {a, b}}", "set_literal_stmt"),
    ]:
        ast = compile_text(text)
        assert any(node.get("kind") == kind for node in all_nodes(ast)), (text, kind)


def test_member_and_operator() -> None:
    ast = compile_text("∀{| x | x.size = 1}")
    assert calls(ast, "size")
    assert calls(ast, "=")


def test_import_file_locations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        imported = root / "imported.lp"
        main = root / "main.lp"
        imported.write_text("∀{| x | x = x}\n", encoding="utf-8")
        main.write_text("$import imported.lp\n", encoding="utf-8")
        ast = compile_text(main.read_text(encoding="utf-8"), base_dir=root, source=str(main), allow_imports=True)
        assert ast["loc"]["source"] == str(imported.resolve())
        assert calls(ast, "=")


def test_stdin_import_rejected() -> None:
    try:
        compile_text("$import missing.lp")
    except CompileError:
        return
    raise AssertionError("stdin import should fail")


def main() -> int:
    tests = [
        test_simple_quantified,
        test_set_module,
        test_binding_call,
        test_nested_call_anf,
        test_compound_lhs,
        test_literals,
        test_member_and_operator,
        test_import_file_locations,
        test_stdin_import_rejected,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
