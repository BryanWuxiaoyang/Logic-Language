#!/usr/bin/env python3
"""Focused tests for check_final_AST.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_final_AST import FinalAstChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHECKER = SCRIPTS / "check_final_AST.py"


def loc(source: str = "<ast>", line: int = 1, column: int = 1, end_column: int = 2) -> dict:
    return {
        "file_path": source,
        "line": line,
        "column": column,
        "end_line": line,
        "end_column": end_column,
    }


def sym(name: str | None, **extra: object) -> dict:
    node = {"kind": "Sym", "source_loc": loc()}
    if name is not None:
        node["name"] = name
    node.update(extra)
    return node


def func(name: str, *args: dict) -> dict:
    return {
        "kind": "Func_stmt",
        "source_loc": loc(),
        "call_sym": sym(name),
        "arg_sym_list": list(args),
    }


def binding(dst: str = "y", src: dict | None = None) -> dict:
    return {
        "kind": "Binding_stmt",
        "source_loc": loc(),
        "dst_sym": sym(dst),
        "src_stmt": src or func("F", sym("x")),
    }


def value_literal(value: str = "1") -> dict:
    return {
        "kind": "Value_literal_stmt",
        "source_loc": loc(),
        "value": value,
    }


def module(bound_syms: list[dict], *, premise_bindings: list[dict] | None = None, premise_pss: list[dict] | None = None, target_pss: list[dict] | None = None) -> dict:
    return {
        "kind": "Quantified_stmt",
        "source_loc": loc(),
        "bound_syms": bound_syms,
        "premise_binding_stmts": premise_bindings or [],
        "premise_proposition_stmts": premise_pss or [],
        "target_proposition_stmts": target_pss or [func("=", sym("x"), sym("x"))],
        "quantifier_sym": sym("∀"),
    }


def codes(ast: dict) -> list[str]:
    return [entry["code"] for entry in FinalAstChecker().check(ast)]


def run_cli(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_valid_names() -> None:
    ast = module([sym("x"), sym("_x"), sym("列表"), sym("x'"), sym("x''"), sym("_x'''"), sym("列表'"), sym("field'"), sym("^x"), sym("^x'"), sym("^tmp0"), sym("^列表"), sym("__x"), sym("∀"), sym("≤"), sym("-"), sym("[:]")])
    assert FinalAstChecker().check(ast) == []


def test_invalid_names() -> None:
    ast = module([sym("1x"), sym("foo-bar"), sym(""), sym(None), sym("'"), sym("''"), sym("1x'"), sym("foo-bar'"), sym("x'y"), sym("x'_y"), sym("^"), sym("^^x"), sym("^1x"), sym("a^b"), sym("x^"), sym("^foo-bar")])
    diagnostics = FinalAstChecker().check(ast)
    assert [entry["code"] for entry in diagnostics] == [
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
        "invalid_bound_sym_name",
    ]


def test_same_statement_conflict() -> None:
    diagnostics = FinalAstChecker().check(module([sym("x"), sym("x")]))
    assert any(entry["code"] == "bound_sym_name_conflict" and "current statement" in entry["reason"] for entry in diagnostics)


def test_prime_suffix_conflict_semantics() -> None:
    assert FinalAstChecker().check(module([sym("x"), sym("x'")])) == []
    diagnostics = FinalAstChecker().check(module([sym("x'"), sym("x'")]))
    assert any(entry["code"] == "bound_sym_name_conflict" and "current statement" in entry["reason"] for entry in diagnostics)


def test_ancestor_conflict() -> None:
    child = module([sym("x")])
    parent = module([sym("x")], target_pss=[child])
    diagnostics = FinalAstChecker().check(parent)
    assert any(entry["code"] == "bound_sym_name_conflict" and "ancestor statement" in entry["reason"] for entry in diagnostics)


def test_sibling_non_conflict() -> None:
    sibling_a = module([sym("x")])
    sibling_b = module([sym("x")])
    parent = module([], target_pss=[sibling_a, sibling_b])
    assert FinalAstChecker().check(parent) == []


def test_nested_src_stmt_is_checked() -> None:
    inner = module([sym("x")])
    outer = module(
        [sym("x")],
        premise_bindings=[binding(src=inner)],
    )
    diagnostics = FinalAstChecker().check(outer)
    assert any(entry["code"] == "bound_sym_name_conflict" for entry in diagnostics)


def test_binding_stmt_in_premise_bindings_is_valid() -> None:
    assert FinalAstChecker().check(module([], premise_bindings=[binding()])) == []


def test_binding_stmt_in_premise_pss_is_invalid() -> None:
    diagnostics = FinalAstChecker().check(module([], premise_pss=[binding()]))
    assert any(
        entry["code"] == "invalid_binding_stmt_location"
        and entry["reason"] == "binding_stmt is only valid in premise_binding_stmts"
        for entry in diagnostics
    )


def test_binding_stmt_in_target_pss_is_invalid() -> None:
    diagnostics = FinalAstChecker().check(module([], target_pss=[binding()]))
    assert any(
        entry["code"] == "invalid_target_proposition_stmt"
        and entry["reason"] == "target_proposition_stmts must contain only proposition statements"
        for entry in diagnostics
    )


def test_target_sym_is_invalid() -> None:
    diagnostics = FinalAstChecker().check(module([], target_pss=[sym("x")]))
    assert any(entry["code"] == "invalid_target_proposition_stmt" for entry in diagnostics)


def test_target_literal_is_invalid() -> None:
    diagnostics = FinalAstChecker().check(module([], target_pss=[value_literal()]))
    assert any(entry["code"] == "invalid_target_proposition_stmt" for entry in diagnostics)


def test_target_func_stmt_and_quantified_stmt_are_valid() -> None:
    assert FinalAstChecker().check(module([], target_pss=[func("=", sym("x"), sym("x"))])) == []
    assert FinalAstChecker().check(module([], target_pss=[module([sym("x")])])) == []


def test_binding_stmt_as_root_is_invalid() -> None:
    diagnostics = FinalAstChecker().check(binding())
    assert any(entry["code"] == "invalid_binding_stmt_location" for entry in diagnostics)


def test_function_output_premise_rule_is_not_final_ast_check() -> None:
    ast = module(
        [sym("x"), sym("y")],
        premise_bindings=[binding("y", func("F", sym("x")))],
        premise_pss=[func("P", sym("y"))],
    )
    assert "function_output_in_premise" not in codes(ast)


def test_cli_stdin_and_file() -> None:
    payload = json.dumps(module([sym("x")]))
    stdin_result = run_cli(["--pretty"], stdin=payload)
    assert stdin_result.returncode == 0
    assert json.loads(stdin_result.stdout) == []

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ast.json"
        path.write_text(payload, encoding="utf-8")
        file_result = run_cli([str(path)])
        assert file_result.returncode == 0
        assert json.loads(file_result.stdout) == []


def test_cli_malformed_json_and_shape_fail() -> None:
    bad_json = run_cli([], stdin="{")
    assert bad_json.returncode == 1
    assert "invalid JSON" in bad_json.stderr

    bad_shape = run_cli([], stdin=json.dumps({"kind": "quantified_stmt"}))
    assert bad_shape.returncode == 1
    assert "legacy AST JSON kind" in bad_shape.stderr


def main() -> int:
    tests = [
        test_valid_names,
        test_invalid_names,
        test_same_statement_conflict,
        test_prime_suffix_conflict_semantics,
        test_ancestor_conflict,
        test_sibling_non_conflict,
        test_nested_src_stmt_is_checked,
        test_binding_stmt_in_premise_bindings_is_valid,
        test_binding_stmt_in_premise_pss_is_invalid,
        test_binding_stmt_in_target_pss_is_invalid,
        test_target_sym_is_invalid,
        test_target_literal_is_invalid,
        test_target_func_stmt_and_quantified_stmt_are_valid,
        test_binding_stmt_as_root_is_invalid,
        test_function_output_premise_rule_is_not_final_ast_check,
        test_cli_stdin_and_file,
        test_cli_malformed_json_and_shape_fail,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} check_final_AST tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
