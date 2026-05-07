#!/usr/bin/env python3
"""Smoke tests for the staged module_AST compiler."""

from __future__ import annotations

import importlib
import json
import tempfile
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import compile_module as compile_module_script
import module_check
import normalize_module_declarations
import resolve_sym_type
from compile_module import CompileError, run_compile_pipeline
from compile_pipeline.source_utils import expand_imports
from compile_pipeline.stage1_normalize_source import run as run_stage1
from compile_pipeline.stage2_desugar_module_text import run as run_stage2
from semantic_check import collect_semantic_diagnostics_from_text
from translate_AST_to_source import translate_ast_to_source

SKILL_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = SKILL_DIR / "scripts"


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


def resolved_symbol(payload: dict, name: str) -> dict:
    for symbol in payload["symbols"]:
        if symbol["name"] == name:
            return symbol
    raise AssertionError(f"missing resolved symbol: {name}; payload={payload}")


def resolved_occurrences(payload: dict, name: str) -> list[dict]:
    return [entry for entry in payload["occurrences"] if entry["name"] == name]


def occurrence_on_line(payload: dict, name: str, lineno: int) -> dict:
    for entry in resolved_occurrences(payload, name):
        if entry["lineno"] == lineno:
            return entry
    raise AssertionError(f"missing resolved occurrence: {name} on line {lineno}; payload={payload}")


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
    assert any(binding["dst_sym"]["name"].startswith("^tmpf") for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_nested_call_anf() -> None:
    ast = compile_text("∀{| x | P(f(x))}")
    assert any(sym["name"].startswith("^tmpf") for sym in ast["bound_syms"])
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
        ("∀{| x | x = {}}", "set_literal_stmt"),
        ("∀{| x | x = [,]}", "tuple_literal_stmt"),
    ]:
        ast = compile_text(text)
        assert any(node.get("kind") == kind for node in all_nodes(ast)), (text, kind)
    assert any(node.get("kind") == "tuple_literal_stmt" and node.get("item_stmts") == [] for node in all_nodes(compile_text("x = [,]")))
    assert any(node.get("kind") == "set_literal_stmt" and node.get("item_stmts") == [] for node in all_nodes(compile_text("x = {}")))
    assert any(node.get("kind") == "sym" and node.get("name") == "[]" for node in all_nodes(compile_text("x = []")))
    for text in ["P({})", "P({1, 2})", "P([,])"]:
        compile_text(text)


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


def test_operator_symbol_can_be_inherited_as_value() -> None:
    ast = compile_text("Predicate ~ ∈")
    inherit_calls = top_level_calls(ast, "~", "target_PSs")
    assert any(
        stmt["arg_sym_list"][0]["name"] == "Predicate" and stmt["arg_sym_list"][1]["name"] == "∈"
        for stmt in inherit_calls
    )


def test_missing_infix_support_round_trip() -> None:
    cases = [
        ("∀{| x, y, z | z = (x + y)}", "+", "+"),
        ("∀{| x, y, z | z = x - y}", "-", "-"),
        ("∀{| x, y, z | z = x * y}", "*", "*"),
        ("∀{| x, y, z | z = x / y}", "/", "/"),
        ("∀{| x, y, z | z = x \\union y}", "∪", "∪"),
        ("∀{| x, y, z | z = x \\intersect y}", "∩", "∩"),
        ("∀{| x, y, z | z = x \\land y}", "∧", "∧"),
        ("∀{| x, y, z | z = x \\lor y}", "∨", "∨"),
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


def test_nested_equality_expressions() -> None:
    member_source = translate_ast_to_source(compile_text("∀{| bool, eq_stmt, sym1 | bool = eq_stmt.dst_sym = sym1}"))
    assert "^tmpdst_sym0 = dst_sym(^eq_stmt)" in member_source
    assert "^tmpeq1 = ^tmpdst_sym0 = ^sym1" in member_source
    assert "^bool = ^tmpeq1" in member_source

    grouped_ast = compile_text("∀{| bool, a, b, c, d | bool = (a = b) && (c = d)}")
    grouped_source = translate_ast_to_source(grouped_ast)
    assert "^tmpa_b0 = ^a = ^b" in grouped_source
    assert "^tmpc_d1 = ^c = ^d" in grouped_source
    assert top_level_calls(grouped_ast, "=", "target_PSs")

    precedence_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c, d | bool = a = b && c = d}"))
    assert "^tmpeq0 = ^a = ^b" in precedence_source
    assert "^tmpeq1 = ^c = ^d" in precedence_source
    assert "^tmpand2 = ^tmpeq0 && ^tmpeq1" in precedence_source


def test_chained_and_precedence_infix_expressions() -> None:
    union_source = translate_ast_to_source(compile_text("∀{| stmts, a, b, c | stmts = a \\union b \\union c}"))
    assert "^tmpunion0 = ∪(^a, ^b)" in union_source
    assert "^tmpunion1 = ∪(^tmpunion0, ^c)" in union_source
    assert "^stmts = ^tmpunion1" in union_source

    intersect_source = translate_ast_to_source(compile_text("∀{| x, a, b, c | x = a \\intersect b \\intersect c}"))
    assert "^tmpintersect0 = ∩(^a, ^b)" in intersect_source
    assert "^tmpintersect1 = ∩(^tmpintersect0, ^c)" in intersect_source

    arithmetic_source = translate_ast_to_source(compile_text("∀{| x, a, b, c | x = a + b * c}"))
    assert "^tmpmul0 = ^b * ^c" in arithmetic_source
    assert "^tmpadd1 = ^a + ^tmpmul0" in arithmetic_source

    arithmetic_source = translate_ast_to_source(compile_text("∀{| x, a, b, c | x = a * b + c}"))
    assert "^tmpmul0 = ^a * ^b" in arithmetic_source
    assert "^tmpadd1 = ^tmpmul0 + ^c" in arithmetic_source

    subtraction_source = translate_ast_to_source(compile_text("∀{| x, a, b, c | x = a - b - c}"))
    assert "^tmpsub0 = ^a - ^b" in subtraction_source
    assert "^tmpsub1 = ^tmpsub0 - ^c" in subtraction_source

    division_source = translate_ast_to_source(compile_text("∀{| x, a, b, c | x = a / b / c}"))
    assert "^tmpdiv0 = ^a / ^b" in division_source
    assert "^tmpdiv1 = ^tmpdiv0 / ^c" in division_source


def test_boolean_and_ordered_comparison_precedence() -> None:
    land_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c | bool = a \\land b \\lor c}"))
    assert "^tmpland0 = ∧(^a, ^b)" in land_source
    assert "^tmplor1 = ∨(^tmpland0, ^c)" in land_source

    ascii_bool_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c | bool = a && b || c}"))
    assert "^tmpand0 = ^a && ^b" in ascii_bool_source
    assert "^tmpor1 = ^tmpand0 || ^c" in ascii_bool_source

    less_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c | bool = a < b < c}"))
    assert "^tmpa_b0 = ^a < ^b" in less_source
    assert "^tmpb_c1 = ^b < ^c" in less_source
    assert "^tmpand2 = ^tmpa_b0 && ^tmpb_c1" in less_source

    mixed_less_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c | bool = a < b <= c}"))
    assert "^tmpa_b0 = ^a < ^b" in mixed_less_source
    assert "^tmpb_c1 = ^b ≤ ^c" in mixed_less_source
    assert "^tmpand2 = ^tmpa_b0 && ^tmpb_c1" in mixed_less_source

    equality_chain_source = translate_ast_to_source(compile_text("∀{| bool, a, b, c | bool = a = b = c}"))
    assert "^tmpeq0 = ^a = ^b" in equality_chain_source
    assert "^tmpeq1 = ^tmpeq0 = ^c" in equality_chain_source
    assert "^tmpand" not in equality_chain_source


def test_prefix_unary_expressions() -> None:
    not_quant_source = translate_ast_to_source(compile_text("∀{| bool | bool = !∀{| x | P(x)}}"))
    assert "^tmpmodule00 = ∀{" in not_quant_source
    assert "^tmpnot1 = !(^tmpmodule00)" in not_quant_source

    for text in [
        "∀{| bool, x | bool = !P(x)}",
        "∀{| bool, x | bool = ! P(x)}",
        "∀{| bool, x | bool = \\lnot P(x)}",
    ]:
        ast = compile_text(text)
        source = translate_ast_to_source(ast)
        assert "^tmpP0 = P(^x)" in source
        assert "^tmpnot1 = !(^tmpP0)" in source
        assert not calls(ast, "!P")

    unary_left_source = translate_ast_to_source(compile_text("∀{| x, a, b | x = -a * b}"))
    assert "^tmpsub0 = -(^a)" in unary_left_source
    assert "^tmpmul1 = ^tmpsub0 * ^b" in unary_left_source

    unary_right_source = translate_ast_to_source(compile_text("∀{| x, a, b | x = a * -b}"))
    assert "^tmpsub0 = -(^b)" in unary_right_source
    assert "^tmpmul1 = ^a * ^tmpsub0" in unary_right_source

    for text in ["∀{| x, set | x = *set}", "∀{| x, set | x = * set}"]:
        assert "^tmpmul0 = *(^set)" in translate_ast_to_source(compile_text(text))

    regressions_source = translate_ast_to_source(compile_text("∀{| bool, x, y, a, b | bool = a != b, x = a - b, y = a * b}"))
    assert "^tmpneq0 = ^a ≠ ^b" in regressions_source
    assert "^tmpsub1 = ^a - ^b" in regressions_source
    assert "^tmpmul2 = ^a * ^b" in regressions_source

    bare_source = translate_ast_to_source(compile_text("∀{| x, y, z | x = !, y = -, z = *}"))
    assert "^x = !" in bare_source
    assert "^y = -" in bare_source
    assert "^z = *" in bare_source


def test_lifted_resolver_equality_expression_compiles() -> None:
    text = """Stmt
Stmt::has_direct_sym_alias: (stmt, sym1, sym2) => bool
    bool = ∃{
        | eq_stmt
        | eq_stmt ∈ stmt.all_stmts
        | Eq_stmt ~ eq_stmt
        (eq_stmt.dst_sym = sym1 && eq_stmt.src_sym = sym2) || (eq_stmt.src_sym = sym1 && eq_stmt.dst_sym = sym2)
    }"""
    ast = compile_text(text)
    assert calls(ast, "=")
    assert calls(ast, "&&")
    assert calls(ast, "||")


def test_operator_head_declaration_round_trip() -> None:
    text = "+: (list, list1) => list2\n    list2 = list"
    ast = compile_text(text)
    assert calls(ast, "+")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert calls(reparsed, "+")


def test_slice_operator_identifier_sym_compiles_everywhere() -> None:
    ast = compile_text("∀{| [:] | [:] = [:]}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["[:]"]
    assert calls(ast, "=")
    assert compile_text("Function ~ [:]")
    ast = compile_text("∀{| [] | [] = x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["[]"]
    assert compile_text("Function ~ []")


def test_slice_operator_declaration_and_call_compile() -> None:
    ast = compile_text("[:]: (val1, val2) => list\n    list = [:](val1, val2)")
    assert calls(ast, "[:]")
    assert any(
        stmt["call_sym"]["name"] == "~" and stmt["arg_sym_list"][1]["name"] == "[:]"
        for stmt in ast["target_PSs"]
    )


def test_range_and_slice_surface_forms_lower_to_slice_operator() -> None:
    ast = compile_text("x = [1: n]\ny = list[1: list.size]")
    slice_calls = calls(ast, "[:]")
    assert len(slice_calls) == 2
    assert any(len(call["arg_sym_list"]) == 2 for call in slice_calls)
    assert any(len(call["arg_sym_list"]) == 3 for call in slice_calls)


def test_compound_slice_member_call_lowers_to_ordinary_call() -> None:
    ast = compile_text("z = list[1: list.size].sum(merge_f)")
    assert calls(ast, "[:]")
    assert calls(ast, "sum")
    assert not calls(ast, "listsum")


def test_class_coloncolon_top_level_function_declaration() -> None:
    source = translate_ast_to_source(compile_text("Val\nClass\nClass::func: (val1, val2) => (val3, val4)"))
    assert "Class::func" not in source
    assert "Function ~ func" in source
    assert "func(^val1, ^val2)" in source
    assert "| Val ~ ^val1" in source
    assert "| Val ~ ^val2" in source
    assert "\n    Tuple ~ ^tmpfunc0\n" in source
    assert "\n    | Tuple ~ ^tmpfunc0\n" not in source
    assert "\n    Val ~ ^val3\n" in source
    assert "\n    Val ~ ^val4\n" in source


def test_class_block_expands_to_current_scope() -> None:
    source = translate_ast_to_source(compile_text("Class\n    ::field\n    ::func: (val1, val2) => (val3, val4)"))
    assert "Class::" not in source
    assert "\n  | ^Class\n" not in source
    assert "Function ~ field" in source
    assert "field(^_class)" in source
    assert "| Class ~ ^_class" in source
    assert "Symbol ~ ^_field" in source
    assert "Function ~ func" in source
    assert "func(^val1, ^val2)" in source


def test_class_field_shorthand_compiles() -> None:
    source = translate_ast_to_source(compile_text("Class\nClass::field"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "field(^_class)" in source
    assert "Class ~ ^_class" in source
    assert "Symbol ~ ^_field" in source
    assert "^_field = field(^_class)" in source


def test_class_field_assignment_sugar_compiles() -> None:
    source = translate_ast_to_source(compile_text("Value\nField\nClass\nValue ~ value\nClass::field = value"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "^_field = field(^_class)" in source
    assert "Class ~ ^_class" in source
    assert "field(^_class)" in source
    assert " = value" in source


def test_class_field_assignment_sugar_compiles_in_class_body() -> None:
    source = translate_ast_to_source(compile_text("Value\nField\nClass\nValue ~ value\nClass\n    ::field = value"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "^_field = field(^_class)" in source
    assert "Class ~ ^_class" in source
    assert "field(^_class)" in source


def test_class_field_assignment_sugar_allows_expression_rhs() -> None:
    source = translate_ast_to_source(compile_text("Value\nField\nClass\nValue ~ value\nF: value => value'\nClass::field = F(value)"))
    assert "F(value)" in source
    assert "field(^_class)" in source


def test_class_field_assignment_sugar_desugars_in_premise_section() -> None:
    source = translate_ast_to_source(compile_text("Value\nField\nClass\nValue ~ value\n| Class::field = value\nP(value)"))
    assert "| Function ~ ^field" in source
    assert "| ∀{" in source
    assert "^field(^_class)" in source
    assert "P(^value)" in source


def test_class_field_shorthand_uses_underscore_receiver_and_output_names() -> None:
    source = translate_ast_to_source(compile_text("Class\n| field'\nClass::field"))
    assert "| ^_class, ^_field" in source
    assert "Symbol ~ ^_field" in source
    assert "^_field = field(^_class)" in source

    source = translate_ast_to_source(compile_text("Class\n| field'\n| field''\nClass::field"))
    assert "| ^_class, ^_field" in source
    assert "Symbol ~ ^_field" in source
    assert "^_field = field(^_class)" in source


def test_class_field_shorthand_desugars_in_premise_section() -> None:
    source = translate_ast_to_source(compile_text("Graph\nGraph~A\nA\n    ::field\nB\nB~b\n"))
    assert "Function ~ field" in source
    assert "field(^_a)" in source
    assert "A ~ ^_a" in source
    assert "Symbol ~ ^_field" in source

def test_prime_suffix_names_compile_and_infer_from_base() -> None:
    source = translate_ast_to_source(compile_text("List\n∀{| list', x'', y | y = list'}"))
    assert "\n    | ^list', ^x'', ^y\n" in source
    assert "| List ~ ^list'" in source
    assert "invalid_bound_sym_name" not in source
    assert "^y = ^list'" in source


def test_class_method_body_is_preserved() -> None:
    source = translate_ast_to_source(compile_text("Class\n    ::func: x => y\n        y = x"))
    assert "Class::func" not in source
    assert "Function ~ func" in source
    assert "\n    | ^y = func(^x)\n" in source
    assert "\n    ^y = ^x\n" in source


def test_function_declaration_and_body_are_separate_rules() -> None:
    text = "Val\nClass\nClass::func: (val1, val2) => (val3, val4)\n    | val1 = val2\n    P(val3)"
    desugared = run_stage2(text, SKILL_DIR).text
    assert desugared.count("∀{") == 3
    assert desugared.count("Val ~ val3") == 1
    assert desugared.count("Val ~ val4") == 1
    assert "| (val3, val4) = func(val1, val2)" in desugared
    assert "| val1 = val2" in desugared
    assert "P(val3)" in desugared

    declaration_index = desugared.index("Val ~ val3")
    body_index = desugared.index("| val1 = val2")
    assert declaration_index < body_index


def test_repeated_function_bodies_are_conditional_facts() -> None:
    text = "F: input => output\n    | input = 1\n    P(output)\n\nF: input => output\n    | input = 2\n    Q(output)"
    source = translate_ast_to_source(compile_text(text, base_dir=SKILL_DIR))
    assert source.count("| ^input = 1") == 1
    assert source.count("| ^input = 2") == 1
    assert source.count("P(^output)") == 1
    assert source.count("Q(^output)") == 1
    assert source.count("Symbol ~ ^output") == 2


def test_function_arrow_shorthand_is_invalid() -> None:
    try:
        compile_text("f: x -> g(x)", base_dir=SKILL_DIR)
    except CompileError as error:
        assert "function-assign '->' is not supported" in str(error)
        return
    raise AssertionError("expected function-assign shorthand to fail")


def test_inheritance_fact_does_not_declare_class_body() -> None:
    try:
        compile_text("A ~ B\n    ::func: b => out")
    except CompileError as error:
        assert (
            "class-declaration body line must start with '::'" in str(error)
            or "unsupported '::' usage" in str(error)
            or "indentation body is only allowed after quantifier, branch, declaration, or class declaration" in str(error)
        )
        return
    raise AssertionError("A ~ B with an indented :: body should require an explicit B declaration")


def test_explicit_class_declaration_after_inheritance_fact() -> None:
    source = translate_ast_to_source(compile_text("B\n    ::func: b => out\nA ~ B"))
    assert "\n  | ^B\n" not in source
    assert "\n  A ~ B\n" in source
    assert "Function ~ func" in source
    assert "\n    | B ~ ^b\n" in source


def test_class_operator_suffix_declaration() -> None:
    source = translate_ast_to_source(compile_text("List\nList::[]: (list, id) => sym"))
    assert "List::[]" not in source
    assert "Function ~ []" in source
    assert "^list[^id]" in source


def test_class_coloncolon_requires_explicit_owner_declaration() -> None:
    for text in ["Class::func: _class => out", "A ~ Class\nClass::func: _class => out", "Class::field"]:
        try:
            compile_text(text)
        except CompileError as error:
            assert "class member declaration requires explicit class declaration: Class" in str(error)
        else:
            raise AssertionError(f"expected undeclared class member owner to fail: {text!r}")

        payload = module_check.check_module(text, "<stdin>", SKILL_DIR, is_file=False)
        assert payload["summary"]["error_count"] == 1, text
        assert payload["entries"][0]["code"] == "undeclared_class_member_owner", text

    for text in ["Class\nOut\nClass::func: _class => _out", "Class\nField\nClass::field", "Class::func: _class => _out\nClass\nOut"]:
        payload = module_check.check_module(text, "<stdin>", SKILL_DIR, is_file=False)
        assert payload["summary"]["error_count"] == 0, text
        assert payload["summary"]["warning_count"] == 0, text


def test_bare_plain_symbol_targets_are_invalid_class_declarations() -> None:
    payload = module_check.check_module("Class\nsym", "<stdin>", SKILL_DIR, is_file=False)
    assert payload["summary"]["error_count"] == 1
    assert payload["summary"]["warning_count"] == 0
    assert payload["entries"][0]["code"] == "invalid_class_declaration_name"


def test_invalid_class_body_lines_fail() -> None:
    cases = [
        "Class\n    P(class)",
        "Class\n    : (class, x) => y",
        "Class::field = value",
        "Class::field\n    P(field)",
        "Class\n    ::field\n        P(field)",
    ]
    for text in cases:
        try:
            compile_text(text)
        except CompileError:
            continue
        raise AssertionError(f"expected invalid class-declaration source to fail: {text!r}")


def test_explicit_class_field_declaration_may_have_body() -> None:
    source = translate_ast_to_source(compile_text("Class\nClass::field: class => field'\n    P(field')"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "\n    P(^field')\n" in source


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
    text = "-: (list, list1) => list2\n    list2.size = (list.size + list1.size)"
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


def test_stage2_class_suffix_fallback_inheritance() -> None:
    desugared = run_stage2("Chip_mem\nF: _chip_mem_class => _out", ".").text
    assert "| Chip_mem ~ _chip_mem_class" in desugared
    assert "| Symbol ~ _chip_mem_class" not in desugared

    primary_desugared = run_stage2("Chip_mem_class\nChip_mem\nF: _chip_mem_class => _out", ".").text
    assert "| Chip_mem_class ~ _chip_mem_class" in primary_desugared
    assert "| Chip_mem ~ _chip_mem_class" not in primary_desugared

    numeric_desugared = run_stage2("Chip_mem\nF: _chip_mem_class1 => _out", ".").text
    assert "| Chip_mem ~ _chip_mem_class1" in numeric_desugared
    assert "| Symbol ~ _chip_mem_class1" not in numeric_desugared

    diagnostics = collect_semantic_diagnostics_from_text("F: _chip_mem_class => _out")
    assert any(entry["code"] == "implicit_inheritance_fallback_symbol" for entry in diagnostics)


def test_stage2_function_output_inheritance_is_target() -> None:
    text = "List\n-: (list, list1) => list2\n    list2.size = (list.size + list1.size)"
    desugared = run_stage2(text, SKILL_DIR).text
    assert "\n    | List\n" not in desugared
    assert "\n    | Symbol ~ List\n" not in desugared
    assert "\n    Symbol ~ List\n" not in desugared
    assert "| List ~ list" in desugared
    assert "| List ~ list1" in desugared
    assert "| List ~ list2" not in desugared
    assert "\n        List ~ list2\n" in desugared


def test_stage2_does_not_inject_implicit_stdlib_import() -> None:
    desugared = run_stage2("∀{| x | x = x}", ".").text
    assert "$import standard_library.lp" not in desugared


def test_standard_library_supplies_universal_inheritance_axioms() -> None:
    stdlib = (SKILL_DIR / "standard_library.lp").read_text(encoding="utf-8")
    assert "^sym ~ ^sym" in stdlib
    assert "Symbol ~ ^sym" in stdlib


def test_stage2_generated_sym_does_not_re_desugar() -> None:
    source = "$import standard_library.lp\n∀{\n    | ^list\n    | list ~ ^list\n    | ^list ~ ^list\n    ^list = ^list\n}\n"
    desugared = run_stage2(source, SKILL_DIR).text
    assert desugared.startswith("$import standard_library.lp\n")
    assert "| Symbol ~ ^list" not in desugared
    assert desugared.count("| list ~ ^list") == 1
    assert desugared.count("| ^list ~ ^list") == 1


def test_stage2_authored_generated_sym_gets_no_implicit_facts() -> None:
    desugared = run_stage2("∀{| ^x | ^x = ^x}", ".").text
    assert "| ^x" in desugared
    assert "| Symbol ~ ^x" not in desugared
    assert "| ^x ~ ^x" not in desugared


def test_double_underscore_sym_is_ordinary() -> None:
    desugared = run_stage2("∀{| __x | __x = __x}", ".").text
    assert "| Symbol ~ __x" in desugared


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


def test_import_searches_skill_dir_for_standard_library() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        normalized = run_stage1(
            "$import standard_library.lp\n∀{| x | x = x}",
            base_dir=root,
            source=str(root / "main.lp"),
            allow_imports=True,
        )
        assert normalized.import_count == 1
        assert "Symbol" in normalized.text
        assert "∀{| x | x = x}" in normalized.text


def test_stage1_dedupes_transitive_imports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared.lp").write_text("Shared\n", encoding="utf-8")
        (root / "a.lp").write_text("$import shared.lp\nA\n", encoding="utf-8")
        (root / "b.lp").write_text("$import shared.lp\nB\n", encoding="utf-8")
        source = "$import a.lp\n$import b.lp\nMain\n"
        normalized = run_stage1(source, base_dir=root, source=str(root / "main.lp"), allow_imports=True)

    assert normalized.import_count == 3
    assert normalized.text.splitlines() == ["Shared", "A", "B", "Main"]


def test_stage1_dedupes_direct_and_resolved_alias_imports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        nested = root / "nested"
        nested.mkdir()
        shared = nested / "shared.lp"
        shared.write_text("Shared\n", encoding="utf-8")
        source = "$import nested/shared.lp\n$import nested/../nested/shared.lp\n$import nested/shared.lp\n"
        normalized = run_stage1(source, base_dir=root, source=str(root / "main.lp"), allow_imports=True)

    assert normalized.import_count == 1
    assert normalized.text == "Shared"


def test_source_utils_expand_imports_dedupes_visible_context_imports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared.lp").write_text("Shared\n", encoding="utf-8")
        (root / "a.lp").write_text("$import shared.lp\nA\n", encoding="utf-8")
        (root / "b.lp").write_text("$import shared.lp\nB\n", encoding="utf-8")
        expanded = expand_imports("$import a.lp\n$import b.lp", root)

    assert expanded.splitlines() == ["Shared", "A", "B"]


def test_import_cycle_still_errors_with_dedup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.lp").write_text("$import b.lp\nA\n", encoding="utf-8")
        (root / "b.lp").write_text("$import a.lp\nB\n", encoding="utf-8")
        try:
            run_stage1("$import a.lp\n", base_dir=root, source=str(root / "main.lp"), allow_imports=True)
        except CompileError as error:
            assert "cyclic import" in str(error)
            return
    raise AssertionError("cyclic import should fail")


def test_module_check_dedupes_located_imports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = root / "bad.lp"
        bad.write_text("Class\n    ::field = x\n        P(x)\n", encoding="utf-8")
        payload = module_check.check_module(
            "$import bad.lp\n$import bad.lp\n",
            str(root / "main.lp"),
            root,
            is_file=False,
        )

    assert payload["summary"]["error_count"] == 1
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["file"] == str(bad.resolve())


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


def test_branch_header_lowers_to_target_module() -> None:
    source = "| x\n|- P(x)\n    y = x\nz = z"
    desugared = run_stage2(source, ".").text
    assert "| - P(x)" not in desugared
    ast = compile_text(source)
    branch_modules = [node for node in ast["target_PSs"] if node.get("kind") == "quantified_stmt"]
    assert len(branch_modules) == 1
    branch = branch_modules[0]
    assert not branch["bound_syms"]
    assert top_level_calls(branch, "P", "premise_PSs")
    assert top_level_calls(branch, "=", "target_PSs")
    assert top_level_calls(ast, "=", "target_PSs")
    assert not any(node.get("name") == "__compiler_branch_module" for node in all_nodes(ast))


def test_sibling_branches_are_target_modules() -> None:
    ast = compile_text("| x\n|- P(x)\n    y = x\n|- Q(x)\n    y = x\nz = z")
    branch_modules = [node for node in ast["target_PSs"] if node.get("kind") == "quantified_stmt"]
    assert len(branch_modules) == 2
    assert top_level_calls(branch_modules[0], "P", "premise_PSs")
    assert top_level_calls(branch_modules[1], "Q", "premise_PSs")
    assert top_level_calls(ast, "=", "target_PSs")


def test_premise_universal_block_contains_target_branch_modules() -> None:
    source = "| x\n| \\all\n    |- P(x)\n        y = x\nz = z"
    expanded = translate_ast_to_source(compile_text(source))
    assert "^∀" not in expanded
    premise_modules = [node for node in compile_text(source)["premise_PSs"] if node.get("kind") == "quantified_stmt"]
    assert len(premise_modules) == 1
    branch_modules = [node for node in premise_modules[0]["target_PSs"] if node.get("kind") == "quantified_stmt"]
    assert len(branch_modules) == 1
    assert top_level_calls(branch_modules[0], "P", "premise_PSs")


def test_branch_requires_indented_block() -> None:
    payload = module_check.check_module("| x\n|- P(x)\nz = z", module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["code"] == "syntax_error"
    assert entry["reason"] == "branch header requires an indented block"


def test_branch_allows_function_output_in_nested_target() -> None:
    payload = module_check.check_module("F: x => y\n    |- P(x)\n        y = 1", module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 0
    assert not any(entry["code"] == "function_output_in_premise" for entry in payload["entries"])


def test_indentation_body_headers_are_validated() -> None:
    valid_sources = [
        "∀\n    | x\n    P(x)",
        "∃\n    | x\n    P(x)",
        "@\n    | x\n    P(x)",
        "| x\n| ∀\n    P(x)\nz = z",
        "| x\n| ∃\n    | y\n    P(y)\nz = z",
        "| x\n|- P(x)\n    Q(x)\nz = z",
        "F: x => y\n    y = x",
        "F: x => y\n    | G: a => b\n        b = a\n    y = G(x)",
        "Class\n    ::field\n    ::func: _class => _out\n        P(_out)",
        "Class\nClass::func: _class => _out\n    P(_out)",
    ]
    for source in valid_sources:
        payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 0, (source, payload)


def test_at_header_desugars_to_recursive_forall_block() -> None:
    sources = [
        "\n".join(
            [
                "@Malu_wmma_instr::matrix1/matrix2",
                "    Malu_wmma_instr",
                "        ::m_size",
                "        ::matrix1: _malu_wmma_instr => _matrix",
                "            P(_matrix)",
            ]
        ),
        "\n".join(
            [
                "@note",
                "    F: _x => _y",
                "        _y = _x",
                "    f = f",
            ]
        ),
    ]
    for source in sources:
        payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 0, (source, payload)


def test_indentation_body_rejects_invalid_owner_and_level_jump() -> None:
    invalid_owner = module_check.check_module("P(x)\n    Q(x)", module_check.STDIN_FILE, Path("."), is_file=False)
    assert invalid_owner["summary"]["error_count"] == 1
    owner_entry = invalid_owner["entries"][0]
    assert owner_entry["stage"] == "syntax"
    assert owner_entry["reason"] == "indentation body is only allowed after quantifier, branch, declaration, or class declaration"
    assert owner_entry["lineno"] == 0
    assert owner_entry["col_start_no"] == 0

    level_jump = module_check.check_module("∀\n        | x\n    P(x)", module_check.STDIN_FILE, Path("."), is_file=False)
    assert level_jump["summary"]["error_count"] == 1
    jump_entry = level_jump["entries"][0]
    assert jump_entry["stage"] == "syntax"
    assert jump_entry["reason"] == "indentation can only increase by one level"
    assert jump_entry["lineno"] == 1
    assert jump_entry["col_start_no"] == 8

    try:
        compile_text("P(x)\n    Q(x)")
    except CompileError as error:
        assert "indentation body is only allowed after quantifier, branch, declaration, or class declaration" in str(error)
    else:
        raise AssertionError("expected compiler to reject arbitrary indentation body owner")

    try:
        compile_text("∀\n        | x\n    P(x)")
    except CompileError as error:
        assert "indentation can only increase by one level" in str(error)
    else:
        raise AssertionError("expected compiler to reject skipped indentation level")


def test_target_nested_declaration_expands_in_function_body() -> None:
    source = translate_ast_to_source(compile_text("F: x => y\n    G: a => b\n        P(b)\n    y = G(x)", base_dir=SKILL_DIR))
    assert "\n    Function ~ G\n" in source
    assert "\n      | ^b = G(^a)\n" in source
    assert "\n      P(^b)\n" in source
    assert "unsupported expression: |" not in source


def test_premise_nested_declaration_expands_in_function_body() -> None:
    source = translate_ast_to_source(compile_text("F: func => y\n    | func: a => b\n        P(b)\n    P(func)", base_dir=SKILL_DIR))
    assert "\n    | Function ~ ^func\n" in source
    assert "\n    | ∀{\n" in source
    assert "\n      | ^b = ^func(^a)\n" in source
    assert "\n      P(^b)\n" in source
    assert "Function ~ | func" not in source


def test_no_body_premise_declaration_expands_signature() -> None:
    source = translate_ast_to_source(compile_text("F: x => y\n    | f: a => b\n    y = x", base_dir=SKILL_DIR))
    assert "\n    | Function ~ ^f\n" in source
    assert "\n      | ^b = ^f(^a)\n" in source


def test_bool_declarations_emit_predicate_fact() -> None:
    source = translate_ast_to_source(compile_text("P: x => bool\n    P(x)", base_dir=SKILL_DIR))
    assert "\n  Predicate ~ P\n" in source
    assert "\n  Function ~ P\n" not in source

    premise_source = translate_ast_to_source(compile_text("F: x => y\n    | P: a => bool\n    y = x", base_dir=SKILL_DIR))
    assert "\n    | Predicate ~ ^P\n" in premise_source
    assert "\n    | Function ~ ^P\n" not in premise_source


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


def test_semantic_suppresses_multiple_inheritance_candidates_warning() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("Max_head_val\nHead_val\nVal\n∀{| max_head_val1 | max_head_val1 = max_head_val1}")
    assert not any(entry["code"] == "implicit_inheritance_candidates" for entry in diagnostics)


def test_semantic_warning_for_bare_index_operator_symbol() -> None:
    for text in ["sym = []", "P([])", "∀{| [] | [] = x}"]:
        diagnostics = collect_semantic_diagnostics_from_text(text)
        assert any(entry["code"] == "bare_index_operator_symbol" and entry["type"] == "warning" for entry in diagnostics), text


def test_semantic_bare_index_operator_symbol_exempts_definitions() -> None:
    for text in [
        "List\nList::[]: (list, id) => sym",
        "[]: (list, id) => sym",
        "Function ~ []",
        "x = [](list, id)",
    ]:
        diagnostics = collect_semantic_diagnostics_from_text(text)
        assert not any(entry["code"] == "bare_index_operator_symbol" for entry in diagnostics), text


def test_semantic_flags_undeclared_class_member_owner() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("Class::func: _class => _out")
    errors = [entry for entry in diagnostics if entry["type"] == "error"]
    assert errors == [
        {
            "file": "__stdin__",
            "lineno": 0,
            "col_start_no": 0,
            "col_end_no": 5,
            "type": "error",
            "code": "undeclared_class_member_owner",
            "reason": "class member declaration requires explicit class declaration: Class",
        }
    ]

    diagnostics = collect_semantic_diagnostics_from_text("A ~ Class\nClass::func: _class => _out")
    assert any(entry["code"] == "undeclared_class_member_owner" for entry in diagnostics)
    diagnostics = collect_semantic_diagnostics_from_text("Class::func: _class => _out\nClass\nOut")
    assert not any(entry["code"] == "undeclared_class_member_owner" for entry in diagnostics)


def test_semantic_flags_function_output_in_body_premise() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("F: x => y\n    | P(y)\n    y = y")
    assert not any(entry["code"] == "function_output_in_premise" for entry in diagnostics)


def test_semantic_flags_nested_function_output_in_body_premise() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("F: x => y\n    | P(G(y))\n    y = y")
    assert not any(entry["code"] == "function_output_in_premise" for entry in diagnostics)


def test_semantic_flags_predicate_output_in_body_premise() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("P: x => bool\n    | Q(bool)\n    P(x)")
    assert not any(entry["code"] == "function_output_in_premise" for entry in diagnostics)


def test_semantic_allows_function_output_in_target_and_generated_binding() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("F: x => y\n    y = F(x)")
    assert not any(entry["code"] == "function_output_in_premise" for entry in diagnostics)


def test_semantic_nested_premise_declaration_output_rule() -> None:
    ok = collect_semantic_diagnostics_from_text("F: x => y\n    | G: a => b\n        Q(b)\n    y = x")
    assert not any(entry["code"] == "function_output_in_premise" for entry in ok)

    failing = collect_semantic_diagnostics_from_text("F: x => y\n    | G: a => b\n        | P(b)\n        Q(b)\n    y = x")
    assert not any(entry["code"] == "function_output_in_premise" for entry in failing)


def test_sibling_submodules_can_reuse_name() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| x | x = x}\n}"))
    assert source.count("\n    | ^x\n") == 2


def test_authored_caret_generated_sym_is_accepted() -> None:
    ast = compile_text("∀{| ^x | ^x = ^x}")
    assert [sym["name"] for sym in ast["bound_syms"] if sym.get("generated")] == ["^x"]


def test_double_underscore_sym_is_not_generated() -> None:
    ast = compile_text("∀{| __x | __x = __x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["__x"]


def test_translate_omits_empty_binder_bar() -> None:
    ast = compile_text("Val ~ min_val\n∀{| val1 | val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    lines = source.splitlines()
    assert "|" not in [line.strip() for line in lines]
    assert any(line.strip() == "Val ~ min_val" for line in lines)
    assert not any(line.strip() == "| Val ~ min_val" for line in lines)
    assert any(line.strip() == "| ^val1" for line in lines)
    assert any(line.strip() == "| Symbol ~ ^val1" for line in lines)
    assert any(line.strip() == "^val1 ≥ min_val" for line in lines)


def test_translate_keeps_binder_line_when_present() -> None:
    ast = compile_text("∀{| x | x = x}")
    source = translate_ast_to_source(ast)
    assert "\n  | ^x" in source


def test_nested_module_disassembly_is_indented() -> None:
    ast = compile_text("-: (list, list1) => list2\n    list2.size = (list.size + list1.size)")
    source = translate_ast_to_source(ast)
    assert "\n  Function ~ -\n" in source
    assert "\n  ∀{\n" in source
    assert "\n    | ^list, ^list1, ^list2" in source
    assert "\n    | ^list2 = ^list - ^list1\n" in source
    assert "\n  }\n" in source


def test_function_output_inheritance_disassembles_as_target() -> None:
    text = "List\n-: (list, list1) => list2\n    list2.size = (list.size + list1.size)"
    first_source = translate_ast_to_source(compile_text(text, base_dir=SKILL_DIR))
    second_source = translate_ast_to_source(compile_text(first_source, base_dir=SKILL_DIR))
    assert "\n  | ^List\n" not in first_source
    assert "\n  | Symbol ~ List\n" not in first_source
    assert "\n  Symbol ~ List\n" not in first_source
    assert "\n    | List ~ ^list\n" in first_source
    assert "\n    | List ~ ^list1\n" in first_source
    assert "\n    | List ~ ^list2\n" not in first_source
    assert "\n    List ~ ^list2\n" in first_source
    assert second_source == first_source


def test_bound_syms_are_not_filtered_as_intrinsics() -> None:
    ast = compile_text("∀{| Symbol, Function, true, false | Symbol = Function}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["Symbol", "Function", "true", "false"]


def test_free_classifier_syms_are_not_auto_bound() -> None:
    ast = compile_text("∀{| x | Symbol ~ x | x = x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["x"]


def test_function_output_inheritance_cases() -> None:
    value_source = translate_ast_to_source(compile_text("Value\nF: value => out_value\n    out_value = out_value", base_dir=SKILL_DIR))
    assert "\n    | Value ~ ^value\n" in value_source
    assert "\n    | ^out_value = F(^value)\n" in value_source
    assert "\n    Value ~ ^out_value\n" in value_source
    assert "\n    | Value ~ ^out_value\n" not in value_source

    symbol_source = translate_ast_to_source(compile_text("F: x => y\n    y = y", base_dir=SKILL_DIR))
    assert "\n    | Symbol ~ ^x\n" in symbol_source
    assert "\n    | ^y = F(^x)\n" in symbol_source
    assert "\n    Symbol ~ ^y\n" in symbol_source

    generated_source = translate_ast_to_source(compile_text("F: ^x => ^y\n    ^y = ^y", base_dir=SKILL_DIR))
    assert "Symbol ~ ^x" not in generated_source
    assert "Symbol ~ ^y" not in generated_source

    bool_source = translate_ast_to_source(compile_text("Bool\nP: x => bool\n    P(x)", base_dir=SKILL_DIR))
    assert "\n    Bool ~ ^bool\n" in bool_source
    assert "\n    | Bool ~ ^bool\n" not in bool_source


def test_is_prefixed_declared_syms_implicitly_inherit_bool() -> None:
    input_source = translate_ast_to_source(compile_text("F: _is_val => out\n    P(_is_val)", base_dir=SKILL_DIR))
    assert "\n    | Bool ~ ^_is_val\n" in input_source
    assert "\n    Symbol ~ ^out\n" in input_source

    output_source = translate_ast_to_source(compile_text("F: x => is_valid", base_dir=SKILL_DIR))
    assert "\n    | Symbol ~ ^x\n" in output_source
    assert "\n    Bool ~ ^is_valid\n" in output_source
    assert "\n    | Bool ~ ^is_valid\n" not in output_source

    override_source = translate_ast_to_source(compile_text("Is_val\nF: _is_val => out\n    P(_is_val)", base_dir=SKILL_DIR))
    assert "\n    | Bool ~ ^_is_val\n" in override_source
    assert "Is_val ~ ^_is_val" not in override_source

    generated_source = translate_ast_to_source(compile_text("F: ^is_val => ^out\n    P(^is_val)", base_dir=SKILL_DIR))
    assert "Bool ~ ^is_val" not in generated_source
    assert "Symbol ~ ^is_val" not in generated_source


def test_function_declaration_without_output_guarantee_omits_rule() -> None:
    source = translate_ast_to_source(compile_text("F: ^x => ^y", base_dir=SKILL_DIR))
    assert source.strip() == "∀{\n  Function ~ F\n}"


def test_tuple_function_declaration_call_and_destructure_are_premises() -> None:
    source = translate_ast_to_source(compile_text("F: x => (y, z)", base_dir=SKILL_DIR))
    assert "\n    | ^tmpF0 = F(^x)\n" in source
    assert "\n    | ^y = ^tmpF0[^tmpvalue1]\n" in source
    assert "\n    | ^z = ^tmpF0[^tmpvalue2]\n" in source
    assert "\n    Tuple ~ ^tmpF0\n" in source
    assert "\n    Symbol ~ ^y\n" in source
    assert "\n    Symbol ~ ^z\n" in source


def test_generated_tuple_function_declaration_keeps_tuple_guarantee() -> None:
    source = translate_ast_to_source(compile_text("F: ^sym => (^sym1, ^sym2)", base_dir=SKILL_DIR))
    assert "\n  ∀{\n" in source
    assert "\n    | ^tmpF0 = F(^sym)\n" in source
    assert "\n    | ^sym1 = ^tmpF0[^tmpvalue1]\n" in source
    assert "\n    | ^sym2 = ^tmpF0[^tmpvalue2]\n" in source
    assert "\n    Tuple ~ ^tmpF0\n" in source
    assert "\n    Value ~ ^tmpvalue1\n" in source
    assert "\n    Value ~ ^tmpvalue2\n" in source
    assert "Symbol ~ ^sym" not in source
    assert "Symbol ~ ^sym1" not in source
    assert "Symbol ~ ^sym2" not in source
    assert "\n    | Tuple ~ ^tmpF0\n" not in source


def test_function_body_return_destructuring_omits_redundant_classifiers() -> None:
    source = translate_ast_to_source(
        compile_text("Sym\nF: sym => (sym1, sym2)\n    | P1(sym)\n    P2(sym1, sym2)", base_dir=SKILL_DIR)
    )
    assert "\n    | ^tmpF0 = F(^sym)\n" in source
    assert "\n    Tuple ~ ^tmpF0\n" in source
    assert "\n    Value ~ ^tmpvalue1\n" in source
    assert "\n    Value ~ ^tmpvalue2\n" in source
    assert "\n    | ^tmpF3 = F(^sym)\n" in source
    assert "\n    | ^sym1 = ^tmpF3[^tmpvalue4]\n" in source
    assert "\n    | ^sym2 = ^tmpF3[^tmpvalue5]\n" in source
    assert source.count("Tuple ~ ^tmpF") == 1
    assert source.count("Value ~ ^tmpvalue") == 2
    assert "\n    P2(^sym1, ^sym2)\n" in source


def test_function_body_local_literal_classifier_is_preserved() -> None:
    source = translate_ast_to_source(compile_text("Sym\nF: sym => out\n    P((sym, out))", base_dir=SKILL_DIR))
    assert source.count("Tuple ~ ") == 1
    assert "\n    Tuple ~ ^tmpsym_out" in source
    assert "P(^tmpsym_out" in source


def test_sibling_nested_modules_are_indented_consistently() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| x | x = x}\n∀{| y | y = y}\n}"))
    assert source.count("\n  ∀{\n") == 2
    assert "\n    | ^x\n" in source
    assert "\n    | ^y\n" in source


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
    assert source.count("\n  Value ~ ^tmp10\n") == 1, source


def test_target_module_assignment_normalized() -> None:
    ast = compile_text("∀{| x | x = ∀{| y | y = y}}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "quantified_stmt" for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_PSs")


def test_multiline_binding_rhs_disassembly_is_indented() -> None:
    text = "sym = {| ^sym | ^sym >= 0 => ^sym + 1}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert "\n  | ^tmpmodule03 = {\n    | ^logic_language_out0\n" in first_source
    assert "\n    ∃{\n      | ^sym, ^tmp00, ^tmp11, ^tmpadd2\n" in first_source
    assert "\n      Value ~ ^tmp00\n      Value ~ ^tmp11\n      ^logic_language_out0 = ^tmpadd2\n" in first_source
    assert "\n    }\n  }\n  sym = ^tmpmodule03\n" in first_source
    assert "\n}\n  sym = ^tmpmodule03\n" not in first_source
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
    assert first_source.count("| Symbol ~ ^val1") == 1
    assert "| ^val1 ~ ^val1" not in first_source
    assert "| Val ~ ^val1" not in first_source


def test_generated_temp_round_trip_is_idempotent() -> None:
    text = "-: (list, list1) => list2\n    list2.size = (list.size + list1.size)"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert first_source == second_source
    assert "| ^tmpfunc_stmt0 ~ ^tmpfunc_stmt0" not in second_source
    assert "| ^tmpsize1 ~ ^tmpsize1" not in second_source
    assert "| ^tmpsize2 ~ ^tmpsize2" not in second_source
    assert "| ^tmpfunc_stmt3 ~ ^tmpfunc_stmt3" not in second_source


def test_wrapper_round_trip_is_stable() -> None:
    text = "∀{| a, b | Tuple ~ (a, b)}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert second_source == first_source


def test_tuple_assignment_round_trip_adds_classifier_predicate() -> None:
    text = "x = (a, b)"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert "\n  Tuple ~ ^tmpa_b0\n" in first_source
    assert "| Tuple ~ ^tmpa_b0" not in first_source
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


def test_module_check_syntax_error_stops_before_semantic_and_compile() -> None:
    original_semantic_entries = module_check.semantic_entries
    original_run_compile_pipeline = module_check.run_compile_pipeline

    def fail_semantic(*args, **kwargs):
        raise AssertionError("semantic check should not run after syntax errors")

    def fail_compile(*args, **kwargs):
        raise AssertionError("compile should not run after syntax errors")

    module_check.semantic_entries = fail_semantic
    module_check.run_compile_pipeline = fail_compile
    try:
        payload = module_check.check_module("∀{| x | x = x", module_check.STDIN_FILE, Path("."), is_file=False)
    finally:
        module_check.semantic_entries = original_semantic_entries
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert payload["summary"]["error_count"] >= 1
    assert {entry["stage"] for entry in payload["entries"]} == {"syntax"}


def test_module_check_set_literals_are_not_set_modules() -> None:
    for text in ["syms = {}", "syms = {1, 2, 3}"]:
        payload = module_check.check_module(text, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 0, (text, payload)


def test_module_check_supports_set_union_infix_with_set_literal() -> None:
    payload = module_check.check_module(
        "syms = func_stmt.arg_sym_list \\union {func_stmt.call_sym}",
        module_check.STDIN_FILE,
        Path("."),
        is_file=False,
    )
    assert payload["summary"]["error_count"] == 0, payload


def test_module_check_set_module_syntax_still_reports_located_errors() -> None:
    payload = module_check.check_module("{| }", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["code"] == "set_module_missing_syms"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 0


def test_module_check_warning_only_bare_index_operator_symbol_exits_clean() -> None:
    payload = module_check.check_module("sym = []", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"] == {"error_count": 0, "warning_count": 1}
    entry = payload["entries"][0]
    assert entry["stage"] == "semantic"
    assert entry["code"] == "bare_index_operator_symbol"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 6


def test_module_check_positioned_branch_error_avoids_file_start_fallback() -> None:
    payload = module_check.check_module("F: x => y\n    |- P(x)", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["code"] == "syntax_error"
    assert entry["reason"] == "branch header requires an indented block"
    assert entry["lineno"] == 1
    assert entry["col_start_no"] == 4


def test_module_check_positioned_unsupported_coloncolon_errors() -> None:
    payload = module_check.check_module(
        "Not_stmt\n"
        "    ::call_sym: not_stmt => sym\n"
        "        sym = '\\lnot'\n"
        "    ::sym\n"
        "    ::arg_sym_list [not_stmt.sym]\n",
        module_check.STDIN_FILE,
        Path("."),
        is_file=False,
    )

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["reason"] == "unsupported '::' usage; '::' is only supported in declaration heads"
    assert entry["lineno"] == 4
    assert entry["col_start_no"] == 4
    assert entry["col_end_no"] == 6


def test_module_check_class_field_assignment_succeeds() -> None:
    payload = module_check.check_module("Value\nField\nClass\nValue ~ value\nClass\n    ::field = value\n", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 0
    assert payload["summary"]["warning_count"] == 0


def test_module_check_positioned_class_field_assignment_body_error() -> None:
    payload = module_check.check_module("Class\n    ::field = x\n        P(x)\n", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["reason"] == "class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration"
    assert entry["lineno"] == 1
    assert entry["col_start_no"] == 4
    assert entry["col_end_no"] == 6


def test_module_check_positioned_arrow_and_literal_errors() -> None:
    cases = [
        ("f: x -> y\n    P(y)\n", "function-assign '->' is not supported; use '=>' with an indented function body", 0, 5, 7),
        ("x = '\\q'\n", "invalid escape sequence \\q", 0, 5, 7),
        ("'x' = y\n", "literal cannot appear on assignment left-hand side", 0, 0, 1),
    ]

    for text, reason, line, col_start, col_end in cases:
        payload = module_check.check_module(text, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 1, (text, payload)
        entry = payload["entries"][0]
        assert entry["stage"] == "syntax"
        assert entry["reason"] == reason
        assert entry["lineno"] == line
        assert entry["col_start_no"] == col_start
        assert entry["col_end_no"] == col_end


def test_module_check_imported_located_syntax_error_uses_import_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        imported = tmp_path / "bad.lp"
        imported.write_text("Class\n    ::field = x\n        P(x)\n", encoding="utf-8")
        payload = module_check.check_module(
            "$import bad.lp\nok = ok",
            str(tmp_path / "main.lp"),
            tmp_path,
            is_file=False,
        )

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["file"] == str(imported.resolve())
    assert entry["reason"] == "class-field shorthand cannot have a function body; use Class::field: input => output for an explicit function declaration"
    assert entry["lineno"] == 1
    assert entry["col_start_no"] == 4


def test_module_check_undeclared_class_member_owner_is_semantic_error() -> None:
    payload = module_check.check_module("Class::func: _class => _out", module_check.STDIN_FILE, Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "semantic"
    assert entry["code"] == "undeclared_class_member_owner"
    assert entry["reason"] == "class member declaration requires explicit class declaration: Class"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 0
    assert entry["col_end_no"] == 5

    payload = module_check.check_module("A ~ Class\nClass::func: _class => _out", module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 1
    assert payload["entries"][0]["code"] == "undeclared_class_member_owner"


def test_module_check_semantic_error_stops_before_compile() -> None:
    original_semantic_entries = module_check.semantic_entries
    original_run_compile_pipeline = module_check.run_compile_pipeline

    def semantic_error(*args, **kwargs):
        return [
            {
                "file": module_check.STDIN_FILE,
                "lineno": 0,
                "col_start_no": 0,
                "col_end_no": 1,
                "type": "error",
                "code": "semantic_test_error",
                "reason": "semantic failed",
                "stage": "semantic",
            }
        ]

    def fail_compile(*args, **kwargs):
        raise AssertionError("compile should not run after semantic errors")

    module_check.semantic_entries = semantic_error
    module_check.run_compile_pipeline = fail_compile
    try:
        payload = module_check.check_module("∀{| x | x = x}", module_check.STDIN_FILE, Path("."), is_file=False)
    finally:
        module_check.semantic_entries = original_semantic_entries
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert payload["summary"]["error_count"] == 1
    assert any(entry["code"] == "semantic_test_error" and entry["stage"] == "semantic" for entry in payload["entries"])


def test_module_check_semantic_warning_continues_to_compile() -> None:
    original_semantic_entries = module_check.semantic_entries
    original_run_compile_pipeline = module_check.run_compile_pipeline
    called = {"compile": False}

    def semantic_warning(*args, **kwargs):
        return [
            {
                "file": module_check.STDIN_FILE,
                "lineno": 0,
                "col_start_no": 0,
                "col_end_no": 1,
                "type": "warning",
                "code": "semantic_test_warning",
                "reason": "semantic warning",
                "stage": "semantic",
            }
        ]

    def compile_ok(*args, **kwargs):
        called["compile"] = True

    module_check.semantic_entries = semantic_warning
    module_check.run_compile_pipeline = compile_ok
    try:
        payload = module_check.check_module("∀{| x | x = x}", module_check.STDIN_FILE, Path("."), is_file=False)
    finally:
        module_check.semantic_entries = original_semantic_entries
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert called["compile"]
    assert payload["summary"] == {"error_count": 0, "warning_count": 1}


def test_module_check_compile_error_uses_entry_file_start() -> None:
    original_run_compile_pipeline = module_check.run_compile_pipeline

    def compile_fails(*args, **kwargs):
        raise CompileError("lowering failed")

    module_check.run_compile_pipeline = compile_fails
    try:
        payload = module_check.check_module("∀{| x | x = x}", "/tmp/input.lp", Path("."), is_file=False)
    finally:
        module_check.run_compile_pipeline = original_run_compile_pipeline

    entry = next(entry for entry in payload["entries"] if entry["stage"] == "compile")
    assert payload["summary"]["error_count"] == 1
    assert entry["stage"] == "compile"
    assert entry["file"] == "/tmp/input.lp"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 0
    assert entry["code"] == "compile_error"


def test_module_check_compile_error_uses_source_fragment_location() -> None:
    payload = module_check.check_module("x = a ??? b\n", "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "compile"
    assert entry["file"] == "/tmp/input.lp"
    assert entry["reason"] == "unsupported expression: a ??? b"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 4
    assert entry["col_end_no"] == 11
    assert entry["code"] == "compile_error"

    payload = module_check.check_module("1\n", "/tmp/input.lp", Path("."), is_file=False)
    entry = payload["entries"][0]
    assert entry["stage"] == "compile"
    assert entry["reason"] == "unsupported non-call statement: 1"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 0
    assert entry["col_end_no"] == 1


def test_module_check_final_ast_diagnostics_keep_location_and_code() -> None:
    original_run_compile_pipeline = module_check.run_compile_pipeline
    diagnostic = {
        "file": "/tmp/final.lp",
        "lineno": 2,
        "col_start_no": 3,
        "col_end_no": 4,
        "type": "error",
        "code": "invalid_bound_sym_name",
        "reason": "bad name",
    }

    def final_ast_fails(*args, **kwargs):
        raise compile_module_script.FinalAstValidationCompileError("bad final ast", [], [diagnostic])

    module_check.run_compile_pipeline = final_ast_fails
    try:
        payload = module_check.check_module("∀{| x | x = x}", "/tmp/input.lp", Path("."), is_file=False)
    finally:
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert payload["summary"]["error_count"] == 1
    assert {**diagnostic, "stage": "final_ast"} in payload["entries"]


def test_module_check_final_ast_plain_declaration_conflict_uses_input_location() -> None:
    source = "∀\n    | x\n    F: x => y\n"
    payload = module_check.check_module(source, "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = next(entry for entry in payload["entries"] if entry["stage"] == "final_ast")
    assert entry["stage"] == "final_ast"
    assert entry["code"] == "bound_sym_name_conflict"
    assert entry["reason"] == "bound-sym name 'x' conflicts with ancestor statement"
    assert entry["lineno"] == 2
    assert entry["col_start_no"] == source.splitlines()[2].index("x")


def test_module_check_final_ast_class_method_body_conflict_uses_declaration_location() -> None:
    source = "∀\n    | x\n    Class\n    Class::m: x => y\n        P(y)\n"
    payload = module_check.check_module(source, "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 2
    entry = next(entry for entry in payload["entries"] if entry["stage"] == "final_ast")
    assert entry["stage"] == "final_ast"
    assert entry["code"] == "bound_sym_name_conflict"
    assert entry["lineno"] == 3
    assert entry["col_start_no"] == source.splitlines()[3].index("x")


def test_module_check_text_import_resolves_standard_library_from_skill_dir() -> None:
    result = subprocess.run(
        [
            "python3",
            str(SCRIPTS_DIR / "module_check.py"),
            "--text",
            "$import standard_library.lp\n∀{| _val | _val = _val}",
            "--base-dir",
            tempfile.gettempdir(),
        ],
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert not any(entry["code"] == "missing_import" for entry in payload["entries"])
    assert payload["summary"] == {"error_count": 0, "warning_count": 0}


def test_module_check_standard_library_is_clean() -> None:
    payload = module_check.check_module(
        (SKILL_DIR / "standard_library.lp").read_text(encoding="utf-8"),
        str((SKILL_DIR / "standard_library.lp").resolve()),
        SKILL_DIR,
        is_file=True,
    )
    assert payload["summary"] == {"error_count": 0, "warning_count": 0}, payload
    assert payload["entries"] == []


def test_module_check_stdin_import_uses_base_dir() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "imported.lp").write_text("Imported\n", encoding="utf-8")
        result = subprocess.run(
            [
                "python3",
                str(SCRIPTS_DIR / "module_check.py"),
                "--base-dir",
                str(root),
            ],
            input="$import imported.lp\n∀{| x | x = x}",
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["error_count"] == 0


def test_expand_module_cli_text_mode() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / "expand_module.py"), "--text", "∀{| x | x = x}"],
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^x\n  | Symbol ~ ^x\n  ^x = ^x\n}\n"


def test_expand_module_cli_file_mode() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "input.lp"
        path.write_text("∀{| x | x = x}", encoding="utf-8")
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "expand_module.py"), str(path)],
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^x\n  | Symbol ~ ^x\n  ^x = ^x\n}\n"


def test_expand_module_cli_stdin_mode() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / "expand_module.py")],
        input="∀{| x | x = x}",
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^x\n  | Symbol ~ ^x\n  ^x = ^x\n}\n"


def test_expand_module_cli_invalid_input() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / "expand_module.py"), "--text", "∀{| 1x | 1x = 1x}"],
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr


def test_normalize_module_declarations_groups_source_units() -> None:
    source = "\n".join(
        [
            "y",
            "F: _a => _b",
            "    _b = _a",
            "Class::m: _class => _out",
            "    _out = _class",
            "A ~ B",
            "F: _x => _y",
            "    _y = _x",
            "Class",
            "    ::field",
            "    ::m: _class => _out2",
            "        _out2 = _class",
            "z = z",
        ]
    )
    assert normalize_module_declarations.normalize_module_declarations_text(source) == "\n".join(
        [
            "y",
            "A ~ B",
            "Class",
            "    ::m: _class => _out",
            "        _out = _class",
            "    ::m: _class => _out2",
            "        _out2 = _class",
            "    ::field",
            "F: _a => _b",
            "    _b = _a",
            "F: _x => _y",
            "    _y = _x",
            "z = z",
            "",
        ]
    )


def test_normalize_module_declarations_places_inheritance_before_member_bodies() -> None:
    source = "\n".join(
        [
            "B",
            "A",
            "A ~ B",
            "B::method: (_b, _in) => _out",
            "    P(_out)",
        ]
    )
    assert normalize_module_declarations.normalize_module_declarations_text(source) == "\n".join(
        [
            "A",
            "A ~ B",
            "B",
            "    ::method: (_b, _in) => _out",
            "        P(_out)",
            "",
        ]
    )


def test_normalize_module_declarations_unindents_multiline_logical_member_body() -> None:
    source = "\n".join(
        [
            "Class",
            "Class::m: _class => _out",
            "    _out = {",
            "        | _item",
            "        P(_item)",
            "    }",
        ]
    )
    assert normalize_module_declarations.normalize_module_declarations_text(source) == "\n".join(
        [
            "Class",
            "    ::m: _class => _out",
            "        _out = {",
            "            | _item",
            "            P(_item)",
            "        }",
            "",
        ]
    )


def test_normalize_module_declarations_respects_nested_block_barriers() -> None:
    source = "\n".join(
        [
            "B",
            "A ~ B",
            "F: _a => _b",
            "    _b = _a",
            "∀",
            "    D",
            "    C",
            "    C ~ D",
            "    D::m: _d => _out",
            "        P(_out)",
            "    H: _x => _y",
            "        _y = _x",
            "    h = h",
            "F: _x => _y",
            "    _y = _x",
        ]
    )
    assert normalize_module_declarations.normalize_module_declarations_text(source) == "\n".join(
        [
            "B",
            "A ~ B",
            "F: _a => _b",
            "    _b = _a",
            "∀",
            "    C",
            "    C ~ D",
            "    D",
            "        ::m: _d => _out",
            "            P(_out)",
            "    H: _x => _y",
            "        _y = _x",
            "    h = h",
            "F: _x => _y",
            "    _y = _x",
            "",
        ]
    )


def test_normalize_module_declarations_opaque_exists_and_declaration_bodies() -> None:
    source = "\n".join(
        [
            "G: _a => _b",
            "    ∀",
            "        F: _x => _y",
            "            _y = _x",
            "        f = f",
            "    _b = _a",
            "∃{",
            "| _x",
            "F: _x => _y",
            "    _y = _x",
            "}",
            "G: _x => _y",
            "    _y = _x",
        ]
    )
    normalized = normalize_module_declarations.normalize_module_declarations_text(source)
    assert normalized.count("G:") == 2
    assert "    ∀\n        F: _x => _y\n            _y = _x\n        f = f" in normalized
    assert "∃{\n| _x\nF: _x => _y\n    _y = _x\n}" in normalized
    assert normalized.index("G: _a => _b") < normalized.index("∃{") < normalized.index("G: _x => _y")


def test_normalize_module_declarations_cli_modes_and_imports() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        imported = root / "imported.lp"
        source_file = root / "source.lp"
        imported.write_text("Imported\n", encoding="utf-8")
        source_file.write_text("$import imported.lp\nf = f", encoding="utf-8")

        file_result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "normalize_module_declarations.py"), str(source_file)],
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
        text_result = subprocess.run(
            [
                "python3",
                str(SCRIPTS_DIR / "normalize_module_declarations.py"),
                "--base-dir",
                str(root),
                "--text",
                "$import imported.lp\nf = f",
            ],
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
        stdin_result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "normalize_module_declarations.py"), "--base-dir", str(root)],
            input="$import imported.lp\nf = f",
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )

    for result in (file_result, text_result, stdin_result):
        assert result.returncode == 0, result.stderr or result.stdout
        assert result.stderr == ""
        assert result.stdout == "Imported\nf = f\n"


def test_normalize_module_declarations_dedupes_transitive_imports() -> None:
    normalized = normalize_module_declarations.normalize_module_declarations_text(
        (SKILL_DIR / "semantic_logic" / "sym_type_resolver.lp").read_text(encoding="utf-8"),
        SKILL_DIR / "semantic_logic",
        source=str((SKILL_DIR / "semantic_logic" / "sym_type_resolver.lp").resolve()),
        allow_imports=True,
    )
    assert [line for line in normalized.splitlines() if line == "Stmt~Binding_stmt"] == ["Stmt~Binding_stmt"]
    assert [line for line in normalized.splitlines() if line == "Stmt"] == ["Stmt"]
    assert "    ::get_sym_type: (_stmt, _sym) => _sym_type" in normalized
    lines = normalized.splitlines()
    assert lines.index("Stmt~Binding_stmt") + 1 == lines.index("Binding_stmt")


def test_normalize_module_declarations_requires_explicit_class_members() -> None:
    for source in ["Class::m: _class => _out", "A ~ Class\nClass::m: _class => _out", "Class::field = value"]:
        try:
            normalize_module_declarations.normalize_module_declarations_text(source)
        except CompileError as error:
            assert "class member declaration requires explicit class declaration: Class" in str(error)
        else:
            raise AssertionError(f"expected undeclared class member owner to fail: {source!r}")

    normalized = normalize_module_declarations.normalize_module_declarations_text("Class::m: _class => _out\nClass")
    assert "Class\n    ::m: _class => _out" in normalized

    normalized = normalize_module_declarations.normalize_module_declarations_text("Class::field = value\nClass")
    assert "Class\n    ::field = value" in normalized

    normalized = normalize_module_declarations.normalize_module_declarations_text("Class\n    ::field = value")
    assert "Class\n    ::field = value" in normalized

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "imported.lp").write_text("Class\n", encoding="utf-8")
        normalized = normalize_module_declarations.normalize_module_declarations_text(
            "$import imported.lp\nClass::m: _class => _out",
            base_dir=root,
        )
    assert "Class\n    ::m: _class => _out" in normalized


def test_normalize_module_declarations_cli_invalid_input() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / "normalize_module_declarations.py"), "--text", "∀{\n  x = x"],
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr


def test_resolve_sym_type_class_func_pred_and_alias_evidence() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Func = Function",
                "Func ~ f",
                "Pred = Predicate",
                "Pred ~ p",
                "Class",
                "y = f(x)",
                "p(x)",
            ]
        )
    )
    assert resolved_symbol(payload, "Class")["type"] == "class"
    assert resolved_symbol(payload, "f")["type"] == "func"
    assert resolved_symbol(payload, "p")["type"] == "pred"
    assert resolved_symbol(payload, "x")["type"] == "pure"
    assert any(entry["colorable"] for entry in resolved_occurrences(payload, "Class"))
    assert any(entry["colorable"] for entry in resolved_occurrences(payload, "f"))
    assert any(entry["colorable"] for entry in resolved_occurrences(payload, "p"))


def test_resolve_sym_type_predicate_wins_over_function() -> None:
    payload = resolve_sym_type.resolve_text("Function ~ p\nPredicate ~ p\np(x)")
    assert resolved_symbol(payload, "p")["type"] == "pred"


def test_resolve_sym_type_class_wins_over_callable_evidence() -> None:
    payload = resolve_sym_type.resolve_text("Predicate\nFunction ~ Predicate\nPred = Predicate")
    assert resolved_symbol(payload, "Predicate")["type"] == "class"
    assert resolved_symbol(payload, "Pred")["type"] == "class"


def test_resolve_sym_type_operator_symbols_are_not_colorable() -> None:
    payload = resolve_sym_type.resolve_text("Function ~ []\nx = [](y)\nz = [:](x, y)")
    assert resolved_symbol(payload, "[]")["type"] == "func"
    assert resolved_symbol(payload, "=")["type"] == "pred"
    assert resolved_symbol(payload, "~")["type"] == "pred"
    assert resolved_symbol(payload, "[:]")["type"] == "func"
    assert all(not entry["colorable"] for entry in resolved_occurrences(payload, "[]"))
    assert all(not entry["colorable"] for entry in resolved_occurrences(payload, "="))
    assert all(not entry["colorable"] for entry in resolved_occurrences(payload, "~"))


def test_resolve_sym_type_definition_locations() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "A~B",
                "B",
                "f: x => y",
                "    y = f(x)",
                "Function ~ g",
                "z = g(y)",
                "Predicate ~ p",
                "p(z)",
            ]
        )
    )
    assert "definition" not in occurrence_on_line(payload, "A", 0)
    assert occurrence_on_line(payload, "B", 0)["definition"]["lineno"] == 1
    assert occurrence_on_line(payload, "f", 3)["definition"]["lineno"] == 2
    assert occurrence_on_line(payload, "g", 5)["definition"]["lineno"] == 4
    assert occurrence_on_line(payload, "p", 7)["definition"]["lineno"] == 6
    assert "definition" not in occurrence_on_line(payload, "x", 3)
    assert "definition" not in occurrence_on_line(payload, "z", 7)


def test_resolve_sym_type_class_typed_pure_symbol_definition() -> None:
    payload = resolve_sym_type.resolve_text("Notsubset_stmt\nNotsubset_stmt ~ notsubset_stmt\nP(notsubset_stmt)")
    occurrence = occurrence_on_line(payload, "notsubset_stmt", 2)
    assert occurrence["type"] == "pure"
    assert not occurrence["colorable"]
    assert occurrence["definition"] == {
        "file": "__stdin__",
        "lineno": 0,
        "col_start_no": 0,
        "col_end_no": len("Notsubset_stmt"),
        "name": "Notsubset_stmt",
        "type": "class",
    }


def test_resolve_sym_type_class_typed_pure_symbol_falls_back_to_fact() -> None:
    payload = resolve_sym_type.resolve_text("Class ~ value\nP(value)")
    occurrence = occurrence_on_line(payload, "value", 1)
    assert occurrence["type"] == "pure"
    assert occurrence["definition"] == {
        "file": "__stdin__",
        "lineno": 0,
        "col_start_no": len("Class ~ "),
        "col_end_no": len("Class ~ value"),
        "name": "value",
        "type": "class",
    }


def test_resolve_sym_type_class_typed_pure_symbol_beats_pure_intro() -> None:
    payload = resolve_sym_type.resolve_text("| value\nClass\nClass ~ value\nP(value)")
    occurrence = occurrence_on_line(payload, "value", 3)
    assert occurrence["type"] == "pure"
    assert occurrence["definition"]["name"] == "Class"
    assert occurrence["definition"]["lineno"] == 1


def test_resolve_sym_type_untyped_pure_symbol_has_no_definition() -> None:
    payload = resolve_sym_type.resolve_text("| x\nP(x)")
    assert "definition" not in occurrence_on_line(payload, "x", 0)
    assert "definition" not in occurrence_on_line(payload, "x", 1)


def test_resolve_sym_type_output_uses_generated_signature_class_evidence() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Sym_type",
                "Stmt",
                "Stmt::get_sym_type: (stmt, sym) => sym_type",
                "    sym_type = sym_type",
            ]
        )
    )
    occurrence = occurrence_on_line(payload, "sym_type", 2)
    assert occurrence["type"] == "pure"
    assert not occurrence["colorable"]
    assert occurrence["definition"] == {
        "file": "__stdin__",
        "lineno": 0,
        "col_start_no": 0,
        "col_end_no": len("Sym_type"),
        "name": "Sym_type",
        "type": "class",
    }


def test_resolve_sym_type_inputs_use_generated_signature_class_evidence() -> None:
    payload = resolve_sym_type.resolve_text("Val\nmax: (_val1, _val2) => _val")
    for name in ["_val1", "_val2", "_val"]:
        occurrence = occurrence_on_line(payload, name, 1)
        assert occurrence["type"] == "pure"
        assert not occurrence["colorable"]
        assert occurrence["definition"]["name"] == "Val"
        assert occurrence["definition"]["lineno"] == 0


def test_resolve_sym_type_signature_class_evidence_uses_numeric_suffixes() -> None:
    payload = resolve_sym_type.resolve_text("Val\nList\n[:]: (_val1, _val2) => _list")
    assert occurrence_on_line(payload, "_val1", 2)["definition"]["name"] == "Val"
    assert occurrence_on_line(payload, "_val2", 2)["definition"]["name"] == "Val"
    assert occurrence_on_line(payload, "_list", 2)["definition"]["name"] == "List"


def test_resolve_sym_type_class_suffix_fallback_definition() -> None:
    payload = resolve_sym_type.resolve_text("Chip_mem\nF: _chip_mem_class => _out")
    occurrence = occurrence_on_line(payload, "_chip_mem_class", 1)
    assert occurrence["type"] == "pure"
    assert not occurrence["colorable"]
    assert occurrence["definition"]["name"] == "Chip_mem"
    assert occurrence["definition"]["lineno"] == 0


def test_resolve_sym_type_generated_binder_class_evidence_defines_pure_symbol() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Id",
                "F: _x => _out",
                "    ∀{",
                "        | _id1, _id2",
                "        | 0 ≤ _id1 < _id2",
                "        P(_id1, _id2)",
                "    }",
            ]
        )
    )
    for name in ["_id1", "_id2"]:
        occurrence = occurrence_on_line(payload, name, 3)
        assert occurrence["type"] == "pure"
        assert not occurrence["colorable"]
        assert occurrence["definition"]["name"] == "Id"
        assert occurrence["definition"]["lineno"] == 0


def test_resolve_sym_type_authored_premise_class_fact_does_not_define_pure_symbol() -> None:
    payload = resolve_sym_type.resolve_text("Val\nF: x => y\n    | Val ~ x\n    y = y")
    assert "definition" not in occurrence_on_line(payload, "x", 1)
    assert "definition" not in occurrence_on_line(payload, "x", 2)


def test_resolve_sym_type_authored_premise_class_fact_is_not_class_navigation_evidence() -> None:
    payload = resolve_sym_type.resolve_text("Id\nF: x => y\n    | Id ~ x\n    y = y")
    assert "definition" not in occurrence_on_line(payload, "x", 1)
    assert "definition" not in occurrence_on_line(payload, "x", 2)


def test_resolve_sym_type_imported_signature_class_definition() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        imported = root / "imported.lp"
        imported.write_text("Val\n", encoding="utf-8")
        main = root / "main.lp"
        main.write_text("$import imported.lp\nmax: (_val1, _val2) => _val\n", encoding="utf-8")
        payload = resolve_sym_type.resolve_file(main)

    for name in ["_val1", "_val2", "_val"]:
        definition = occurrence_on_line(payload, name, 1)["definition"]
        assert definition["file"] == str(imported.resolve())
        assert definition["name"] == "Val"


def test_resolve_sym_type_target_equality_propagates_class_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Sym_type",
                "Sym_type ~ class_sym_type",
                "f: x => out",
                "    out = class_sym_type",
            ]
        )
    )
    assert occurrence_on_line(payload, "out", 2)["definition"]["name"] == "Sym_type"
    assert occurrence_on_line(payload, "out", 3)["definition"]["name"] == "Sym_type"


def test_resolve_sym_type_premise_equality_does_not_propagate_class_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Sym_type",
                "Sym_type ~ class_sym_type",
                "f: x => out",
                "    | out = class_sym_type",
                "    out = out",
            ]
        )
    )
    assert "definition" not in occurrence_on_line(payload, "out", 2)
    assert "definition" not in occurrence_on_line(payload, "out", 3)
    assert "definition" not in occurrence_on_line(payload, "out", 4)


def test_resolve_sym_type_inheritance_fact_does_not_define_capital_class_name() -> None:
    payload = resolve_sym_type.resolve_text("A\nA~B\nP(B)")
    assert "definition" not in occurrence_on_line(payload, "B", 1)
    assert "definition" not in occurrence_on_line(payload, "B", 2)


def test_resolve_sym_type_class_block_receiver_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Notsubset_stmt",
                "    ::lhs_sym",
                "    ::rhs_sym",
                "    ::arg_sym_list: notsubset_stmt => list",
                "        list = [notsubset_stmt.lhs_sym, notsubset_stmt.rhs_sym]",
            ]
        )
    )
    for line in [3, 4]:
        occurrence = occurrence_on_line(payload, "notsubset_stmt", line)
        assert occurrence["type"] == "pure"
        assert occurrence["definition"]["name"] == "Notsubset_stmt"
        assert occurrence["definition"]["lineno"] == 0


def test_resolve_sym_type_qualified_class_owner_receiver_definition() -> None:
    payload = resolve_sym_type.resolve_text("Notsubset_stmt\nNotsubset_stmt::arg_sym_list: notsubset_stmt => list\n    list = notsubset_stmt")
    for line in [1, 2]:
        occurrence = occurrence_on_line(payload, "notsubset_stmt", line)
        assert occurrence["type"] == "pure"
        assert occurrence["definition"]["name"] == "Notsubset_stmt"
        assert occurrence["definition"]["lineno"] == 0
        assert occurrence["definition"]["col_start_no"] == 0


def test_resolve_sym_type_imported_class_typed_definition() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        imported = root / "imported.lp"
        imported.write_text("Imported_class\n", encoding="utf-8")
        main = root / "main.lp"
        main.write_text("$import imported.lp\nImported_class ~ value\nP(value)\n", encoding="utf-8")
        payload = resolve_sym_type.resolve_file(main)

    definition = occurrence_on_line(payload, "value", 2)["definition"]
    assert definition["file"] == str(imported.resolve())
    assert definition["name"] == "Imported_class"
    assert definition["type"] == "class"


def test_resolve_sym_type_class_typed_definition_uses_first_evidence() -> None:
    payload = resolve_sym_type.resolve_text("A\nB\nA ~ value\nB ~ value\nP(value)")
    for line in [2, 3, 4]:
        definition = occurrence_on_line(payload, "value", line)["definition"]
        assert definition["name"] == "A"
        assert definition["lineno"] == 0


def test_resolve_sym_type_function_and_predicate_use_declaration_heads() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Function ~ f",
                "f: x => y",
                "    y = x",
                "Predicate ~ p",
                "p: x => bool",
                "    bool = true",
                "z = f(x)",
                "p(z)",
            ]
        )
    )
    assert occurrence_on_line(payload, "f", 6)["definition"]["lineno"] == 1
    assert occurrence_on_line(payload, "p", 7)["definition"]["lineno"] == 4


def test_resolve_sym_type_member_call_uses_qualified_class_method_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "func: x => y",
                "    y = x",
                "Class ~ receiver",
                "Class::func: receiver => out",
                "    out = receiver",
                "y = receiver.func",
            ]
        )
    )
    definition = occurrence_on_line(payload, "func", 6)["definition"]
    assert definition["lineno"] == 4
    assert definition["col_start_no"] == len("Class::")


def test_resolve_sym_type_member_call_uses_indented_class_method_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "    ::func: receiver => out",
                "        out = receiver",
                "Class ~ receiver",
                "y = receiver.func",
            ]
        )
    )
    definition = occurrence_on_line(payload, "func", 4)["definition"]
    assert definition["lineno"] == 1
    assert definition["col_start_no"] == len("    ::")


def test_resolve_sym_type_member_call_uses_bare_class_field_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "    ::field",
                "Class ~ receiver",
                "y = receiver.field",
            ]
        )
    )
    definition = occurrence_on_line(payload, "field", 3)["definition"]
    assert definition["lineno"] == 1
    assert definition["col_start_no"] == len("    ::")


def test_resolve_sym_type_bare_class_field_in_premise_section_is_function() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Graph",
                "Graph~Class",
                "Class",
                "    ::field",
                "B",
                "B~b",
            ]
        )
    )
    symbol = resolved_symbol(payload, "field")
    assert symbol["type"] == "func"
    occurrence = occurrence_on_line(payload, "field", 3)
    assert occurrence["colorable"] is True


def test_resolve_sym_type_member_call_falls_back_to_function_declaration() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "func: x => y",
                "    y = x",
                "Class ~ receiver",
                "y = receiver.func",
            ]
        )
    )
    definition = occurrence_on_line(payload, "func", 4)["definition"]
    assert definition["lineno"] == 1


def test_resolve_sym_type_imported_definition_locations() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        imported = root / "imported.lp"
        imported.write_text("Imported_class\nFunction ~ f\n", encoding="utf-8")
        main = root / "main.lp"
        main.write_text("$import imported.lp\nvalue = f(Imported_class)\n", encoding="utf-8")
        payload = resolve_sym_type.resolve_file(main)

    class_definition = occurrence_on_line(payload, "Imported_class", 1)["definition"]
    function_definition = occurrence_on_line(payload, "f", 1)["definition"]
    assert class_definition["file"] == str(imported.resolve())
    assert class_definition["lineno"] == 0
    assert function_definition["file"] == str(imported.resolve())
    assert function_definition["lineno"] == 1
    assert {entry["file"] for entry in payload["occurrences"]} == {str(main.resolve())}


def test_resolve_sym_type_definition_prefers_current_file() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        imported = root / "imported.lp"
        imported.write_text("Function ~ f\n", encoding="utf-8")
        main = root / "main.lp"
        main.write_text("$import imported.lp\nf: x => y\nz = f(x)\n", encoding="utf-8")
        payload = resolve_sym_type.resolve_file(main)

    definition = occurrence_on_line(payload, "f", 2)["definition"]
    assert definition["file"] == str(main.resolve())
    assert definition["lineno"] == 1


def test_resolve_sym_type_invalid_source_returns_empty_success_payload() -> None:
    payload = resolve_sym_type.resolve_text("∀{| x | x = x")
    assert payload == {"summary": {"symbol_count": 0, "occurrence_count": 0}, "symbols": [], "occurrences": []}


def test_resolve_sym_type_cli_modes() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPTS_DIR / "resolve_sym_type.py"), "--text", "Function ~ f\ny = f(x)", "--pretty"],
        capture_output=True,
        text=True,
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 0
    assert resolved_symbol(json.loads(result.stdout), "f")["type"] == "func"

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        imported = root / "imported.lp"
        imported.write_text("Predicate ~ p\n", encoding="utf-8")
        main = root / "main.lp"
        main.write_text("$import imported.lp\np(x)\n", encoding="utf-8")
        file_result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "resolve_sym_type.py"), "--file", str(main)],
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
        assert file_result.returncode == 0
        file_payload = json.loads(file_result.stdout)
        assert resolved_symbol(file_payload, "p")["type"] == "pred"
        assert {entry["file"] for entry in file_payload["occurrences"]} == {str(main.resolve())}

        stdin_result = subprocess.run(
            [
                "python3",
                str(SCRIPTS_DIR / "resolve_sym_type.py"),
                "--filename",
                str(main),
                "--base-dir",
                str(root),
            ],
            input="$import imported.lp\np(x)\n",
            capture_output=True,
            text=True,
            cwd=SKILL_DIR,
            check=False,
        )
        assert stdin_result.returncode == 0
        assert resolved_symbol(json.loads(stdin_result.stdout), "p")["type"] == "pred"


def test_script_modules_import_without_cycles() -> None:
    modules = [
        "compile_module",
        "expand_module",
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
        "module_check",
        "resolve_sym_type",
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
        test_operator_symbol_can_be_inherited_as_value,
        test_missing_infix_support_round_trip,
        test_nested_equality_expressions,
        test_chained_and_precedence_infix_expressions,
        test_boolean_and_ordered_comparison_precedence,
        test_prefix_unary_expressions,
        test_lifted_resolver_equality_expression_compiles,
        test_operator_head_declaration_round_trip,
        test_slice_operator_identifier_sym_compiles_everywhere,
        test_slice_operator_declaration_and_call_compile,
        test_range_and_slice_surface_forms_lower_to_slice_operator,
        test_compound_slice_member_call_lowers_to_ordinary_call,
        test_class_coloncolon_top_level_function_declaration,
        test_class_block_expands_to_current_scope,
        test_class_field_shorthand_compiles,
        test_class_field_shorthand_uses_underscore_receiver_and_output_names,
        test_class_field_shorthand_desugars_in_premise_section,
        test_prime_suffix_names_compile_and_infer_from_base,
        test_class_method_body_is_preserved,
        test_function_declaration_and_body_are_separate_rules,
        test_repeated_function_bodies_are_conditional_facts,
        test_function_arrow_shorthand_is_invalid,
        test_inheritance_fact_does_not_declare_class_body,
        test_explicit_class_declaration_after_inheritance_fact,
        test_class_operator_suffix_declaration,
        test_class_coloncolon_requires_explicit_owner_declaration,
        test_bare_plain_symbol_targets_are_invalid_class_declarations,
        test_invalid_class_body_lines_fail,
        test_explicit_class_field_declaration_may_have_body,
        test_wrapper_predicates_lower_through_anf,
        test_capital_wrapper_predicates_normalize_to_infix,
        test_stage2_ancestor_scope_for_function_decl,
        test_stage2_capital_inheritance_when_visible,
        test_stage2_class_suffix_fallback_inheritance,
        test_stage2_function_output_inheritance_is_target,
        test_stage2_does_not_inject_implicit_stdlib_import,
        test_standard_library_supplies_universal_inheritance_axioms,
        test_stage2_generated_sym_does_not_re_desugar,
        test_stage2_authored_generated_sym_gets_no_implicit_facts,
        test_double_underscore_sym_is_ordinary,
        test_stage2_synthesized_infixes_are_spaced,
        test_stage2_omits_symbol_when_inheritance_premise_exists,
        test_stage2_legacy_unspaced_infix_still_compiles,
        test_import_file_locations,
        test_import_searches_skill_dir_for_standard_library,
        test_stage1_dedupes_transitive_imports,
        test_stage1_dedupes_direct_and_resolved_alias_imports,
        test_source_utils_expand_imports_dedupes_visible_context_imports,
        test_import_cycle_still_errors_with_dedup,
        test_module_check_dedupes_located_imports,
        test_stdin_import_rejected,
        test_multiline_bar_semantics,
        test_branch_header_lowers_to_target_module,
        test_sibling_branches_are_target_modules,
        test_premise_universal_block_contains_target_branch_modules,
        test_branch_requires_indented_block,
        test_branch_allows_function_output_in_nested_target,
        test_indentation_body_headers_are_validated,
        test_at_header_desugars_to_recursive_forall_block,
        test_indentation_body_rejects_invalid_owner_and_level_jump,
        test_target_nested_declaration_expands_in_function_body,
        test_premise_nested_declaration_expands_in_function_body,
        test_no_body_premise_declaration_expands_signature,
        test_bool_declarations_emit_predicate_fact,
        test_duplicate_binders_deduplicate,
        test_nested_ancestor_conflict_is_invalid,
        test_semantic_suppresses_multiple_inheritance_candidates_warning,
        test_semantic_warning_for_bare_index_operator_symbol,
        test_semantic_bare_index_operator_symbol_exempts_definitions,
        test_semantic_flags_undeclared_class_member_owner,
        test_semantic_flags_function_output_in_body_premise,
        test_semantic_flags_nested_function_output_in_body_premise,
        test_semantic_flags_predicate_output_in_body_premise,
        test_semantic_allows_function_output_in_target_and_generated_binding,
        test_semantic_nested_premise_declaration_output_rule,
        test_sibling_submodules_can_reuse_name,
        test_authored_caret_generated_sym_is_accepted,
        test_double_underscore_sym_is_not_generated,
        test_translate_omits_empty_binder_bar,
        test_translate_keeps_binder_line_when_present,
        test_nested_module_disassembly_is_indented,
        test_function_output_inheritance_disassembles_as_target,
        test_bound_syms_are_not_filtered_as_intrinsics,
        test_free_classifier_syms_are_not_auto_bound,
        test_function_output_inheritance_cases,
        test_is_prefixed_declared_syms_implicitly_inherit_bool,
        test_function_declaration_without_output_guarantee_omits_rule,
        test_tuple_function_declaration_call_and_destructure_are_premises,
        test_generated_tuple_function_declaration_keeps_tuple_guarantee,
        test_function_body_return_destructuring_omits_redundant_classifiers,
        test_function_body_local_literal_classifier_is_preserved,
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
        test_module_check_syntax_error_stops_before_semantic_and_compile,
        test_module_check_set_literals_are_not_set_modules,
        test_module_check_supports_set_union_infix_with_set_literal,
        test_module_check_set_module_syntax_still_reports_located_errors,
        test_module_check_warning_only_bare_index_operator_symbol_exits_clean,
        test_module_check_positioned_branch_error_avoids_file_start_fallback,
        test_module_check_positioned_unsupported_coloncolon_errors,
        test_module_check_class_field_assignment_succeeds,
        test_module_check_positioned_class_field_assignment_body_error,
        test_module_check_positioned_arrow_and_literal_errors,
        test_module_check_imported_located_syntax_error_uses_import_file,
        test_module_check_undeclared_class_member_owner_is_semantic_error,
        test_module_check_semantic_error_stops_before_compile,
        test_module_check_semantic_warning_continues_to_compile,
        test_module_check_compile_error_uses_entry_file_start,
        test_module_check_compile_error_uses_source_fragment_location,
        test_module_check_final_ast_diagnostics_keep_location_and_code,
        test_module_check_final_ast_plain_declaration_conflict_uses_input_location,
        test_module_check_final_ast_class_method_body_conflict_uses_declaration_location,
        test_module_check_text_import_resolves_standard_library_from_skill_dir,
        test_module_check_standard_library_is_clean,
        test_module_check_stdin_import_uses_base_dir,
        test_expand_module_cli_text_mode,
        test_expand_module_cli_file_mode,
        test_expand_module_cli_stdin_mode,
        test_expand_module_cli_invalid_input,
        test_normalize_module_declarations_groups_source_units,
        test_normalize_module_declarations_places_inheritance_before_member_bodies,
        test_normalize_module_declarations_unindents_multiline_logical_member_body,
        test_normalize_module_declarations_respects_nested_block_barriers,
        test_normalize_module_declarations_opaque_exists_and_declaration_bodies,
        test_normalize_module_declarations_cli_modes_and_imports,
        test_normalize_module_declarations_dedupes_transitive_imports,
        test_normalize_module_declarations_requires_explicit_class_members,
        test_normalize_module_declarations_cli_invalid_input,
        test_resolve_sym_type_class_func_pred_and_alias_evidence,
        test_resolve_sym_type_predicate_wins_over_function,
        test_resolve_sym_type_class_wins_over_callable_evidence,
        test_resolve_sym_type_operator_symbols_are_not_colorable,
        test_resolve_sym_type_definition_locations,
        test_resolve_sym_type_class_typed_pure_symbol_definition,
        test_resolve_sym_type_class_typed_pure_symbol_falls_back_to_fact,
        test_resolve_sym_type_class_typed_pure_symbol_beats_pure_intro,
        test_resolve_sym_type_untyped_pure_symbol_has_no_definition,
        test_resolve_sym_type_output_uses_generated_signature_class_evidence,
        test_resolve_sym_type_inputs_use_generated_signature_class_evidence,
        test_resolve_sym_type_signature_class_evidence_uses_numeric_suffixes,
        test_resolve_sym_type_class_suffix_fallback_definition,
        test_resolve_sym_type_generated_binder_class_evidence_defines_pure_symbol,
        test_resolve_sym_type_authored_premise_class_fact_does_not_define_pure_symbol,
        test_resolve_sym_type_authored_premise_class_fact_is_not_class_navigation_evidence,
        test_resolve_sym_type_imported_signature_class_definition,
        test_resolve_sym_type_target_equality_propagates_class_definition,
        test_resolve_sym_type_premise_equality_does_not_propagate_class_definition,
        test_resolve_sym_type_inheritance_fact_does_not_define_capital_class_name,
        test_resolve_sym_type_class_block_receiver_definition,
        test_resolve_sym_type_qualified_class_owner_receiver_definition,
        test_resolve_sym_type_imported_class_typed_definition,
        test_resolve_sym_type_class_typed_definition_uses_first_evidence,
        test_resolve_sym_type_function_and_predicate_use_declaration_heads,
        test_resolve_sym_type_member_call_uses_qualified_class_method_definition,
        test_resolve_sym_type_member_call_uses_indented_class_method_definition,
        test_resolve_sym_type_member_call_uses_bare_class_field_definition,
        test_resolve_sym_type_bare_class_field_in_premise_section_is_function,
        test_resolve_sym_type_member_call_falls_back_to_function_declaration,
        test_resolve_sym_type_imported_definition_locations,
        test_resolve_sym_type_definition_prefers_current_file,
        test_resolve_sym_type_invalid_source_returns_empty_success_payload,
        test_resolve_sym_type_cli_modes,
        test_script_modules_import_without_cycles,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
