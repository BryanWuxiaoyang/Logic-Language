#!/usr/bin/env python3
"""Smoke tests for the staged module_AST compiler."""

from __future__ import annotations

import tempfile
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compile_module as compile_module_script
from compile_module import CompileError, run_compile_pipeline
from compile_pipeline.stage2_desugar_module_text import run as run_stage2
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
    ]
    for text, call_name, rendered in cases:
        ast = compile_text(text)
        assert calls(ast, call_name), (text, call_name)
        source = translate_ast_to_source(ast)
        assert rendered in source, (text, rendered, source)
        reparsed = compile_text(source)
        assert calls(reparsed, call_name), (text, source)


def test_operator_head_declaration_round_trip() -> None:
    text = "+: (list, list1) => list2\n        list2 = list"
    ast = compile_text(text)
    assert calls(ast, "+")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert calls(reparsed, "+")


def test_wrapper_predicates_lower_through_anf() -> None:
    cases = [
        ("∀{| a, b | tuple ~ (a, b)}", "tuple_literal_stmt", "tuple"),
        ("∀{| a, b | set ~ {a, b}}", "set_literal_stmt", "set"),
        ("∀{| a | value ~ 1}", "value_literal_stmt", "value"),
    ]
    for text, literal_kind, classifier in cases:
        ast = compile_text(text)
        assert any(binding["src_stmt"]["kind"] == literal_kind for binding in ast["premise_binding_stmts"]), (text, literal_kind)
        target_calls = top_level_calls(ast, "~", "target_PSs")
        assert len(target_calls) == 1, (text, target_calls)
        assert target_calls[0]["arg_sym_list"][0]["name"] == classifier, (text, classifier)
        assert target_calls[0]["arg_sym_list"][1]["generated"], text


def test_legacy_wrapper_predicates_normalize_to_infix() -> None:
    cases = [
        ("∀{| a, b | tuple~(a, b)}", "tuple ~ (a, b)"),
        ("∀{| a, b | set~{a, b}}", "set ~ {a, b}"),
        ("∀{| a | value~1}", "value ~ 1"),
    ]
    for text, rendered in cases:
        desugared = run_stage2(text, ".").text
        assert rendered in desugared, (text, desugared)
        assert "~" in rendered and rendered.replace(" ~ ", "~") not in desugared, (text, desugared)
        ast = compile_text(text)
        assert top_level_calls(ast, "~", "target_PSs"), text


def test_stage2_ancestor_scope_for_function_decl() -> None:
    text = "-: (list, list1) => list2\n        list2.size = (list.size + list1.size)"
    desugared = run_stage2(text, ".").text
    assert "| __list, list1, list2" in desugared
    assert "| list ~ list1" in desugared
    assert "| sym ~ __list" not in desugared
    assert "| list ~ __list" not in desugared
    assert "| __list ~ __list" not in desugared
    assert "tuple~(__list, __list1)" not in desugared
    assert "tuple ~ (__list, __list1)" not in desugared
    assert "__list1" not in desugared


def test_stage2_generated_sym_does_not_re_desugar() -> None:
    source = "$import standard_library.lp\n∀{\n    | __list\n    | list ~ __list\n    | __list ~ __list\n    __list = __list\n}\n"
    desugared = run_stage2(source, ".").text
    assert "| sym ~ __list" not in desugared
    assert desugared.count("| list ~ __list") == 1
    assert desugared.count("| __list ~ __list") == 1


def test_stage2_authored_generated_sym_gets_no_implicit_facts() -> None:
    desugared = run_stage2("∀{| __x | __x = __x}", ".").text
    assert "| __x" in desugared
    assert "| sym ~ __x" not in desugared
    assert "| __x ~ __x" not in desugared


def test_stage2_synthesized_infixes_are_spaced() -> None:
    desugared = run_stage2("∀{| x | x = x}", ".").text
    assert "| sym ~ x" in desugared
    assert "| x ~ x" in desugared
    assert "| sym~x" not in desugared
    assert "| x~x" not in desugared


def test_stage2_legacy_unspaced_infix_still_compiles() -> None:
    ast = compile_text("∀{| x | sym~x}")
    assert top_level_calls(ast, "~", "target_PSs")


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


def test_duplicate_binders_deduplicate() -> None:
    ast = compile_text("∀{| x, x | x = x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["x"]


def test_nested_ancestor_conflict_freshens() -> None:
    desugared = run_stage2("∀{| x | ∀{| x | x = x}}", ".").text
    assert "| __x" in desugared
    assert "| x ~ __x" not in desugared


def test_sibling_submodules_can_reuse_name() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| x | x = x}\n}"))
    assert source.count("\n    | x\n") == 2


def test_authored_generated_sym_is_accepted() -> None:
    ast = compile_text("∀{| __x | __x = __x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["__x"]


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
    assert "\n  | x" in source


def test_nested_module_disassembly_is_indented() -> None:
    ast = compile_text("-: (list, list1) => list2\n        list2.size = (list.size + list1.size)")
    source = translate_ast_to_source(ast)
    assert "\n  function ~ -\n" in source
    assert "\n  ∀{\n" in source
    assert "\n    | __list, list1, list2" in source
    assert "\n    | list2 = __list - list1\n" in source
    assert "\n  }\n" in source


def test_sibling_nested_modules_are_indented_consistently() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| y | y = y}\n}"))
    assert source.count("\n  ∀{\n") == 2
    assert "\n    | x\n" in source
    assert "\n    | y\n" in source


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


def test_generated_temp_round_trip_is_idempotent() -> None:
    text = "-: (list, list1) => list2\n        list2.size = (list.size + list1.size)"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert second_source == first_source
    assert "| __tmpfunc_stmt0 ~ __tmpfunc_stmt0" not in second_source
    assert "| __tmpsize1 ~ __tmpsize1" not in second_source
    assert "| __tmpsize2 ~ __tmpsize2" not in second_source
    assert "| __tmpfunc_stmt3 ~ __tmpfunc_stmt3" not in second_source


def test_wrapper_round_trip_is_stable() -> None:
    text = "∀{| a, b | tuple ~ (a, b)}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert second_source == first_source


def test_run_compile_pipeline_fails_on_final_ast_validation_invalid_name() -> None:
    original = compile_module_script.FinalAstChecker

    class FakeChecker:
        def check(self, ast: dict) -> list[dict[str, object]]:
            return [
                {
                    "file": "<ast>",
                    "lineno": 0,
                    "col_start_no": 0,
                    "col_end_no": 1,
                    "type": "error",
                    "code": "invalid_bound_sym_name",
                    "reason": "bound-sym name 'foo-bar' is invalid",
                }
            ]

    compile_module_script.FinalAstChecker = FakeChecker
    try:
        try:
            run_compile_pipeline("∀{| x | x = x}")
        except CompileError as error:
            message = str(error)
            assert "final AST validation failed:" in message
            assert "invalid_bound_sym_name" in message
            assert "foo-bar" in message
        else:
            raise AssertionError("run_compile_pipeline should fail on final AST validation")
    finally:
        compile_module_script.FinalAstChecker = original


def test_run_compile_pipeline_fails_on_final_ast_validation_conflict() -> None:
    original = compile_module_script.FinalAstChecker

    class FakeChecker:
        def check(self, ast: dict) -> list[dict[str, object]]:
            return [
                {
                    "file": "<ast>",
                    "lineno": 1,
                    "col_start_no": 2,
                    "col_end_no": 3,
                    "type": "error",
                    "code": "bound_sym_name_conflict",
                    "reason": "bound-sym name 'x' conflicts with ancestor statement",
                }
            ]

    compile_module_script.FinalAstChecker = FakeChecker
    try:
        try:
            run_compile_pipeline("∀{| x | x = x}")
        except CompileError as error:
            message = str(error)
            assert "bound_sym_name_conflict" in message
            assert "ancestor statement" in message
        else:
            raise AssertionError("run_compile_pipeline should fail on final AST validation")
    finally:
        compile_module_script.FinalAstChecker = original


def test_compile_module_cli_fails_without_ast_json_on_validation_error() -> None:
    code = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "skills/logic-language/scripts"))
import compile_module
class FakeChecker:
    def check(self, ast):
        return [{"file":"<ast>","lineno":0,"col_start_no":0,"col_end_no":1,"type":"error","code":"invalid_bound_sym_name","reason":"bad"}]
compile_module.FinalAstChecker = FakeChecker
sys.argv = ["compile_module.py", "--text", "∀{| x | x = x}"]
raise SystemExit(compile_module.main())
"""
    result = subprocess.run(
        ["python3", "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[4],
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "final AST validation failed:" in result.stderr
    assert "invalid_bound_sym_name" in result.stderr


def test_compile_module_cli_debug_stages_prints_summaries_before_validation_error() -> None:
    code = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "skills/logic-language/scripts"))
import compile_module
class FakeChecker:
    def check(self, ast):
        return [{"file":"<ast>","lineno":0,"col_start_no":0,"col_end_no":1,"type":"error","code":"invalid_bound_sym_name","reason":"bad"}]
compile_module.FinalAstChecker = FakeChecker
sys.argv = ["compile_module.py", "--debug-stages", "--text", "∀{| x | x = x}"]
raise SystemExit(compile_module.main())
"""
    result = subprocess.run(
        ["python3", "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[4],
        check=False,
    )
    assert result.returncode == 1
    assert "stage: stage1_normalize_source" in result.stdout
    assert "stage: stage6_emit_module_ast" in result.stdout
    assert "final AST validation failed:" in result.stderr


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
        test_wrapper_predicates_lower_through_anf,
        test_legacy_wrapper_predicates_normalize_to_infix,
        test_stage2_ancestor_scope_for_function_decl,
        test_stage2_generated_sym_does_not_re_desugar,
        test_stage2_authored_generated_sym_gets_no_implicit_facts,
        test_stage2_synthesized_infixes_are_spaced,
        test_stage2_legacy_unspaced_infix_still_compiles,
        test_import_file_locations,
        test_stdin_import_rejected,
        test_multiline_bar_semantics,
        test_duplicate_binders_deduplicate,
        test_nested_ancestor_conflict_freshens,
        test_sibling_submodules_can_reuse_name,
        test_authored_generated_sym_is_accepted,
        test_translate_omits_empty_binder_bar,
        test_translate_keeps_binder_line_when_present,
        test_nested_module_disassembly_is_indented,
        test_sibling_nested_modules_are_indented_consistently,
        test_target_literal_assignment_normalized,
        test_target_module_assignment_normalized,
        test_disassembled_final_ast_preserves_target_placement,
        test_round_trip_disassembly_is_idempotent,
        test_generated_temp_round_trip_is_idempotent,
        test_wrapper_round_trip_is_stable,
        test_run_compile_pipeline_fails_on_final_ast_validation_invalid_name,
        test_run_compile_pipeline_fails_on_final_ast_validation_conflict,
        test_compile_module_cli_fails_without_ast_json_on_validation_error,
        test_compile_module_cli_debug_stages_prints_summaries_before_validation_error,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
