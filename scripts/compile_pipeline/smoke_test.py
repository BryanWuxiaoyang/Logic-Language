#!/usr/bin/env python3
"""Smoke tests for the staged module_AST compiler."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compile_module import CompileError, run_compile_pipeline
from translate_AST_to_source import translate_ast_to_source


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


def target_bindings(ast: dict) -> list[dict]:
    return [node for node in ast.get("target_PSs", []) if node.get("kind") == "binding_stmt"]


def top_level_calls(ast: dict, name: str, field: str) -> list[dict]:
    return [node for node in ast.get(field, []) if node.get("kind") == "func_stmt" and node.get("call_sym", {}).get("name") == name]


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
    ast = compile_text("∀{| x, y | x = f(y) | y = y}")
    assert any(binding["dst_sym"]["name"] == "x" and binding["src_stmt"]["kind"] == "func_stmt" for binding in bindings(ast))


def test_target_call_assignment_normalized() -> None:
    ast = compile_text("∀{| x, y | y = f(x)}")
    assert not target_bindings(ast)
    assert any(binding["dst_sym"]["name"].startswith("__tmpf") for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_nested_call_anf() -> None:
    ast = compile_text("∀{| x | P(f(x))}")
    assert any(sym["name"].startswith("__tmpf") for sym in ast["bound_syms"])
    assert any(binding.get("generated") for binding in ast["premise_binding_stmts"])


def test_compound_lhs() -> None:
    ast = compile_text("∀{| a, b, x | (a, b) = f(x)}")
    assert not target_bindings(ast)
    target_eqs = top_level_calls(ast, "=", "target_PSs")
    assert len(target_eqs) == 2
    assert {stmt["arg_sym_list"][0]["name"] for stmt in target_eqs} == {"a", "b"}
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


def test_missing_infix_support_round_trip() -> None:
    cases = [
        ("∀{| x, y, z | z = (x + y)}", "+", "+"),
        ("∀{| x, y, z | z = x - y}", "-", "-"),
        ("∀{| x, y, z | z = x * y}", "*", "*"),
        ("∀{| x, y, z | z = x / y}", "/", "/"),
        ("∀{| x, y | x && y}", "&&", "&&"),
        ("∀{| x, y | x || y}", "||", "||"),
        ("∀{| x, S | x in S}", "in", "∈"),
        ("∀{| x, S | x notin S}", "notin", "∉"),
    ]
    for text, call_name, rendered in cases:
        ast = compile_text(text)
        assert calls(ast, call_name), (text, call_name)
        source = translate_ast_to_source(ast)
        assert rendered in source, (text, rendered, source)
        reparsed = compile_text(source)
        assert calls(reparsed, rendered if call_name in {"in", "notin"} else call_name), (text, source)


def test_operator_head_declaration_round_trip() -> None:
    text = "+: (list, list1) => list2\n        list2 = list"
    ast = compile_text(text)
    assert calls(ast, "+")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert calls(reparsed, "+")


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


def test_multiline_bar_semantics() -> None:
    ast = compile_text("∀{\n| x\n| x ~ x\nx = x\n}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["x"]
    assert top_level_calls(ast, "~", "premise_PSs")
    assert top_level_calls(ast, "=", "target_PSs")


def test_translate_omits_empty_binder_bar() -> None:
    ast = compile_text("val ~ min_val\n∀{| val1 | val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    lines = source.splitlines()
    assert "|" not in [line.strip() for line in lines]
    assert any(line.strip() == "val ~ min_val" for line in lines)
    assert not any(line.strip() == "| val ~ min_val" for line in lines)
    assert any(line.strip() == "| val1" for line in lines)
    assert any(line.strip() == "| sym ~ val1" for line in lines)
    assert any(line.strip() == "val1 ≥ min_val" for line in lines)


def test_translate_keeps_binder_line_when_present() -> None:
    ast = compile_text("∀{| x | x = x}")
    source = translate_ast_to_source(ast)
    assert "\n| x" in source


def test_target_literal_assignment_normalized() -> None:
    ast = compile_text("∀{| x | x = 1}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "value_literal_stmt" for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_target_module_assignment_normalized() -> None:
    ast = compile_text("∀{| x | x = ∀{| y | y = y}}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "quantified_stmt" for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_disassembled_final_ast_preserves_target_placement() -> None:
    ast = compile_text("val ~ min_val\n∀{| val1 | val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert not target_bindings(reparsed)
    assert any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["target_PSs"])
    assert not any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["premise_PSs"])


def test_round_trip_disassembly_is_idempotent() -> None:
    text = "val ~ min_val\n∀{| val1 | val1 ≥ min_val}"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert second_source == first_source
    assert first_source.count("| sym ~ val1") == 1
    assert first_source.count("| val1 ~ val1") == 1
    assert first_source.count("| val ~ val1") == 1


def main() -> int:
    tests = [
        test_simple_quantified,
        test_set_module,
        test_binding_call,
        test_target_call_assignment_normalized,
        test_nested_call_anf,
        test_compound_lhs,
        test_literals,
        test_member_and_operator,
        test_missing_infix_support_round_trip,
        test_operator_head_declaration_round_trip,
        test_import_file_locations,
        test_stdin_import_rejected,
        test_multiline_bar_semantics,
        test_translate_omits_empty_binder_bar,
        test_translate_keeps_binder_line_when_present,
        test_target_literal_assignment_normalized,
        test_target_module_assignment_normalized,
        test_disassembled_final_ast_preserves_target_placement,
        test_round_trip_disassembly_is_idempotent,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
