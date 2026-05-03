#!/usr/bin/env python3
"""Smoke tests for the staged module_AST compiler."""

from __future__ import annotations

import importlib
import tempfile
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compile_module as compile_module_script
from compile_module import CompileError, run_compile_pipeline
from compile_pipeline.stage2_desugar_module_text import run as run_stage2
from semantic_check import collect_semantic_diagnostics_from_text
from translate_AST_to_source import translate_ast_to_source

SKILL_DIR = Path(__file__).resolve().parents[2]


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


def test_implicit_literal_classifier_predicates() -> None:
    cases = [
        ("∀{| x | x = 'a'}", "Char"),
        ('∀{| x | x = "ab"}', "String"),
        ("∀{| x | x = 1}", "Value"),
        ("∀{| x, a, b | x = (a, b)}", "Tuple"),
        ("∀{| x, a, b | x = {a, b}}", "Set"),
    ]
    for text, classifier in cases:
        ast = compile_text(text)
        premise_calls = top_level_calls(ast, "~", "premise_PSs")
        target_calls = top_level_calls(ast, "~", "target_PSs")
        all_classifier_calls = [stmt for stmt in calls(ast, "~") if stmt["arg_sym_list"][0]["name"] == classifier]
        assert all_classifier_calls, (text, classifier, calls(ast, "~"))
        if classifier == "String":
            assert any(stmt["arg_sym_list"][0]["name"] == "String" for stmt in target_calls), (text, target_calls)
            continue
        assert any(
            stmt["arg_sym_list"][0]["name"] == classifier and stmt["arg_sym_list"][1].get("generated")
            for stmt in target_calls
        ), (text, classifier, target_calls)
        assert not any(
            stmt["arg_sym_list"][0]["name"] == classifier and stmt["arg_sym_list"][1].get("generated")
            for stmt in premise_calls
        ), (text, classifier, premise_calls)


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
        ("∀{| a, b | Tuple ~ (a, b)}", "tuple_literal_stmt", "Tuple"),
        ("∀{| a, b | Set ~ {a, b}}", "set_literal_stmt", "Set"),
        ("∀{| a | Value ~ 1}", "value_literal_stmt", "Value"),
    ]
    for text, literal_kind, classifier in cases:
        ast = compile_text(text)
        assert any(binding["src_stmt"]["kind"] == literal_kind for binding in ast["premise_binding_stmts"]), (text, literal_kind)
        target_calls = top_level_calls(ast, "~", "target_PSs")
        assert len(target_calls) == 1, (text, target_calls)
        assert target_calls[0]["arg_sym_list"][0]["name"] == classifier, (text, classifier)
        assert target_calls[0]["arg_sym_list"][1]["generated"], text
        premise_calls = top_level_calls(ast, "~", "premise_PSs")
        assert not any(
            stmt["arg_sym_list"][0]["name"] == classifier and stmt["arg_sym_list"][1]["name"] == target_calls[0]["arg_sym_list"][1]["name"]
            for stmt in premise_calls
        ), text


def test_capital_wrapper_predicates_normalize_to_infix() -> None:
    cases = [
        ("∀{| a, b | Tuple~(a, b)}", "Tuple ~ (a, b)"),
        ("∀{| a, b | Set~{a, b}}", "Set ~ {a, b}"),
        ("∀{| a | Value~1}", "Value ~ 1"),
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
    assert "| list, list1, list2" in desugared
    assert "| list ~ list1" not in desugared
    assert "| Symbol ~ list" in desugared
    assert "| list ~ list" not in desugared
    assert "| List ~ list" not in desugared
    assert "tuple~(__list, __list1)" not in desugared
    assert "tuple ~ (list, list1)" not in desugared
    assert "__list1" not in desugared


def test_stage2_capital_inheritance_when_visible() -> None:
    desugared = run_stage2("$import standard_library.lp\n∀{| list1 | list1 = list1}", SKILL_DIR).text
    assert "| Symbol ~ list1" not in desugared
    assert "| List ~ list1" in desugared
    assert "| sym ~ list1" not in desugared
    assert "| list ~ list1" not in desugared


def test_stage2_function_output_inheritance_is_target() -> None:
    text = "List\n-: (list, list1) => list2\n        list2.size = (list.size + list1.size)"
    desugared = run_stage2(text, SKILL_DIR).text
    assert "\n    | List\n" in desugared
    assert "\n    | Symbol ~ List\n" not in desugared
    assert "\n    Symbol ~ List\n" in desugared
    assert "| List ~ list" in desugared
    assert "| List ~ list1" in desugared
    assert "| List ~ list2" not in desugared
    assert "\n        List ~ list2\n" in desugared


def test_stage2_does_not_inject_implicit_stdlib_import() -> None:
    desugared = run_stage2("∀{| x | x = x}", ".").text
    assert "$import standard_library.lp" not in desugared


def test_standard_library_supplies_universal_inheritance_axioms() -> None:
    stdlib = (SKILL_DIR / "standard_library.lp").read_text(encoding="utf-8")
    assert "__sym ~ __sym" in stdlib
    assert "Symbol ~ __sym" in stdlib


def test_stage2_generated_sym_does_not_re_desugar() -> None:
    source = "$import standard_library.lp\n∀{\n    | __list\n    | list ~ __list\n    | __list ~ __list\n    __list = __list\n}\n"
    desugared = run_stage2(source, SKILL_DIR).text
    assert desugared.startswith("$import standard_library.lp\n")
    assert "| Symbol ~ __list" not in desugared
    assert desugared.count("| list ~ __list") == 1
    assert desugared.count("| __list ~ __list") == 1


def test_stage2_authored_generated_sym_gets_no_implicit_facts() -> None:
    desugared = run_stage2("∀{| __x | __x = __x}", ".").text
    assert "| __x" in desugared
    assert "| Symbol ~ __x" not in desugared
    assert "| __x ~ __x" not in desugared


def test_stage2_synthesized_infixes_are_spaced() -> None:
    desugared = run_stage2("∀{| x | x = x}", ".").text
    assert "| Symbol ~ x" in desugared
    assert "| x ~ x" not in desugared
    assert "| Symbol~x" not in desugared
    assert "| x~x" not in desugared


def test_stage2_omits_symbol_when_inheritance_premise_exists() -> None:
    desugared = run_stage2("∀{| x | Value ~ x | x = x}", ".").text
    assert "| Value ~ x" in desugared
    assert "| Symbol ~ x" not in desugared


def test_stage2_legacy_unspaced_infix_still_compiles() -> None:
    ast = compile_text("∀{| x | Symbol~x}")
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


def test_nested_ancestor_conflict_is_invalid() -> None:
    desugared = run_stage2("∀{| x | ∀{| x | x = x}}", ".").text
    assert "| __x" not in desugared
    assert "| x ~ __x" not in desugared
    try:
        compile_text("∀{| x | ∀{| x | x = x}}")
    except CompileError as error:
        assert "bound_sym_name_conflict" in str(error)
    else:
        raise AssertionError("ancestor bound-sym conflict should fail final AST validation")


def test_semantic_warning_for_multiple_inheritance_candidates() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("Max_head_val\nHead_val\nVal\n∀{| max_head_val1 | max_head_val1 = max_head_val1}")
    assert any(
        entry["type"] == "warning"
        and entry["code"] == "implicit_inheritance_candidates"
        and "Max_head_val, Head_val, Val" in entry["reason"]
        and "selected Max_head_val" in entry["reason"]
        for entry in diagnostics
    )


def test_sibling_submodules_can_reuse_name() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| x | x = x}\n}"))
    assert source.count("\n    | x\n") == 2


def test_authored_generated_sym_is_accepted() -> None:
    ast = compile_text("∀{| __x | __x = __x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["__x"]


def test_translate_omits_empty_binder_bar() -> None:
    ast = compile_text("Val ~ min_val\n∀{| val1 | val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    lines = source.splitlines()
    assert "|" not in [line.strip() for line in lines]
    assert any(line.strip() == "Val ~ min_val" for line in lines)
    assert not any(line.strip() == "| Val ~ min_val" for line in lines)
    assert any(line.strip() == "| val1" for line in lines)
    assert any(line.strip() == "| Symbol ~ val1" for line in lines)
    assert any(line.strip() == "val1 ≥ min_val" for line in lines)


def test_translate_keeps_binder_line_when_present() -> None:
    ast = compile_text("∀{| x | x = x}")
    source = translate_ast_to_source(ast)
    assert "\n  | x" in source


def test_nested_module_disassembly_is_indented() -> None:
    ast = compile_text("-: (list, list1) => list2\n        list2.size = (list.size + list1.size)")
    source = translate_ast_to_source(ast)
    assert "\n  Function ~ -\n" in source
    assert "\n  ∀{\n" in source
    assert "\n    | list, list1, list2" in source
    assert "\n    | list2 = list - list1\n" in source
    assert "\n  }\n" in source


def test_function_output_inheritance_disassembles_as_target() -> None:
    text = "List\n-: (list, list1) => list2\n        list2.size = (list.size + list1.size)"
    first_source = translate_ast_to_source(compile_text(text, base_dir=SKILL_DIR))
    second_source = translate_ast_to_source(compile_text(first_source, base_dir=SKILL_DIR))
    assert "\n  | List\n" in first_source
    assert "\n  | Symbol ~ List\n" not in first_source
    assert "\n  Symbol ~ List\n" in first_source
    assert "\n    | List ~ list\n" in first_source
    assert "\n    | List ~ list1\n" in first_source
    assert "\n    | List ~ list2\n" not in first_source
    assert "\n    List ~ list2\n" in first_source
    assert second_source == first_source


def test_bound_syms_are_not_filtered_as_intrinsics() -> None:
    ast = compile_text("∀{| Symbol, Function, true, false | Symbol = Function}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["Symbol", "Function", "true", "false"]


def test_free_classifier_syms_are_not_auto_bound() -> None:
    ast = compile_text("∀{| x | Symbol ~ x | x = x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["x"]


def test_function_output_inheritance_cases() -> None:
    value_source = translate_ast_to_source(compile_text("Value\nF: value => out_value\n    out_value = out_value", base_dir=SKILL_DIR))
    assert "\n    | Value ~ value\n" in value_source
    assert "\n    Value ~ out_value\n" in value_source
    assert "\n    | Value ~ out_value\n" not in value_source

    symbol_source = translate_ast_to_source(compile_text("F: x => y\n    y = y", base_dir=SKILL_DIR))
    assert "\n    | Symbol ~ x\n" in symbol_source
    assert "\n    Symbol ~ y\n" in symbol_source

    generated_source = translate_ast_to_source(compile_text("F: __x => __y\n    __y = __y", base_dir=SKILL_DIR))
    assert "Symbol ~ __x" not in generated_source
    assert "Symbol ~ __y" not in generated_source

    bool_source = translate_ast_to_source(compile_text("Bool\nP: x => bool\n    P(x)", base_dir=SKILL_DIR))
    assert "\n    Bool ~ bool\n" in bool_source
    assert "\n    | Bool ~ bool\n" not in bool_source


def test_sibling_nested_modules_are_indented_consistently() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| y | y = y}\n}"))
    assert source.count("\n  ∀{\n") == 2
    assert "\n    | x\n" in source
    assert "\n    | y\n" in source


def test_target_literal_assignment_normalized() -> None:
    ast = compile_text("∀{| x | x = 1}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "value_literal_stmt" for binding in ast["premise_binding_stmts"])
    assert not any(stmt["arg_sym_list"][0]["name"] == "Value" for stmt in top_level_calls(ast, "~", "premise_PSs"))
    assert any(stmt["arg_sym_list"][0]["name"] == "Value" for stmt in top_level_calls(ast, "~", "target_PSs"))
    assert top_level_calls(ast, "=", "target_PSs")


def test_nested_literal_argument_adds_classifier_target() -> None:
    ast = compile_text("∀{| p, a, b | P((a, b))}")
    assert any(binding["src_stmt"]["kind"] == "tuple_literal_stmt" for binding in ast["premise_binding_stmts"])
    premise_calls = top_level_calls(ast, "~", "premise_PSs")
    target_calls = top_level_calls(ast, "~", "target_PSs")
    assert not any(stmt["arg_sym_list"][0]["name"] == "Tuple" and stmt["arg_sym_list"][1].get("generated") for stmt in premise_calls)
    assert any(stmt["arg_sym_list"][0]["name"] == "Tuple" and stmt["arg_sym_list"][1].get("generated") for stmt in target_calls)


def test_authored_premise_literal_classifier_keeps_premise_and_adds_target() -> None:
    ast = compile_text("∀{| x | Value ~ 1 | x = x}")
    premise_calls = [
        stmt for stmt in top_level_calls(ast, "~", "premise_PSs")
        if stmt["arg_sym_list"][0]["name"] == "Value" and stmt["arg_sym_list"][1].get("generated")
    ]
    target_calls = [
        stmt for stmt in top_level_calls(ast, "~", "target_PSs")
        if stmt["arg_sym_list"][0]["name"] == "Value" and stmt["arg_sym_list"][1].get("generated")
    ]
    assert len(premise_calls) == 1, premise_calls
    assert len(target_calls) == 1, target_calls
    assert premise_calls[0]["arg_sym_list"][1]["name"] == target_calls[0]["arg_sym_list"][1]["name"]


def test_authored_target_literal_classifier_dedupes_generated_target() -> None:
    source = translate_ast_to_source(compile_text("∀{| x | Value ~ 1}"))
    assert source.count("\n  Value ~ __tmp10\n") == 1, source


def test_target_module_assignment_normalized() -> None:
    ast = compile_text("∀{| x | x = ∀{| y | y = y}}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "quantified_stmt" for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_multiline_binding_rhs_disassembly_is_indented() -> None:
    text = "sym = {| __sym | __sym >= 0 => __sym + 1}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert "\n  | __tmpmodule03 = {\n    | __logic_language_out0\n" in first_source
    assert "\n    ∃{\n      | __sym, __tmp00, __tmp11, __tmpadd2\n" in first_source
    assert "\n      Value ~ __tmp00\n      Value ~ __tmp11\n      __logic_language_out0 = __tmpadd2\n" in first_source
    assert "\n    }\n  }\n  sym = __tmpmodule03\n" in first_source
    assert "\n}\n  sym = __tmpmodule03\n" not in first_source
    assert second_source == first_source


def test_disassembled_final_ast_preserves_target_placement() -> None:
    ast = compile_text("Val ~ min_val\n∀{| val1 | val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert not target_bindings(reparsed)
    assert any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["target_PSs"])
    assert not any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["premise_PSs"])


def test_round_trip_disassembly_is_idempotent() -> None:
    text = "Val ~ min_val\n∀{| val1 | val1 ≥ min_val}"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert second_source == first_source
    assert first_source.count("| Symbol ~ val1") == 1
    assert "| val1 ~ val1" not in first_source
    assert "| Val ~ val1" not in first_source


def test_generated_temp_round_trip_is_idempotent() -> None:
    text = "-: (list, list1) => list2\n        list2.size = (list.size + list1.size)"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert set(first_source.splitlines()) == set(second_source.splitlines())
    assert "| __tmpfunc_stmt0 ~ __tmpfunc_stmt0" not in second_source
    assert "| __tmpsize1 ~ __tmpsize1" not in second_source
    assert "| __tmpsize2 ~ __tmpsize2" not in second_source
    assert "| __tmpfunc_stmt3 ~ __tmpfunc_stmt3" not in second_source


def test_wrapper_round_trip_is_stable() -> None:
    text = "∀{| a, b | Tuple ~ (a, b)}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert second_source == first_source


def test_tuple_assignment_round_trip_adds_classifier_predicate() -> None:
    text = "x = (a, b)"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert "\n  Tuple ~ __tmpa_b0\n" in first_source
    assert "| Tuple ~ __tmpa_b0" not in first_source
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
    assert "stage: stage5_lower_to_module_ast" in result.stdout
    assert "final AST validation failed:" in result.stderr


def test_script_modules_import_without_cycles() -> None:
    modules = [
        "compile_module",
        "compile_pipeline.errors",
        "compile_pipeline.source_utils",
        "compile_pipeline.module_sections",
        "compile_pipeline.stage1_normalize_source",
        "compile_pipeline.stage2_desugar_module_text",
        "compile_pipeline.stage3_parse_module_sections",
        "compile_pipeline.stage4_parse_statements",
        "compile_pipeline.stage5_lower_to_module_ast",
        "syntax_check",
        "syntax_check_common",
        "semantic_check",
        "translate_AST_to_source",
        "validate_golden_tests",
    ]
    for module in modules:
        importlib.import_module(module)


def main() -> int:
    tests = [
        test_simple_quantified,
        test_set_module,
        test_binding_call,
        test_target_call_assignment_normalized,
        test_nested_call_anf,
        test_compound_lhs,
        test_literals,
        test_implicit_literal_classifier_predicates,
        test_member_and_operator,
        test_missing_infix_support_round_trip,
        test_operator_head_declaration_round_trip,
        test_wrapper_predicates_lower_through_anf,
        test_capital_wrapper_predicates_normalize_to_infix,
        test_stage2_ancestor_scope_for_function_decl,
        test_stage2_capital_inheritance_when_visible,
        test_stage2_function_output_inheritance_is_target,
        test_stage2_does_not_inject_implicit_stdlib_import,
        test_standard_library_supplies_universal_inheritance_axioms,
        test_stage2_generated_sym_does_not_re_desugar,
        test_stage2_authored_generated_sym_gets_no_implicit_facts,
        test_stage2_synthesized_infixes_are_spaced,
        test_stage2_omits_symbol_when_inheritance_premise_exists,
        test_stage2_legacy_unspaced_infix_still_compiles,
        test_import_file_locations,
        test_stdin_import_rejected,
        test_multiline_bar_semantics,
        test_duplicate_binders_deduplicate,
        test_nested_ancestor_conflict_is_invalid,
        test_semantic_warning_for_multiple_inheritance_candidates,
        test_sibling_submodules_can_reuse_name,
        test_authored_generated_sym_is_accepted,
        test_translate_omits_empty_binder_bar,
        test_translate_keeps_binder_line_when_present,
        test_nested_module_disassembly_is_indented,
        test_function_output_inheritance_disassembles_as_target,
        test_bound_syms_are_not_filtered_as_intrinsics,
        test_free_classifier_syms_are_not_auto_bound,
        test_function_output_inheritance_cases,
        test_sibling_nested_modules_are_indented_consistently,
        test_target_literal_assignment_normalized,
        test_nested_literal_argument_adds_classifier_target,
        test_authored_premise_literal_classifier_keeps_premise_and_adds_target,
        test_authored_target_literal_classifier_dedupes_generated_target,
        test_target_module_assignment_normalized,
        test_multiline_binding_rhs_disassembly_is_indented,
        test_disassembled_final_ast_preserves_target_placement,
        test_round_trip_disassembly_is_idempotent,
        test_generated_temp_round_trip_is_idempotent,
        test_wrapper_round_trip_is_stable,
        test_tuple_assignment_round_trip_adds_classifier_predicate,
        test_run_compile_pipeline_fails_on_final_ast_validation_invalid_name,
        test_run_compile_pipeline_fails_on_final_ast_validation_conflict,
        test_compile_module_cli_fails_without_ast_json_on_validation_error,
        test_compile_module_cli_debug_stages_prints_summaries_before_validation_error,
        test_script_modules_import_without_cycles,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
