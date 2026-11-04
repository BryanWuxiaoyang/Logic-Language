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
import resolve_sym_type
from AST import Call_expr, ClassDecl, ClassFieldDecl, ClassMethodDecl, Func_stmt, FunctionDecl, Inherit_stmt, Source_loc, Sym, Sym_expr
from compile_module import CompileError, run_compile_pipeline
from compile_pipeline.source_utils import expand_imports
from compile_pipeline.front_end_source_loader import run as run_stage1
from compile_pipeline.stage1_front_end import parse_front_end_ast, run as run_front_end
from compile_pipeline.front_end_desugar import run as run_stage2
from compile_pipeline.back_end_sections import run as run_stage3
from compile_pipeline.back_end_statements import run as run_stage4
from compile_pipeline.back_end_lower_object import run as run_stage5
from semantic_check import collect_semantic_diagnostics_from_text
from translate_AST_to_source import translate_ast_to_source
from front_end_AST_organizer import organize_module_text

SKILL_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = SKILL_DIR / "scripts"
FUNC_KINDS = {
    "Func_stmt",
    "Pred_stmt",
    "Eq_stmt",
    "Inherit_stmt",
    "And_stmt",
    "Or_stmt",
    "Not_stmt",
    "Implies_stmt",
    "Ne_stmt",
    "Gt_stmt",
    "Lt_stmt",
    "Ge_stmt",
    "Le_stmt",
    "In_stmt",
    "Notin_stmt",
    "Subset_stmt",
    "Notsubset_stmt",
    "Includedin_stmt",
    "Notincludedin_stmt",
}
SECTION_FIELD_ALIASES = {
    "premise_proposition_stmts": "premise_proposition_stmts",
    "target_proposition_stmts": "target_proposition_stmts",
}


def compile_text(text: str, *, base_dir: Path | str = ".", source: str = "__stdin__", allow_imports: bool = False) -> dict:
    return run_compile_pipeline(text, base_dir, source=source, allow_imports=allow_imports).ast


def stage2_text(text: str, base_dir: Path | str = ".", *, allow_imports: bool = False) -> str:
    return translate_ast_to_source(compile_text(text, base_dir=base_dir, allow_imports=allow_imports))


def stage2_result(text: str, base_dir: Path | str = ".", *, allow_imports: bool = False) -> object:
    return run_stage2(run_stage1(text, base_dir=base_dir, allow_imports=allow_imports), base_dir)


def statement_text(statement: object) -> str:
    expr = getattr(statement, "expr", None)
    if expr is None:
        return ""
    if isinstance(expr, Call_expr) and expr.call_sym is not None:
        args = []
        for arg in expr.args:
            if isinstance(arg, Sym_expr) and arg.sym is not None:
                args.append(arg.sym.name)
            else:
                args.append(arg.kind)
        if len(args) == 2 and expr.call_sym.name in {"~", "=", "∈", "≥", "≤", ">", "<"}:
            return f"{args[0]} {expr.call_sym.name} {args[1]}"
        return f"{expr.call_sym.name}(" + ", ".join(args) + ")"
    return expr.kind


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
    return [node for node in all_nodes(ast) if node.get("kind") in FUNC_KINDS and node.get("call_sym", {}).get("name") == name]


def bindings(ast: dict) -> list[dict]:
    return [node for node in all_nodes(ast) if node.get("kind") == "Binding_stmt"]


def target_bindings(ast: dict) -> list[dict]:
    return [node for node in ast.get("target_proposition_stmts", []) if node.get("kind") == "Binding_stmt"]


def top_level_calls(ast: dict, name: str, field: str) -> list[dict]:
    actual_field = SECTION_FIELD_ALIASES.get(field, field)
    return [node for node in ast.get(actual_field, []) if node.get("kind") in FUNC_KINDS and node.get("call_sym", {}).get("name") == name]


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
    assert "premise_proposition_stmts" in ast
    assert "target_proposition_stmts" in ast
    assert "source_loc" in ast


def assert_source_loc_invariant(node: object, path: str = "$") -> None:
    if isinstance(node, dict):
        if "kind" in node:
            assert "source_loc" in node, f"missing source_loc at {path}: {node}"
        if node.get("kind") == "Sym" and node.get("generated"):
            assert "source_name" in node, f"missing source_name at {path}: {node}"
        for key, value in node.items():
            assert_source_loc_invariant(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            assert_source_loc_invariant(item, f"{path}[{index}]")


def test_final_ast_source_loc_invariant_and_generated_source_name() -> None:
    ast = compile_text("∀{| _x | _x = 1}")
    assert_source_loc_invariant(ast)
    generated = [node for node in all_nodes(ast) if node.get("kind") == "Sym" and node.get("generated")]
    assert generated
    assert all(node.get("source_name") for node in generated)
    assert any(node["source_loc"]["column"] == 15 and node["source_loc"]["end_column"] == 16 for node in generated)


def test_ast_type_inheritance_uses_isinstance() -> None:
    loc = Source_loc("__test__", 1, 1, 1, 2)
    statement = Inherit_stmt(loc, Sym(loc, name="Class"), Sym(loc, name="_x"))
    assert isinstance(statement, Inherit_stmt)
    assert isinstance(statement, Func_stmt)
    assert statement.to_json()["kind"] == "Inherit_stmt"


def test_generated_declaration_fact_uses_declaration_head_loc() -> None:
    text = "Uav\n    ::is_oob: (_uav, _byte_id, _byte_size) => _bool"
    ast = compile_text(text, source="<sample>")
    function_fact = next(
        stmt
        for stmt in top_level_calls(ast, "~", "target_proposition_stmts")
        if stmt.get("call_sym", {}).get("name") == "~"
        and stmt["arg_sym_list"][0]["name"] == "Function"
        and stmt["arg_sym_list"][1]["name"] == "is_oob"
    )
    loc = function_fact["arg_sym_list"][1]["source_loc"]
    assert loc == {"file_path": "<sample>", "line": 2, "column": 7, "end_line": 2, "end_column": 13}


def test_generated_inheritance_fact_uses_inferred_binder_loc() -> None:
    text = "\n".join(
        [
            "Uav",
            "    ::is_oob: (_uav, _byte_id, _byte_size) => _bool",
            "    ::read: (_uav, _byte_id, _byte_size, _is_oob_check) => _val",
            "        | _is_oob = _uav.is_oob(_byte_id, _byte_size)",
            "        P(_is_oob)",
        ]
    )
    ast = compile_text(text, source="<sample>")
    bool_fact = next(
        stmt
        for stmt in calls(ast, "~")
        if stmt["arg_sym_list"][0]["name"] == "Bool" and stmt["arg_sym_list"][1]["name"] == "_is_oob"
    )
    assert bool_fact["arg_sym_list"][1]["source_loc"] == {
        "file_path": "<sample>",
        "line": 4,
        "column": 11,
        "end_line": 4,
        "end_column": 18,
    }


def test_simple_quantified() -> None:
    ast = compile_text("∀{| _x | _x = _x}")
    assert ast["kind"] == "Quantified_stmt"
    assert calls(ast, "=")
    assert_no_legacy_top_level(ast)


def test_set_module() -> None:
    ast = compile_text("{| _x | _x = _x}")
    assert ast["kind"] == "Set_stmt"
    assert calls(ast, "=")


def test_binding_call() -> None:
    ast = compile_text("∀{| _x, _y | _x = f(_y) | _y = _y}")
    assert any(binding["dst_sym"]["name"] == "_x" and binding["src_stmt"]["kind"] in FUNC_KINDS for binding in bindings(ast))


def test_target_call_assignment_normalized() -> None:
    ast = compile_text("∀{| _x, _y | _y = f(_x)}")
    assert not target_bindings(ast)
    assert any(binding["dst_sym"]["name"].startswith("^tmpf") for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_proposition_stmts")


def test_nested_call_anf() -> None:
    ast = compile_text("∀{| _x | P(f(_x))}")
    assert any(sym["name"].startswith("^tmpf") for sym in ast["bound_syms"])
    assert any(binding.get("generated") for binding in ast["premise_binding_stmts"])


def test_compound_lhs() -> None:
    ast = compile_text("∀{| _a, _b, _x | (_a, _b) = f(_x)}")
    assert not target_bindings(ast)
    target_eqs = top_level_calls(ast, "=", "target_proposition_stmts")
    assert len(target_eqs) == 2
    assert {stmt["arg_sym_list"][0]["name"] for stmt in target_eqs} == {"_a", "_b"}
    assert calls(ast, "[]")


def test_literals() -> None:
    for text, kind in [
        ("∀{| _x | _x = 'a'}", "Char_literal_stmt"),
        ("∀{| _x | _x = 1}", "Value_literal_stmt"),
        ("∀{| _x, _a, _b | _x = (_a, _b)}", "Tuple_literal_stmt"),
        ("∀{| _x, _a | _x = [_a]}", "Tuple_literal_stmt"),
        ("∀{| _x, _a, _b | _x = {_a, _b}}", "Set_literal_stmt"),
        ("∀{| _x | _x = {}}", "Set_literal_stmt"),
        ("∀{| _x | _x = [,]}", "Tuple_literal_stmt"),
    ]:
        ast = compile_text(text)
        assert any(node.get("kind") == kind for node in all_nodes(ast)), (text, kind)
    assert any(node.get("kind") == "Tuple_literal_stmt" and node.get("item_stmts") == [] for node in all_nodes(compile_text("_x = [,]")))
    assert any(node.get("kind") == "Tuple_literal_stmt" and len(node.get("item_stmts", [])) == 1 for node in all_nodes(compile_text("_x = [_a]")))
    assert any(node.get("kind") == "Set_literal_stmt" and node.get("item_stmts") == [] for node in all_nodes(compile_text("_x = {}")))
    assert any(node.get("kind") == "Sym" and node.get("name") == "[]" for node in all_nodes(compile_text("_x = []")))
    for text in ["P({})", "P({1, 2})", "P([,])", "P([_a])"]:
        compile_text(text)


def test_implicit_literal_classifier_predicates() -> None:
    cases = [
        ("∀{| _x | _x = 'a'}", "Char"),
        ('∀{| _x | _x = "ab"}', "String"),
        ("∀{| _x | _x = 1}", "Value"),
        ("∀{| _x, _a, _b | _x = (_a, _b)}", "Tuple"),
        ("∀{| _x, _a, _b | _x = {_a, _b}}", "Set"),
    ]
    for text, classifier in cases:
        ast = compile_text(text)
        premise_calls = top_level_calls(ast, "~", "premise_proposition_stmts")
        target_calls = top_level_calls(ast, "~", "target_proposition_stmts")
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
    ast = compile_text("∀{| _x | _x.size = 1}")
    assert calls(ast, "size")
    assert calls(ast, "=")


def test_operator_symbol_can_be_inherited_as_value() -> None:
    ast = compile_text("Predicate ~ ∈")
    inherit_calls = top_level_calls(ast, "~", "target_proposition_stmts")
    assert any(
        stmt["arg_sym_list"][0]["name"] == "Predicate" and stmt["arg_sym_list"][1]["name"] == "∈"
        for stmt in inherit_calls
    )


def test_missing_infix_support_round_trip() -> None:
    cases = [
        ("∀{| _x, _y, _z | _z = (_x + _y)}", "+", "+"),
        ("∀{| _x, _y, _z | _z = _x - _y}", "-", "-"),
        ("∀{| _x, _y, _z | _z = _x * _y}", "*", "*"),
        ("∀{| _x, _y, _z | _z = _x / _y}", "/", "/"),
        ("∀{| _x, _y, _z | _z = _x \\union _y}", "∪", "∪"),
        ("∀{| _x, _y, _z | _z = _x \\intersect _y}", "∩", "∩"),
        ("∀{| _x, _y, _z | _z = _x \\land _y}", "∧", "∧"),
        ("∀{| _x, _y, _z | _z = _x \\lor _y}", "∨", "∨"),
        ("∀{| _x, _y | _x && _y}", "&&", "&&"),
    ]
    for text, call_name, rendered in cases:
        ast = compile_text(text)
        assert calls(ast, call_name), (text, call_name)
        source = translate_ast_to_source(ast)
        assert rendered in source, (text, rendered, source)
        reparsed = compile_text(source)
        assert calls(reparsed, call_name), (text, source)


def test_nested_equality_expressions() -> None:
    member_source = translate_ast_to_source(compile_text("∀{| _bool, _eq_stmt, _sym1 | _bool = _eq_stmt.dst_sym = _sym1}"))
    assert "^tmpdst_sym0 = dst_sym(^_eq_stmt)" in member_source
    assert "^tmpeq1 = ^tmpdst_sym0 = ^_sym1" in member_source
    assert "^_bool = ^tmpeq1" in member_source

    grouped_ast = compile_text("∀{| _bool, _a, _b, _c, _d | _bool = (_a = _b) && (_c = _d)}")
    grouped_source = translate_ast_to_source(grouped_ast)
    assert "^tmpeq0 = ^_a = ^_b" in grouped_source
    assert "^tmpeq1 = ^_c = ^_d" in grouped_source
    assert top_level_calls(grouped_ast, "=", "target_proposition_stmts")

    precedence_source = translate_ast_to_source(compile_text("∀{| _bool, _a, _b, _c, _d | _bool = _a = _b && _c = _d}"))
    assert "^tmpand0 = ^_b && ^_c" in precedence_source
    assert "^tmpeq1 = ^tmpand0 = ^_d" in precedence_source
    assert "^tmpeq2 = ^_a = ^tmpeq1" in precedence_source


def test_chained_and_precedence_infix_expressions() -> None:
    union_source = translate_ast_to_source(compile_text("∀{| _stmts, _a, _b, _c | _stmts = _a \\union _b \\union _c}"))
    assert "^tmpunion0 = ∪(^_a, ^_b)" in union_source
    assert "^tmpunion1 = ∪(^tmpunion0, ^_c)" in union_source
    assert "^_stmts = ^tmpunion1" in union_source

    intersect_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b, _c | _x = _a \\intersect _b \\intersect _c}"))
    assert "^tmpintersect0 = ∩(^_a, ^_b)" in intersect_source
    assert "^tmpintersect1 = ∩(^tmpintersect0, ^_c)" in intersect_source

    arithmetic_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b, _c | _x = _a + _b * _c}"))
    assert "^tmpadd0 = ^_a + ^_b" in arithmetic_source
    assert "^tmpmul1 = ^tmpadd0 * ^_c" in arithmetic_source

    arithmetic_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b, _c | _x = _a * _b + _c}"))
    assert "^tmpmul0 = ^_a * ^_b" in arithmetic_source
    assert "^tmpadd1 = ^tmpmul0 + ^_c" in arithmetic_source

    subtraction_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b, _c | _x = _a - _b - _c}"))
    assert "^tmpsub0 = ^_a - ^_b" in subtraction_source
    assert "^tmpsub1 = ^tmpsub0 - ^_c" in subtraction_source

    division_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b, _c | _x = _a / _b / _c}"))
    assert "^tmpdiv0 = ^_a / ^_b" in division_source
    assert "^tmpdiv1 = ^tmpdiv0 / ^_c" in division_source


def test_modulo_operator() -> None:
    # Spaced and compact syntax must both produce a binary call, not a raw symbol.
    for expression in ("_a % _b", "_a%_b", "-_a % -_b", "_a % (_b + _c)"):
        ast = compile_text("∀{| _x, _a, _b, _c | _x = " + expression + "}")
        modulo_calls = calls(ast, "%")
        assert len(modulo_calls) == 1
        assert len(modulo_calls[0]["arg_sym_list"]) == 2
        source = translate_ast_to_source(ast)
        assert " % " in source
        assert calls(compile_text(source), "%")
        assert stage2_text(source) == source

    # Preserve the language's existing left-to-right arithmetic grouping.
    for expression, first, second in (
        ("_a % _b % _c", "^tmpmod0 = ^_a % ^_b", "^tmpmod1 = ^tmpmod0 % ^_c"),
        ("_a % _b * _c", "^tmpmod0 = ^_a % ^_b", "^tmpmul1 = ^tmpmod0 * ^_c"),
        ("_a / _b % _c", "^tmpdiv0 = ^_a / ^_b", "^tmpmod1 = ^tmpdiv0 % ^_c"),
        ("_a + _b % _c", "^tmpadd0 = ^_a + ^_b", "^tmpmod1 = ^tmpadd0 % ^_c"),
    ):
        source = stage2_text("∀{| _x, _a, _b, _c | _x = " + expression + "}")
        assert first in source
        assert second in source

    # Operator declarations and explicit function calls remain ordinary symbols.
    declaration = "%: (_val1, _val2) => _val\n    _val = %(_val1, _val2)"
    assert calls(compile_text(stage2_text(declaration)), "%")
    payload = resolve_sym_type.resolve_text(declaration + "\n_x = _a % _b")
    assert resolved_symbol(payload, "%")["type"] == "func"
    occurrences = resolved_occurrences(payload, "%")
    assert any(entry["lineno"] == 2 for entry in occurrences)
    assert all(not entry["colorable"] for entry in occurrences)


def test_boolean_and_ordered_comparison_precedence() -> None:
    land_source = translate_ast_to_source(compile_text("∀{| _bool, _a, _b, _c | _bool = _a \\land _b \\lor _c}"))
    assert "^tmpland0 = ∧(^_a, ^_b)" in land_source
    assert "^tmplor1 = ∨(^tmpland0, ^_c)" in land_source

    less_source = translate_ast_to_source(compile_text("∀{| _bool, _a, _b, _c | _bool = _a < _b < _c}"))
    assert "^tmplt0 = ^_a < ^_b" in less_source
    assert "^tmplt1 = ^tmplt0 < ^_c" in less_source

    mixed_less_source = translate_ast_to_source(compile_text("∀{| _bool, _a, _b, _c | _bool = _a < _b <= _c}"))
    assert "^tmplt0 = ^_a < ^_b" in mixed_less_source
    assert "^tmple1 = ^tmplt0 ≤ ^_c" in mixed_less_source

    equality_chain_source = translate_ast_to_source(compile_text("∀{| _bool, _a, _b, _c | _bool = _a = _b = _c}"))
    assert "^tmpeq0 = ^_b = ^_c" in equality_chain_source
    assert "^tmpeq1 = ^_a = ^tmpeq0" in equality_chain_source
    assert "^tmpand" not in equality_chain_source


def test_prefix_unary_expressions() -> None:
    not_quant_source = translate_ast_to_source(compile_text("∀{| _bool | _bool = !∀{| _x | P(_x)}}"))
    assert "^tmp00 = ∀{" in not_quant_source
    assert "^tmpnot1 = !(^tmp00)" in not_quant_source

    for text in [
        "∀{| _bool, _x | _bool = !P(_x)}",
        "∀{| _bool, _x | _bool = ! P(_x)}",
        "∀{| _bool, _x | _bool = \\lnot P(_x)}",
    ]:
        ast = compile_text(text)
        source = translate_ast_to_source(ast)
        assert "^tmpP0 = P(^_x)" in source
        assert "^tmpnot1 = !(^tmpP0)" in source
        assert not calls(ast, "!P")

    unary_left_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b | _x = -_a * _b}"))
    assert "^tmpsub0 = -(^_a)" in unary_left_source
    assert "^tmpmul1 = ^tmpsub0 * ^_b" in unary_left_source

    unary_right_source = translate_ast_to_source(compile_text("∀{| _x, _a, _b | _x = _a * -_b}"))
    assert "^tmpsub0 = -(^_b)" in unary_right_source
    assert "^tmpmul1 = ^_a * ^tmpsub0" in unary_right_source

    for text in ["∀{| _x, _set | _x = *_set}", "∀{| _x, _set | _x = * _set}"]:
        assert "^tmpmul0 = *(^_set)" in translate_ast_to_source(compile_text(text))

    regressions_source = translate_ast_to_source(compile_text("∀{| _bool, _x, _y, _a, _b | _bool = _a != _b, _x = _a - _b, _y = _a * _b}"))
    assert "^tmpneq0 = ^_a ≠ ^_b" in regressions_source
    assert "^tmpsub1 = ^_a - ^_b" in regressions_source
    assert "^tmpmul2 = ^_a * ^_b" in regressions_source

    bare_source = translate_ast_to_source(compile_text("∀{| _x, _y, _z | _x = !, _y = -, _z = *}"))
    assert "^_x = !" in bare_source
    assert "^_y = -" in bare_source
    assert "^_z = *" in bare_source


def test_lifted_resolver_equality_expression_compiles() -> None:
    text = """Stmt
Stmt::has_direct_sym_alias: (_stmt, _sym1, _sym2) => _bool
    _bool = ∃{
        | _eq_stmt
        | _eq_stmt ∈ _stmt.all_stmts
        | Eq_stmt ~ _eq_stmt
        (_eq_stmt.dst_sym = _sym1 && _eq_stmt.src_sym = _sym2) \\lor (_eq_stmt.src_sym = _sym1 && _eq_stmt.dst_sym = _sym2)
    }"""
    ast = compile_text(text)
    assert calls(ast, "=")
    assert calls(ast, "&&")
    assert calls(ast, "∨")


def test_operator_head_declaration_round_trip() -> None:
    text = "+: (_list, _list1) => _list2\n    _list2 = _list"
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
    ast = compile_text("∀{| [] | [] = _x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["[]"]
    assert compile_text("Function ~ []")


def test_slice_operator_declaration_and_call_compile() -> None:
    ast = compile_text("[:]: (_val1, _val2) => _list\n    _list = [:](_val1, _val2)")
    assert calls(ast, "[:]")
    assert any(
        stmt["call_sym"]["name"] == "~" and stmt["arg_sym_list"][1]["name"] == "[:]"
        for stmt in ast["target_proposition_stmts"]
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
    source = translate_ast_to_source(compile_text("Val\nClass\nClass::func: (_val1, _val2) => (_val3, _val4)"))
    assert "Class::func" not in source
    assert "Function ~ func" in source
    assert "func(^_val1, ^_val2)" in source
    assert "| Val ~ ^_val1" in source
    assert "| Val ~ ^_val2" in source
    assert "\n    Tuple ~ ^tmpfunc0\n" in source
    assert "\n    | Tuple ~ ^tmpfunc0\n" not in source
    assert "\n    Val ~ ^_val3\n" in source
    assert "\n    Val ~ ^_val4\n" in source


def test_class_block_expands_to_current_scope() -> None:
    source = translate_ast_to_source(compile_text("Class\n    ::field\n    ::func: (_val1, _val2) => (_val3, _val4)"))
    assert "Class::" not in source
    assert "\n  | ^Class\n" not in source
    assert "Function ~ field" in source
    assert "field(^_class)" in source
    assert "| Class ~ ^_class" in source
    assert "Symbol ~ ^_field" in source
    assert "Function ~ func" in source
    assert "func(^_val1, ^_val2)" in source


def test_class_field_shorthand_compiles() -> None:
    source = translate_ast_to_source(compile_text("Class\nClass::field"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "field(^_class)" in source
    assert "Class ~ ^_class" in source
    assert "Symbol ~ ^_field" in source
    assert "^_field = field(^_class)" in source


def test_class_field_shorthand_uses_underscore_receiver_and_output_names() -> None:
    source = translate_ast_to_source(compile_text("Class\nClass::field"))
    assert "| ^_class, ^_field" in source
    assert "Symbol ~ ^_field" in source
    assert "^_field = field(^_class)" in source


def test_class_field_shorthand_desugars_in_premise_section() -> None:
    source = translate_ast_to_source(compile_text("Graph\nGraph~A\nA\n    ::field\nB\nB~b\n"))
    assert "Function ~ field" in source
    assert "field(^_a)" in source
    assert "A ~ ^_a" in source
    assert "Symbol ~ ^_field" in source


def test_class_field_assignment_lowers_to_field_declaration_and_axiom() -> None:
    source = translate_ast_to_source(compile_text("Value\nField\nClass\nValue ~ value\nClass\n    ::field = value"))
    assert "Function ~ field" in source
    assert "^_field = field(^_class)" in source
    assert "Class ~ ^_class" in source
    assert "^tmpfunc_stmt0 = field(^_class)" in source
    assert "^tmpfunc_stmt0 = value" in source


def test_class_field_assignment_premise_lowers_to_premise_artifacts() -> None:
    source = translate_ast_to_source(compile_text("Class\n| Class::field = value"))
    assert "| Function ~ field" in source
    assert "| ∀{" in source
    assert "^tmpfunc_stmt0 = field(^_class)" in source
    assert "^tmpfunc_stmt0 = value" in source


def test_prime_suffix_names_compile_and_infer_from_base() -> None:
    source = translate_ast_to_source(compile_text("List\n∀{| _list', _x'', _y | _y = _list'}"))
    assert "\n    | ^_list', ^_x'', ^_y\n" in source
    assert "| List ~ ^_list'" in source
    assert "invalid_bound_sym_name" not in source
    assert "^_y = ^_list'" in source


def test_class_method_body_is_preserved() -> None:
    source = translate_ast_to_source(compile_text("Class\n    ::func: _x => _y\n        _y = _x"))
    assert "Class::func" not in source
    assert "Function ~ func" in source
    assert "\n    | ^_y = func(^_x)\n" in source
    assert "\n    ^_y = ^_x\n" in source


def test_function_declaration_and_body_are_separate_rules() -> None:
    text = "Val\nClass\nClass::func: (_val1, _val2) => (_val3, _val4)\n    | _val1 = _val2\n    P(_val3)"
    desugared = stage2_text(text, SKILL_DIR)
    assert desugared.count("∀{") == 3
    assert desugared.count("Val ~ ^_val3") == 1
    assert desugared.count("Val ~ ^_val4") == 1
    assert "^_val3 = ^tmpfunc0[^tmpvalue1]" in desugared
    assert "| ^_val1 = ^_val2" in desugared
    assert "P(^_val3)" in desugared

    declaration_index = desugared.index("Val ~ ^_val3")
    body_index = desugared.index("| ^_val1 = ^_val2")
    assert declaration_index < body_index


def test_repeated_function_bodies_are_conditional_facts() -> None:
    text = "f: _input => _output\n    | _input = 1\n    P(_output)\n\nf: _input => _output\n    | _input = 2\n    Q(_output)"
    source = translate_ast_to_source(compile_text(text, base_dir=SKILL_DIR))
    assert source.count("| ^_input = 1") == 1
    assert source.count("| ^_input = 2") == 1
    assert source.count("P(^_output)") == 1
    assert source.count("Q(^_output)") == 1
    assert source.count("Symbol ~ ^_output") == 2


def test_function_arrow_shorthand_is_invalid() -> None:
    try:
        compile_text("f: _x -> g(_x)", base_dir=SKILL_DIR)
    except CompileError as error:
        assert "function-assign '->' is not supported" in str(error)
        return
    raise AssertionError("expected function-assign shorthand to fail")


def test_inheritance_fact_does_not_declare_class_body() -> None:
    try:
        compile_text("A ~ B\n    ::func: _b => _out")
    except CompileError as error:
        assert (
            "class-declaration body line must start with '::'" in str(error)
            or "unsupported '::' usage" in str(error)
            or "indentation body is only allowed after quantifier, branch, declaration, or class declaration" in str(error)
        )
        return
    raise AssertionError("A ~ B with an indented :: body should require an explicit B declaration")


def test_explicit_class_declaration_after_inheritance_fact() -> None:
    source = translate_ast_to_source(compile_text("B\n    ::func: _b => _out\nA ~ B"))
    assert "\n  | ^B\n" not in source
    assert "\n  A ~ B\n" in source
    assert "Function ~ func" in source
    assert "\n    | B ~ ^_b\n" in source


def test_class_operator_suffix_declaration() -> None:
    source = translate_ast_to_source(compile_text("List\nList::[]: (_list, _id) => _sym"))
    assert "List::[]" not in source
    assert "Function ~ []" in source
    assert "^_list[^_id]" in source


def test_class_coloncolon_requires_explicit_owner_declaration() -> None:
    for text in ["Class::func: _class => _out", "A ~ Class\nClass::func: _class => _out", "Class::field"]:
        payload = module_check.check_module(text, "<stdin>", SKILL_DIR, is_file=False)
        assert payload["summary"]["error_count"] == 1, text
        assert payload["entries"][0]["code"] == "undeclared_class_member_owner", text

    for text in ["Class\nOut\nClass::func: _class => _out", "Class\nField\nClass::field", "Class::func: _class => _out\nClass\nOut"]:
        payload = module_check.check_module(text, "<stdin>", SKILL_DIR, is_file=False)
        assert payload["summary"]["error_count"] == 0, text
        assert payload["summary"]["warning_count"] == 0, text


def test_bare_plain_symbol_targets_are_invalid_class_declarations() -> None:
    payload = module_check.check_module("Class\n    _sym", "<stdin>", SKILL_DIR, is_file=False)
    assert payload["summary"]["error_count"] == 1
    assert payload["summary"]["warning_count"] == 0
    assert payload["entries"][0]["code"] == "syntax_error"
    assert payload["entries"][0]["reason"] == "class-declaration body line must start with '::'"


def test_invalid_class_body_lines_fail() -> None:
    cases = [
        "Class\n    P(class)",
        "Class\n    : (class, x) => y",
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
    source = translate_ast_to_source(compile_text("Class\nClass::field: _class => _field'\n    P(_field')"))
    assert "Class::field" not in source
    assert "Function ~ field" in source
    assert "\n    P(^_field')\n" in source


def test_wrapper_predicates_lower_through_anf() -> None:
    cases = [
        ("∀{| _a, _b | Tuple ~ (_a, _b)}", "Tuple_literal_stmt", "Tuple"),
        ("∀{| _a, _b | Set ~ {_a, _b}}", "Set_literal_stmt", "Set"),
        ("∀{| _a | Value ~ 1}", "Value_literal_stmt", "Value"),
    ]
    for text, literal_kind, classifier in cases:
        ast = compile_text(text)
        assert any(binding["src_stmt"]["kind"] == literal_kind for binding in ast["premise_binding_stmts"]), (text, literal_kind)
        target_calls = top_level_calls(ast, "~", "target_proposition_stmts")
        assert len(target_calls) == 1, (text, target_calls)
        assert target_calls[0]["arg_sym_list"][0]["name"] == classifier, (text, classifier)
        assert target_calls[0]["arg_sym_list"][1]["generated"], text
        premise_calls = top_level_calls(ast, "~", "premise_proposition_stmts")
        assert not any(
            stmt["arg_sym_list"][0]["name"] == classifier and stmt["arg_sym_list"][1]["name"] == target_calls[0]["arg_sym_list"][1]["name"]
            for stmt in premise_calls
        ), text


def test_capital_wrapper_predicates_normalize_to_infix() -> None:
    cases = [
        ("∀{| _a, _b | Tuple~(_a, _b)}", "Tuple ~ ^tmp"),
        ("∀{| _a, _b | Set~{_a, _b}}", "Set ~ ^tmp"),
        ("∀{| _a | Value~1}", "Value ~ ^tmp"),
    ]
    for text, rendered_prefix in cases:
        desugared = stage2_text(text, ".")
        assert rendered_prefix in desugared, (text, desugared)
        assert "Tuple~" not in desugared and "Set~" not in desugared and "Value~" not in desugared, (text, desugared)
        ast = compile_text(text)
        assert top_level_calls(ast, "~", "target_proposition_stmts"), text


def test_stage2_ancestor_scope_for_function_decl() -> None:
    text = "-: (_list, _list1) => _list2\n    _list2.size = (_list.size + _list1.size)"
    desugared = stage2_text(text, ".")
    assert "| ^_list, ^_list1, ^_list2" in desugared
    assert "| list ~ ^_list1" not in desugared
    assert "| Symbol ~ ^_list" in desugared
    assert "| ^_list ~ ^_list" not in desugared
    assert "| List ~ ^_list" not in desugared
    assert "tuple~(__list, __list1)" not in desugared
    assert "tuple ~ (^_list, ^_list1)" not in desugared
    assert "__list1" not in desugared


def test_stage2_capital_inheritance_when_visible() -> None:
    desugared = stage2_text("$import standard_library.lp\n∀{| _list1 | _list1 = _list1}", SKILL_DIR, allow_imports=True)
    assert "| Symbol ~ ^_list1" not in desugared
    assert "| List ~ ^_list1" in desugared
    assert "| sym ~ ^_list1" not in desugared
    assert "| list ~ ^_list1" not in desugared


def test_stage2_class_suffix_fallback_inheritance() -> None:
    desugared = stage2_text("Chip_mem\nf: _chip_mem_class => _out", ".")
    assert "| Chip_mem ~ ^_chip_mem_class" in desugared
    assert "| Symbol ~ ^_chip_mem_class" not in desugared

    primary_desugared = stage2_text("Chip_mem_class\nChip_mem\nf: _chip_mem_class => _out", ".")
    assert "| Chip_mem_class ~ ^_chip_mem_class" in primary_desugared
    assert "| Chip_mem ~ ^_chip_mem_class" not in primary_desugared

    numeric_desugared = stage2_text("Chip_mem\nf: _chip_mem_class1 => _out", ".")
    assert "| Chip_mem ~ ^_chip_mem_class1" in numeric_desugared
    assert "| Symbol ~ ^_chip_mem_class1" not in numeric_desugared

    diagnostics = collect_semantic_diagnostics_from_text("f: _chip_mem_class => _out")
    assert any(entry["code"] == "implicit_inheritance_fallback_symbol" for entry in diagnostics)


def test_stage2_function_output_inheritance_is_target() -> None:
    text = "List\n-: (_list, _list1) => _list2\n    _list2.size = (_list.size + _list1.size)"
    desugared = stage2_text(text, SKILL_DIR)
    assert "\n    | List\n" not in desugared
    assert "\n    | Symbol ~ List\n" not in desugared
    assert "\n  Symbol ~ List\n" in desugared
    assert "| List ~ ^_list" in desugared
    assert "| List ~ ^_list1" in desugared
    assert "| List ~ ^_list2" not in desugared
    assert "\n    List ~ ^_list2\n" in desugared


def test_stage2_declared_class_symbol_fact_is_deduped() -> None:
    desugared = stage2_text("List\nList", SKILL_DIR)
    assert desugared.count("\n  Symbol ~ List\n") == 1
    assert "\n    | List\n" not in desugared


def test_stage2_does_not_inject_implicit_stdlib_import() -> None:
    desugared = stage2_text("∀{| _x | _x = _x}", ".")
    assert "$import standard_library.lp" not in desugared


def test_standard_library_supplies_universal_inheritance_axioms() -> None:
    stdlib = (SKILL_DIR / "standard_library.lp").read_text(encoding="utf-8")
    assert "^sym ~ ^sym" in stdlib
    assert "Symbol ~ ^sym" in stdlib


def test_stage2_generated_sym_does_not_re_desugar() -> None:
    source = "$import standard_library.lp\n∀{\n    | ^list\n    | list ~ ^list\n    | ^list ~ ^list\n    ^list = ^list\n}\n"
    desugared = stage2_text(source, SKILL_DIR, allow_imports=True)
    assert "| Symbol ~ ^list" not in desugared
    assert desugared.count("| list ~ ^list") == 1
    assert desugared.count("| ^list ~ ^list") == 1


def test_stage2_authored_generated_sym_gets_no_implicit_facts() -> None:
    desugared = stage2_text("∀{| ^x | ^x = ^x}", ".")
    assert "| ^x" in desugared
    assert "| Symbol ~ ^x" not in desugared
    assert "| ^x ~ ^x" not in desugared


def test_double_underscore_sym_is_ordinary() -> None:
    desugared = stage2_text("∀{| __x | __x = __x}", ".")
    assert "| Symbol ~ ^__x" in desugared


def test_stage2_synthesized_infixes_are_spaced() -> None:
    desugared = stage2_text("∀{| _x | _x = _x}", ".")
    assert "| Symbol ~ ^_x" in desugared
    assert "| ^_x ~ ^_x" not in desugared
    assert "| Symbol~_x" not in desugared
    assert "| _x~_x" not in desugared


def test_stage2_attaches_authoritative_desugared_module() -> None:
    result = stage2_result("f: _is_val => _sym\n    TS", ".")
    module = result.ast.modules[0].lowered_module
    assert module is not None
    assert run_stage3(result.ast).module is module
    signature_module = module.target_statements[1].sub_modules[0]
    assert "Bool ~ _is_val" in [statement_text(statement) for statement in signature_module.predicate_statements]
    assert "Symbol ~ _sym" in [statement_text(statement) for statement in signature_module.target_statements]


def test_stage1_parse_ast_preserves_class_and_function_decls() -> None:
    source = "Val\nClass\n    ::field\n    ::func: (_class, _val) => _out\n        | P(_class)\n        Q(_out)\n"
    parsed = parse_front_end_ast(source, ".", allow_imports=False)
    module = parsed.modules[0]

    assert module.lowered_module is None
    assert [(class_decl.name.name, [type(member).__name__ for member in class_decl.members]) for class_decl in module.classes] == [
        ("Val", []),
        ("Class", ["ClassFieldDecl", "ClassMethodDecl"]),
    ]
    method = module.classes[1].members[1]
    assert isinstance(method, ClassMethodDecl)
    assert method.decl.owner is not None and method.decl.owner.name == "Class"
    assert method.decl.body_premise_proposition_stmts
    assert method.decl.body_target_proposition_stmts


def test_stage1_run_exposes_parse_desugar_and_lowered_ast() -> None:
    result = run_front_end("Class\nClass::field", ".", allow_imports=False)
    assert result.parse_ast.modules[0].lowered_module is None
    assert result.desugar_ast.modules[0].lowered_module is None
    assert result.ast.modules[0].lowered_module is not None


def test_front_end_ast_organizer_groups_source_structure() -> None:
    source = "Val\nClass::b: _class => _b\nClass\nClass::a: _class => _a\ng: _x => _y\nf: _x => _y\ng: _z => _w\n"
    organized = organize_module_text(source, ".", allow_imports=False)
    assert "Class\n    ::b: _class => _b\n    ::a: _class => _a" in organized
    assert organized.index("g: _x => _y") < organized.index("g: _z => _w") < organized.index("f: _x => _y")
    assert compile_text(source) == compile_text(organized)


def test_compile_stages_are_ast_only_and_no_render_fallbacks() -> None:
    front_end_desugar_module = importlib.import_module("compile_pipeline.front_end_desugar")
    module_parser_module = importlib.import_module("compile_pipeline.module_parser")
    back_end_sections_module = importlib.import_module("compile_pipeline.back_end_sections")
    back_end_statements_module = importlib.import_module("compile_pipeline.back_end_statements")
    back_end_lower_object_module = importlib.import_module("compile_pipeline.back_end_lower_object")

    for removed in ["render_source_ast", "render_statement", "render_module_key", "desugar_module_text", "canonical_statement_key"]:
        assert not hasattr(front_end_desugar_module, removed), removed
    for removed in ["parse_located_module_text", "check_module_to_module", "synthetic_marker_statement"]:
        assert not hasattr(module_parser_module, removed), removed
    for removed_module in [
        "syntax_check_common",
        "compile_pipeline.typed_module_parser",
        "compile_pipeline.declaration_locations",
        "compile_pipeline.expr_parser",
        "compile_pipeline.located_text",
        "compile_pipeline.module_sections",
        "compile_pipeline._legacy_stage1_normalize_source",
        "compile_pipeline._legacy_stage2_desugar_module_text",
        "compile_pipeline._legacy_stage3_parse_module_sections",
        "compile_pipeline._legacy_stage4_parse_statements",
        "compile_pipeline._legacy_stage5_lower_to_module_ast",
        "normalize_module_declarations",
    ]:
        try:
            importlib.import_module(removed_module)
        except ModuleNotFoundError:
            pass
        else:
            raise AssertionError(f"legacy module is still importable: {removed_module}")
    for stage_module in [front_end_desugar_module, back_end_sections_module, back_end_statements_module, back_end_lower_object_module]:
        assert not hasattr(stage_module, "main")

    for call in [
        lambda: run_stage2("∀{| _x | _x = _x}", "."),
        lambda: run_stage3("∀{| _x | _x = _x}"),
        lambda: run_stage4(run_stage1("∀{| _x | _x = _x}")),
        lambda: run_stage5("∀{| _x | _x = _x}"),
    ]:
        try:
            call()
        except CompileError:
            continue
        raise AssertionError("stage accepted raw or wrong typed input")

    source_ast = run_stage1("∀{| _x | _x = _x}")
    module = source_ast.modules[0].lowered_module
    assert not hasattr(source_ast.modules[0], "text")
    assert module is not None and not hasattr(module.target_statements[0], "text")
    assert module.target_statements[0].expr is not None and not hasattr(module.target_statements[0].expr, "text")


def test_stage2_structural_collection_inheritance_module() -> None:
    result = stage2_result("Reg\nF: _regs => _out", ".")
    signature_statement = next(statement for statement in result.ast.modules[0].lowered_module.target_statements if statement.sub_modules)
    signature_module = signature_statement.sub_modules[0]
    premise_texts = [statement_text(statement) for statement in signature_module.predicate_statements]
    collection_stmt = next(statement for statement in signature_module.predicate_statements if statement.sub_modules)
    item_module = collection_stmt.sub_modules[0]
    assert "Set ~ _regs" in premise_texts
    assert item_module.syms == ["_regs_item"]
    assert [statement_text(statement) for statement in item_module.predicate_statements] == ["_regs_item ∈ _regs"]
    assert [statement_text(statement) for statement in item_module.target_statements] == ["Reg ~ _regs_item"]


def test_stage2_target_only_does_not_infer_bound_sym() -> None:
    module = stage2_result("_x = y", ".").ast.modules[0].lowered_module
    assert module.syms == []
    assert module.predicate_statements == []
    assert [statement_text(statement) for statement in module.target_statements] == ["_x = y"]


def test_stage2_omits_symbol_when_inheritance_premise_exists() -> None:
    desugared = stage2_text("∀{| _x | Value ~ _x | _x = _x}", ".")
    assert "| Value ~ ^_x" in desugared
    assert "| Symbol ~ ^_x" not in desugared


def test_stage2_permissive_unspaced_infix_still_compiles() -> None:
    ast = compile_text("∀{| _x | Symbol~_x}")
    assert top_level_calls(ast, "~", "target_proposition_stmts")


def test_import_file_locations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        imported = root / "imported.lp"
        main = root / "main.lp"
        imported.write_text("∀{| _x | _x = _x}\n", encoding="utf-8")
        main.write_text("$import imported.lp\n", encoding="utf-8")
        ast = compile_text(main.read_text(encoding="utf-8"), base_dir=root, source=str(main), allow_imports=True)
        assert ast["source_loc"]["file_path"] == str(imported.resolve())
        assert calls(ast, "=")


def test_import_searches_skill_dir_for_standard_library() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        normalized = run_stage1(
            "$import standard_library.lp\n∀{| _x | _x = _x}",
            base_dir=root,
            source=str(root / "main.lp"),
            allow_imports=True,
        )
        assert normalized.import_count == 1
        module = normalized.modules[0].lowered_module
        assert module is not None
        assert "Symbol" in module.declared_classes
        assert any(
            submodule.syms == ["_x"]
            and any(statement_text(statement) == "_x = _x" for statement in submodule.target_statements)
            for statement in module.target_statements
            for submodule in statement.sub_modules
        )


def test_stage1_dedupes_transitive_imports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared.lp").write_text("Shared\n", encoding="utf-8")
        (root / "a.lp").write_text("$import shared.lp\nA\n", encoding="utf-8")
        (root / "b.lp").write_text("$import shared.lp\nB\n", encoding="utf-8")
        source = "$import a.lp\n$import b.lp\nMain\n"
        normalized = run_stage1(source, base_dir=root, source=str(root / "main.lp"), allow_imports=True)

    assert normalized.import_count == 3
    assert normalized.modules[0].lowered_module is not None
    assert normalized.modules[0].lowered_module.declared_classes == ["Shared", "A", "B", "Main"]


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
    assert normalized.modules[0].lowered_module is not None
    assert normalized.modules[0].lowered_module.declared_classes == ["Shared"]


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
    ast = compile_text("∀{\n| _x\n| _x ~ _x\n_x = _x\n}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["_x"]
    assert top_level_calls(ast, "~", "premise_proposition_stmts")
    assert top_level_calls(ast, "=", "target_proposition_stmts")


def test_branch_header_lowers_to_target_module() -> None:
    source = "| _x\n|- P(_x)\n    _y = _x\n_z = _z"
    desugared = stage2_text(source, ".")
    assert "| - P(_x)" not in desugared
    ast = compile_text(source)
    branch_modules = [node for node in ast["target_proposition_stmts"] if node.get("kind") == "Quantified_stmt"]
    assert len(branch_modules) == 1
    branch = branch_modules[0]
    assert not branch["bound_syms"]
    assert top_level_calls(branch, "P", "premise_proposition_stmts")
    assert top_level_calls(branch, "=", "target_proposition_stmts")
    assert top_level_calls(ast, "=", "target_proposition_stmts")
    assert not any(node.get("name") == "__compiler_branch_module" for node in all_nodes(ast))


def test_sibling_branches_are_target_modules() -> None:
    ast = compile_text("| _x\n|- P(_x)\n    _y = _x\n|- Q(_x)\n    _y = _x\n_z = _z")
    branch_modules = [node for node in ast["target_proposition_stmts"] if node.get("kind") == "Quantified_stmt"]
    assert len(branch_modules) == 2
    assert top_level_calls(branch_modules[0], "P", "premise_proposition_stmts")
    assert top_level_calls(branch_modules[1], "Q", "premise_proposition_stmts")
    assert top_level_calls(ast, "=", "target_proposition_stmts")


def test_premise_universal_block_contains_target_branch_modules() -> None:
    source = "| _x\n| \\all\n    |- P(_x)\n        _y = _x\n_z = _z"
    expanded = translate_ast_to_source(compile_text(source))
    assert "^∀" not in expanded
    premise_modules = [node for node in compile_text(source)["premise_proposition_stmts"] if node.get("kind") == "Quantified_stmt"]
    assert len(premise_modules) == 1
    branch_modules = [node for node in premise_modules[0]["target_proposition_stmts"] if node.get("kind") == "Quantified_stmt"]
    assert len(branch_modules) == 1
    assert top_level_calls(branch_modules[0], "P", "premise_proposition_stmts")


def test_branch_requires_indented_block() -> None:
    payload = module_check.check_module("| _x\n|- P(_x)\n_z = _z", module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "syntax"
    assert entry["code"] == "syntax_error"
    assert entry["reason"] == "branch header requires an indented block"


def test_branch_allows_function_output_in_nested_target() -> None:
    payload = module_check.check_module("f: _x => _y\n    |- P(_x)\n        _y = 1", module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 0
    assert not any(entry["code"] == "function_output_in_premise" for entry in payload["entries"])


def test_indentation_body_headers_are_validated() -> None:
    valid_sources = [
        "∀\n    | _x\n    P(_x)",
        "∃\n    | _x\n    P(_x)",
        "@\n    | _x\n    P(_x)",
        "| _x\n| ∀\n    P(_x)\n_z = _z",
        "| _x\n| ∃\n    | _y\n    P(_y)\n_z = _z",
        "| _x\n|- P(_x)\n    Q(_x)\n_z = _z",
        "f: _x => _y\n    _y = _x",
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
                "    f: _x => _y",
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
    source = translate_ast_to_source(compile_text("f: _x => _y\n    g: _a => _b\n        P(_b)\n    _y = g(_x)", base_dir=SKILL_DIR))
    assert "\n    Function ~ g\n" in source
    assert "\n      | ^_b = g(^_a)\n" in source
    assert "\n      P(^_b)\n" in source
    assert "unsupported expression: |" not in source


def test_premise_nested_declaration_expands_in_function_body() -> None:
    payload = module_check.check_module(
        "f: _func => _y\n    | g: _a => _b\n        P(_b)\n    P(_func)",
        module_check.STDIN_FILE,
        Path("."),
        is_file=False,
    )
    assert payload["summary"]["error_count"] == 0
    assert all(entry["code"] != "naming_error" for entry in payload["entries"])


def test_no_body_premise_declaration_expands_signature() -> None:
    payload = module_check.check_module(
        "f: _x => _y\n    | g: _a => _b\n    _y = _x",
        module_check.STDIN_FILE,
        Path("."),
        is_file=False,
    )
    assert payload["summary"]["error_count"] == 0
    assert all(entry["code"] != "naming_error" for entry in payload["entries"])


def test_bool_declarations_emit_predicate_fact() -> None:
    source = translate_ast_to_source(compile_text("p: _x => _is_valid\n    p(_x)", base_dir=SKILL_DIR))
    assert "\n  Function ~ p\n" in source
    assert "\n    Bool ~ ^_is_valid\n" in source

    payload = module_check.check_module(
        "f: _x => _y\n    | p: _a => _is_valid\n    _y = _x",
        module_check.STDIN_FILE,
        Path("."),
        is_file=False,
    )
    assert payload["summary"]["error_count"] == 0
    assert all(entry["code"] != "naming_error" for entry in payload["entries"])


def test_duplicate_binders_deduplicate() -> None:
    ast = compile_text("∀{| _x, _x | _x = _x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["_x"]


def test_nested_ancestor_conflict_is_invalid() -> None:
    desugared = stage2_result("∀{| _x | ∀{| _x | _x = _x}}", ".")
    nested = desugared.ast.modules[0].lowered_module.target_statements[0].sub_modules[0]
    assert nested.syms == ["_x"]
    try:
        compile_text("∀{| _x | ∀{| _x | _x = _x}}")
    except CompileError as error:
        assert "bound_sym_name_conflict" in str(error)
    else:
        raise AssertionError("ancestor bound-sym conflict should fail final AST validation")


def test_semantic_suppresses_multiple_inheritance_candidates_warning() -> None:
    diagnostics = collect_semantic_diagnostics_from_text("Max_head_val\nHead_val\nVal\n∀{| max_head_val1 | max_head_val1 = max_head_val1}")
    assert not any(entry["code"] == "implicit_inheritance_candidates" for entry in diagnostics)


def test_semantic_warning_for_bare_index_operator_symbol() -> None:
    for text in ["sym = []", "P([])", "∀{| [] | [] = _x}"]:
        diagnostics = collect_semantic_diagnostics_from_text(text)
        assert any(entry["code"] == "bare_index_operator_symbol" and entry["type"] == "warning" for entry in diagnostics), text


def test_semantic_set_premise_warnings() -> None:
    source = "{| _x | _x ∈ xs | _v = f(_x) => _v}"
    diagnostics = collect_semantic_diagnostics_from_text(source)
    warnings = [entry for entry in diagnostics if entry["code"] == "set_stmt_premise"]
    assert len(warnings) == 2
    assert all(entry["type"] == "warning" for entry in warnings)
    diagnostics = collect_semantic_diagnostics_from_text("{| _x => f(_x)}")
    assert not any(entry["code"] == "set_stmt_premise" for entry in diagnostics)


def test_semantic_bare_index_operator_symbol_exempts_definitions() -> None:
    for text in [
        "List\nList::[]: (list, id) => sym",
        "[]: (list, id) => sym",
        "Function ~ []",
        "_x = [](list, id)",
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
    source = translate_ast_to_source(compile_text("∀{\n∀{| _x | _x = _x}\n∀{| _x | _x = _x}\n}"))
    assert source.count("\n    | ^_x\n") == 2


def test_authored_caret_generated_sym_is_accepted() -> None:
    ast = compile_text("∀{| ^x | ^x = ^x}")
    assert [sym["name"] for sym in ast["bound_syms"] if sym.get("generated")] == ["^x"]


def test_double_underscore_sym_is_not_generated() -> None:
    ast = compile_text("∀{| __x | __x = __x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["__x"]


def test_translate_omits_empty_binder_bar() -> None:
    ast = compile_text("Val ~ min_val\n∀{| _val1 | _val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    lines = source.splitlines()
    assert "|" not in [line.strip() for line in lines]
    assert any(line.strip() == "Val ~ min_val" for line in lines)
    assert not any(line.strip() == "| Val ~ min_val" for line in lines)
    assert any(line.strip() == "| ^_val1" for line in lines)
    assert any(line.strip() == "| Symbol ~ ^_val1" for line in lines)
    assert any(line.strip() == "^_val1 ≥ min_val" for line in lines)


def test_translate_keeps_binder_line_when_present() -> None:
    ast = compile_text("∀{| _x | _x = _x}")
    source = translate_ast_to_source(ast)
    assert "\n  | ^_x" in source


def test_nested_module_disassembly_is_indented() -> None:
    ast = compile_text("-: (_list, _list1) => _list2\n    _list2.size = (_list.size + _list1.size)")
    source = translate_ast_to_source(ast)
    assert "\n  Function ~ -\n" in source
    assert "\n  ∀{\n" in source
    assert "\n    | ^_list, ^_list1, ^_list2" in source
    assert "\n    | ^_list2 = ^_list - ^_list1\n" in source
    assert "\n  }\n" in source


def test_function_output_inheritance_disassembles_as_target() -> None:
    text = "List\n-: (_list, _list1) => _list2\n    _list2.size = (_list.size + _list1.size)"
    first_source = translate_ast_to_source(compile_text(text, base_dir=SKILL_DIR))
    second_source = translate_ast_to_source(compile_text(first_source, base_dir=SKILL_DIR))
    assert "\n  | ^List\n" not in first_source
    assert "\n  | Symbol ~ List\n" not in first_source
    assert "\n  Symbol ~ List\n" in first_source
    assert "\n    | List ~ ^_list\n" in first_source
    assert "\n    | List ~ ^_list1\n" in first_source
    assert "\n    | List ~ ^_list2\n" not in first_source
    assert "\n    List ~ ^_list2\n" in first_source
    assert second_source == first_source


def test_bound_syms_are_not_filtered_as_intrinsics() -> None:
    payload = module_check.check_module("∀{| Symbol, Function, true, false | Symbol = Function}", "<stdin>", SKILL_DIR, is_file=False)
    assert payload["summary"]["error_count"] == 1
    assert payload["entries"][0]["code"] == "naming_error"
    assert payload["entries"][0]["reason"].count("invalid_bound_sym_name") == 4


def test_free_classifier_syms_are_not_auto_bound() -> None:
    ast = compile_text("∀{| _x | Symbol ~ _x | _x = _x}")
    assert [sym["name"] for sym in ast["bound_syms"] if not sym.get("generated")] == ["_x"]


def test_function_output_inheritance_cases() -> None:
    value_source = translate_ast_to_source(compile_text("Value\nf: _value => _out_value\n    _out_value = _out_value", base_dir=SKILL_DIR))
    assert "\n    | Value ~ ^_value\n" in value_source
    assert "\n    | ^_out_value = f(^_value)\n" in value_source
    assert "\n    Value ~ ^_out_value\n" in value_source
    assert "\n    | Value ~ ^_out_value\n" not in value_source

    symbol_source = translate_ast_to_source(compile_text("f: _x => _y\n    _y = _y", base_dir=SKILL_DIR))
    assert "\n    | Symbol ~ ^_x\n" in symbol_source
    assert "\n    | ^_y = f(^_x)\n" in symbol_source
    assert "\n    Symbol ~ ^_y\n" in symbol_source

    generated_source = translate_ast_to_source(compile_text("f: ^x => ^y\n    ^y = ^y", base_dir=SKILL_DIR))
    assert "Symbol ~ ^x" not in generated_source
    assert "Symbol ~ ^y" not in generated_source

    bool_source = translate_ast_to_source(compile_text("Bool\np: _x => _is_valid\n    p(_x)", base_dir=SKILL_DIR))
    assert "\n    Bool ~ ^_is_valid\n" in bool_source
    assert "\n    | Bool ~ ^_is_valid\n" not in bool_source


def test_is_prefixed_declared_syms_implicitly_inherit_bool() -> None:
    input_source = translate_ast_to_source(compile_text("f: _is_val => _out\n    P(_is_val)", base_dir=SKILL_DIR))
    assert "\n    | Bool ~ ^_is_val\n" in input_source
    assert "\n    Symbol ~ ^_out\n" in input_source

    output_source = translate_ast_to_source(compile_text("f: _x => _is_valid", base_dir=SKILL_DIR))
    assert "\n    | Symbol ~ ^_x\n" in output_source
    assert "\n    Bool ~ ^_is_valid\n" in output_source
    assert "\n    | Bool ~ ^_is_valid\n" not in output_source

    override_source = translate_ast_to_source(compile_text("Is_val\nf: _is_val => _out\n    P(_is_val)", base_dir=SKILL_DIR))
    assert "\n    | Bool ~ ^_is_val\n" in override_source
    assert "Is_val ~ ^_is_val" not in override_source

    generated_source = translate_ast_to_source(compile_text("f: ^is_val => ^out\n    P(^is_val)", base_dir=SKILL_DIR))
    assert "Bool ~ ^is_val" not in generated_source
    assert "Symbol ~ ^is_val" not in generated_source


def test_function_declaration_without_output_guarantee_omits_rule() -> None:
    source = translate_ast_to_source(compile_text("f: ^x => ^y", base_dir=SKILL_DIR))
    assert source.strip() == "∀{\n  Function ~ f\n}"


def test_tuple_function_declaration_call_and_destructure_are_premises() -> None:
    source = translate_ast_to_source(compile_text("f: _x => (_y, _z)", base_dir=SKILL_DIR))
    assert "\n    | ^tmpf0 = f(^_x)\n" in source
    assert "\n    | ^_y = ^tmpf0[^tmpvalue1]\n" in source
    assert "\n    | ^_z = ^tmpf0[^tmpvalue2]\n" in source
    assert "\n    Tuple ~ ^tmpf0\n" in source
    assert "\n    Symbol ~ ^_y\n" in source
    assert "\n    Symbol ~ ^_z\n" in source


def test_generated_tuple_function_declaration_keeps_tuple_guarantee() -> None:
    source = translate_ast_to_source(compile_text("f: ^sym => (^sym1, ^sym2)", base_dir=SKILL_DIR))
    assert "\n  ∀{\n" in source
    assert "\n    | ^tmpf0 = f(^sym)\n" in source
    assert "\n    | ^sym1 = ^tmpf0[^tmpvalue1]\n" in source
    assert "\n    | ^sym2 = ^tmpf0[^tmpvalue2]\n" in source
    assert "\n    Tuple ~ ^tmpf0\n" in source
    assert "\n    Value ~ ^tmpvalue1\n" in source
    assert "\n    Value ~ ^tmpvalue2\n" in source
    assert "Symbol ~ ^sym" not in source
    assert "Symbol ~ ^sym1" not in source
    assert "Symbol ~ ^sym2" not in source
    assert "\n    | Tuple ~ ^tmpf0\n" not in source


def test_function_body_return_destructuring_omits_redundant_classifiers() -> None:
    source = translate_ast_to_source(
        compile_text("Sym\nf: _sym => (_sym1, _sym2)\n    | P1(_sym)\n    P2(_sym1, _sym2)", base_dir=SKILL_DIR)
    )
    assert "\n    | ^tmpf0 = f(^_sym)\n" in source
    assert "\n    Tuple ~ ^tmpf0\n" in source
    assert "\n    Value ~ ^tmpvalue1\n" in source
    assert "\n    Value ~ ^tmpvalue2\n" in source
    assert "\n    | ^tmpf3 = f(^_sym)\n" in source
    assert "\n    | ^_sym1 = ^tmpf3[^tmpvalue4]\n" in source
    assert "\n    | ^_sym2 = ^tmpf3[^tmpvalue5]\n" in source
    assert source.count("Tuple ~ ^tmpf") == 1
    assert source.count("Value ~ ^tmpvalue") == 2
    assert "\n    P2(^_sym1, ^_sym2)\n" in source


def test_function_body_local_literal_classifier_is_preserved() -> None:
    source = translate_ast_to_source(compile_text("Sym\nf: _sym => _out\n    P((_sym, _out))", base_dir=SKILL_DIR))
    assert source.count("Tuple ~ ") == 1
    assert "\n    Tuple ~ ^tmptuple0" in source
    assert "P(^tmptuple0" in source


def test_sibling_nested_modules_are_indented_consistently() -> None:
    source = translate_ast_to_source(compile_text("∀{\n∀{| _x | _x = _x}\n∀{| _y | _y = _y}\n}"))
    assert source.count("\n  ∀{\n") == 2
    assert "\n    | ^_x\n" in source
    assert "\n    | ^_y\n" in source


def test_target_literal_assignment_normalized() -> None:
    ast = compile_text("∀{| _x | _x = 1}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "Value_literal_stmt" for binding in ast["premise_binding_stmts"])
    assert not any(stmt["arg_sym_list"][0]["name"] == "Value" for stmt in top_level_calls(ast, "~", "premise_proposition_stmts"))
    assert any(stmt["arg_sym_list"][0]["name"] == "Value" for stmt in top_level_calls(ast, "~", "target_proposition_stmts"))
    assert top_level_calls(ast, "=", "target_proposition_stmts")


def test_generated_literal_assignment_is_closure_stable() -> None:
    expanded = translate_ast_to_source(compile_text("sym = 'a'"))
    assert translate_ast_to_source(compile_text(expanded)) == expanded


def test_nested_literal_argument_adds_classifier_target() -> None:
    ast = compile_text("∀{| _p, _a, _b | P((_a, _b))}")
    assert any(binding["src_stmt"]["kind"] == "Tuple_literal_stmt" for binding in ast["premise_binding_stmts"])
    premise_calls = top_level_calls(ast, "~", "premise_proposition_stmts")
    target_calls = top_level_calls(ast, "~", "target_proposition_stmts")
    assert not any(stmt["arg_sym_list"][0]["name"] == "Tuple" and stmt["arg_sym_list"][1].get("generated") for stmt in premise_calls)
    assert any(stmt["arg_sym_list"][0]["name"] == "Tuple" and stmt["arg_sym_list"][1].get("generated") for stmt in target_calls)


def test_authored_premise_literal_classifier_keeps_premise_and_adds_target() -> None:
    ast = compile_text("∀{| _x | Value ~ 1 | _x = _x}")
    premise_calls = [
        stmt for stmt in top_level_calls(ast, "~", "premise_proposition_stmts")
        if stmt["arg_sym_list"][0]["name"] == "Value" and stmt["arg_sym_list"][1].get("generated")
    ]
    target_calls = [
        stmt for stmt in top_level_calls(ast, "~", "target_proposition_stmts")
        if stmt["arg_sym_list"][0]["name"] == "Value" and stmt["arg_sym_list"][1].get("generated")
    ]
    assert len(premise_calls) == 1, premise_calls
    assert len(target_calls) == 1, target_calls
    assert premise_calls[0]["arg_sym_list"][1]["name"] == target_calls[0]["arg_sym_list"][1]["name"]


def test_authored_target_literal_classifier_dedupes_generated_target() -> None:
    source = translate_ast_to_source(compile_text("∀{| _x | Value ~ 1}"))
    assert source.count("\n  Value ~ ^tmp10\n") == 1, source


def test_target_module_assignment_normalized() -> None:
    ast = compile_text("∀{| _x | _x = ∀{| _y | _y = _y}}")
    assert not target_bindings(ast)
    assert any(binding["src_stmt"]["kind"] == "Quantified_stmt" for binding in ast["premise_binding_stmts"])
    assert top_level_calls(ast, "=", "target_proposition_stmts")


def test_multiline_binding_rhs_disassembly_is_indented() -> None:
    text = "sym = {| ^sym | ^sym >= 0 => ^sym + 1}"
    first_source = translate_ast_to_source(compile_text(text))
    assert "| ^logic_language_out0\n    ∃{" in first_source
    assert "logic_language_out1" not in first_source
    assert "\n  sym = " in first_source
    assert translate_ast_to_source(compile_text(first_source)) == first_source


def test_image_set_maps_source_set_members_not_premise_implication() -> None:
    examples = [
        "{| _x | P(_x) => F(_x)}",
        "{| _x, _y | P(_x, _y) => (F(_x), G(_y))}",
        "{| _x ∈ xs => F(_x)}",
        "{| _x | P(_x) | Q(_x) => F(_x)}",
        "{| _x | _x > 0 | Q(_x) => F(_x)}",
        "{\n    | _x\n    _x ∈ xs\n    _x > 0\n    => F(_x)\n}",
    ]
    for text in examples:
        ast = compile_text(text)
        assert ast["kind"] == "Set_stmt"
        assert len(ast["bound_syms"]) == 1, text
        assert not ast["premise_binding_stmts"], text
        assert not ast["premise_proposition_stmts"], text
        exists = ast["target_proposition_stmts"][0]
        assert exists["kind"] == "Quantified_stmt"
        assert exists["quantifier_sym"]["name"] == "∃"
        source = translate_ast_to_source(ast)
        assert translate_ast_to_source(compile_text(source)) == source, text

    ast = compile_text("{\n    | _x\n    _x ∈ xs\n    _x > 0\n    => F(_x)\n}")
    exists = ast["target_proposition_stmts"][0]
    assert top_level_calls(exists, "∈", "target_proposition_stmts")
    assert top_level_calls(exists, ">", "target_proposition_stmts")
    assert not top_level_calls(exists, "∈", "premise_proposition_stmts")
    assert not top_level_calls(exists, ">", "premise_proposition_stmts")
    ast = compile_text("{| _x | P(_x) | Q(_x) => F(_x)}")
    exists = ast["target_proposition_stmts"][0]
    implication = next(stmt for stmt in exists["target_proposition_stmts"] if stmt["kind"] == "Quantified_stmt")
    assert top_level_calls(implication, "P", "premise_proposition_stmts")
    assert top_level_calls(implication, "Q", "target_proposition_stmts")
    assert not top_level_calls(exists, "P", "premise_proposition_stmts")


def test_disassembled_final_ast_preserves_target_placement() -> None:
    ast = compile_text("Val ~ min_val\n∀{| _val1 | _val1 ≥ min_val}")
    source = translate_ast_to_source(ast)
    reparsed = compile_text(source)
    assert not target_bindings(reparsed)
    assert any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["target_proposition_stmts"])
    assert not any(stmt.get("call_sym", {}).get("name") == "~" for stmt in reparsed["premise_proposition_stmts"])


def test_round_trip_disassembly_is_idempotent() -> None:
    text = "Val ~ min_val\n∀{| _val1 | _val1 ≥ min_val}"
    first_ast = compile_text(text)
    first_source = translate_ast_to_source(first_ast)
    second_ast = compile_text(first_source)
    second_source = translate_ast_to_source(second_ast)
    assert second_source == first_source
    assert first_source.count("| Symbol ~ ^_val1") == 1
    assert "| ^_val1 ~ ^_val1" not in first_source
    assert "| Val ~ ^_val1" not in first_source


def test_generated_temp_round_trip_is_idempotent() -> None:
    text = "-: (_list, _list1) => _list2\n    _list2.size = (_list.size + _list1.size)"
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
    text = "∀{| _a, _b | Tuple ~ (_a, _b)}"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert second_source == first_source


def test_tuple_assignment_round_trip_adds_classifier_predicate() -> None:
    text = "x = (a, b)"
    first_source = translate_ast_to_source(compile_text(text))
    second_source = translate_ast_to_source(compile_text(first_source))
    assert "\n  Tuple ~ ^tmptuple0\n" in first_source
    assert "| Tuple ~ ^tmptuple0" not in first_source
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
            run_compile_pipeline("∀{| _x | _x = _x}")
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
            run_compile_pipeline("∀{| _x | _x = _x}")
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
sys.argv = ["compile_module.py", "--text", "∀{| _x | _x = _x}"]
raise SystemExit(compile_module.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
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
sys.argv = ["compile_module.py", "--debug-stages", "--text", "∀{| _x | _x = _x}"]
raise SystemExit(compile_module.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=Path(__file__).resolve().parents[4],
        check=False,
    )
    assert result.returncode == 1
    assert '"stage": "stage1_front_end"' in result.stdout
    assert '"stage": "stage2_back_end"' in result.stdout
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


def test_module_check_multiline_module_braces_reject_invalid_opener() -> None:
    invalid_opener = "_threads = {|\n  | _thread\n  _thread ∈ _threads\n}\n"
    payload = module_check.check_module(invalid_opener, module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 1
    entry = next(entry for entry in payload["entries"] if entry["type"] == "error")
    assert entry["code"] == "invalid_multiline_module_brace"
    assert entry["reason"].startswith("multiline module opener")
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == invalid_opener.index("{")


def test_module_check_multiline_module_braces_allow_brace_only_and_inline_forms() -> None:
    for source in [
        "_threads = {\n  | _thread\n  _thread ∈ _threads\n}\n",
        "_threads = update({\n  | _thread\n  _thread ∈ _threads\n})\n",
        "_threads = {| _thread | _thread ∈ _threads}\n",
        "∀{| _x | _x = _x}\n",
        "∀{\n  | _x\n  _x = _x\n}\n",
    ]:
        payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 0, (source, payload)


def test_module_check_wrapped_set_target_quantifier_block_is_not_binder_section() -> None:
    source = """∀{
    | _out
    _out = min({
        | _candidate
        ∀
            | _i
            | _candidate = _i
            _i = _candidate
    })
}
"""
    payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 0, payload


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
        ("f: _x -> _y\n    P(_y)\n", "syntax", "function-assign '->' is not supported; use '=>' with an indented function body", 0, 6, 8),
        ("x = '\\q'\n", "compile", "invalid escape sequence \\q", 0, 5, 7),
    ]

    for text, stage, reason, line, col_start, col_end in cases:
        payload = module_check.check_module(text, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 1, (text, payload)
        entry = payload["entries"][0]
        assert entry["stage"] == stage
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
        payload = module_check.check_module("∀{| _x | _x = _x}", module_check.STDIN_FILE, Path("."), is_file=False)
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
        payload = module_check.check_module("∀{| _x | _x = _x}", module_check.STDIN_FILE, Path("."), is_file=False)
    finally:
        module_check.semantic_entries = original_semantic_entries
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert called["compile"]
    assert payload["summary"] == {"error_count": 0, "warning_count": 1}


def test_module_check_compile_error_fallback_uses_first_source_line() -> None:
    original_run_compile_pipeline = module_check.run_compile_pipeline

    def compile_fails(*args, **kwargs):
        raise CompileError("lowering failed")

    module_check.run_compile_pipeline = compile_fails
    try:
        payload = module_check.check_module("∀{| _x | _x = _x}", "/tmp/input.lp", Path("."), is_file=False)
    finally:
        module_check.run_compile_pipeline = original_run_compile_pipeline

    entry = next(entry for entry in payload["entries"] if entry["stage"] == "compile")
    assert payload["summary"]["error_count"] == 1
    assert entry["stage"] == "compile"
    assert entry["file"] == "/tmp/input.lp"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 0
    assert entry["code"] == "compile_error"


def test_module_check_compile_error_uses_structured_source_location() -> None:
    original_run_compile_pipeline = module_check.run_compile_pipeline

    def compile_fails(*args, **kwargs):
        raise CompileError(
            "lowering failed",
            source_loc={"source": "/tmp/source.lp", "line": 2, "column": 5, "end_line": 2, "end_column": 9},
        )

    module_check.run_compile_pipeline = compile_fails
    try:
        payload = module_check.check_module("A\nB\n", "/tmp/input.lp", Path("."), is_file=False)
    finally:
        module_check.run_compile_pipeline = original_run_compile_pipeline

    entry = next(entry for entry in payload["entries"] if entry["stage"] == "compile")
    assert payload["summary"]["error_count"] == 1
    assert entry["file"] == "/tmp/source.lp"
    assert entry["lineno"] == 1
    assert entry["col_start_no"] == 4
    assert entry["col_end_no"] == 8
    assert entry["reason"] == "lowering failed"


def test_module_check_compile_error_uses_source_fragment_location() -> None:
    payload = module_check.check_module("x = a ??? b\n", "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = payload["entries"][0]
    assert entry["stage"] == "compile"
    assert entry["file"] == "/tmp/input.lp"
    assert entry["reason"] == "unsupported expression: raw"
    assert entry["lineno"] == 0
    assert entry["col_start_no"] == 4
    assert entry["col_end_no"] == 11
    assert entry["code"] == "compile_error"


def test_module_check_compile_error_inside_decl_body_uses_body_line() -> None:
    source = "f: _x => _y\n    | _z = _x + (bad ??? raw)\n    _y = _z\n"
    payload = module_check.check_module(source, "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    errors = [entry for entry in payload["entries"] if entry["type"] == "error"]
    assert len(errors) == 1
    entry = errors[0]
    assert entry["stage"] == "compile"
    assert entry["file"] == "/tmp/input.lp"
    assert entry["reason"] == "unsupported expression: raw"
    assert entry["lineno"] == 1
    assert entry["col_start_no"] == 17
    assert entry["col_end_no"] == 28
    assert entry["code"] == "compile_error"


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
        payload = module_check.check_module("∀{| _x | _x = _x}", "/tmp/input.lp", Path("."), is_file=False)
    finally:
        module_check.run_compile_pipeline = original_run_compile_pipeline

    assert payload["summary"]["error_count"] == 1
    assert {**diagnostic, "stage": "final_ast"} in payload["entries"]


def test_compile_rejects_bare_sym_target_final_ast() -> None:
    source = "{\n  | _thread\n  _thread\n}\n"
    try:
        compile_text(source)
    except compile_module_script.FinalAstValidationCompileError as error:
        assert any(entry["code"] == "invalid_target_proposition_stmt" for entry in error.diagnostics)
    else:
        raise AssertionError("expected bare target Sym to fail final AST validation")

    payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
    assert payload["summary"]["error_count"] == 1
    entry = next(entry for entry in payload["entries"] if entry["stage"] == "final_ast")
    assert entry["code"] == "invalid_target_proposition_stmt"
    assert entry["reason"] == "target_proposition_stmts must contain only proposition statements"
    assert entry["lineno"] == 2
    assert entry["col_start_no"] == source.splitlines()[2].index("_thread")


def test_compile_allows_proposition_targets() -> None:
    for source in [
        "{\n  | _thread\n  _thread = _thread\n}\n",
        "∀{| _thread | P(_thread)}",
    ]:
        payload = module_check.check_module(source, module_check.STDIN_FILE, Path("."), is_file=False)
        assert payload["summary"]["error_count"] == 0, (source, payload)
        compile_text(source)


def test_module_check_final_ast_plain_declaration_conflict_uses_input_location() -> None:
    source = "∀\n    | _x\n    f: _x => _y\n"
    payload = module_check.check_module(source, "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 1
    entry = next(entry for entry in payload["entries"] if entry["stage"] == "final_ast")
    assert entry["stage"] == "final_ast"
    assert entry["code"] == "bound_sym_name_conflict"
    assert entry["reason"] == "bound-sym name '_x' conflicts with ancestor statement"
    assert entry["lineno"] == 2
    assert entry["col_start_no"] == source.splitlines()[2].index("_x")


def test_module_check_final_ast_class_method_body_conflict_uses_declaration_location() -> None:
    source = "∀\n    | _x\n    Class\n    Class::m: _x => _y\n        P(_y)\n"
    payload = module_check.check_module(source, "/tmp/input.lp", Path("."), is_file=False)

    assert payload["summary"]["error_count"] == 2
    entry = next(entry for entry in payload["entries"] if entry["stage"] == "final_ast")
    assert entry["stage"] == "final_ast"
    assert entry["code"] == "bound_sym_name_conflict"
    assert entry["lineno"] == 3
    assert entry["col_start_no"] == source.splitlines()[3].index("_x")


def test_module_check_text_import_resolves_standard_library_from_skill_dir() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "module_check.py"),
            "--text",
            "$import standard_library.lp\n∀{| _val | _val = _val}",
            "--base-dir",
            tempfile.gettempdir(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert not any(entry["code"] == "missing_import" for entry in payload["entries"])
    assert payload["summary"] == {"error_count": 0, "warning_count": 3}
    assert all(entry["code"] == "set_stmt_premise" for entry in payload["entries"])


def test_module_check_standard_library_has_only_set_premise_warnings() -> None:
    payload = module_check.check_module(
        (SKILL_DIR / "standard_library.lp").read_text(encoding="utf-8"),
        str((SKILL_DIR / "standard_library.lp").resolve()),
        SKILL_DIR,
        is_file=True,
    )
    assert payload["summary"] == {"error_count": 0, "warning_count": 3}, payload
    assert all(entry["code"] == "set_stmt_premise" for entry in payload["entries"])


def test_module_check_stdin_import_uses_base_dir() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "imported.lp").write_text("Imported\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "module_check.py"),
                "--base-dir",
                str(root),
            ],
            input="$import imported.lp\n∀{| _x | _x = _x}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=SKILL_DIR,
            check=False,
        )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["error_count"] == 0


def test_expand_module_cli_text_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "expand_module.py"), "--text", "∀{| _x | _x = _x}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^_x\n  | Symbol ~ ^_x\n  ^_x = ^_x\n}\n"


def test_expand_module_cli_file_mode() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "input.lp"
        path.write_text("∀{| _x | _x = _x}", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "expand_module.py"), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=SKILL_DIR,
            check=False,
        )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^_x\n  | Symbol ~ ^_x\n  ^_x = ^_x\n}\n"


def test_expand_module_cli_stdin_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "expand_module.py")],
        input="∀{| _x | _x = _x}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=SKILL_DIR,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "∀{\n  | ^_x\n  | Symbol ~ ^_x\n  ^_x = ^_x\n}\n"


def test_expand_module_cli_invalid_input() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "expand_module.py"), "--text", "{| }"],
        capture_output=True,
        text=True,
        encoding="utf-8",
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


def test_resolve_sym_type_completion_scopes_include_expanded_bound_syms() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Coord",
                "Val",
                "f: _val => _out",
                "    | _raw_coord = coord(_val)",
                "    _out = _raw_coord",
            ]
        )
    )
    scope_names = {
        sym["name"]
        for scope in payload["completion_scopes"]
        for sym in scope["bound_syms"]
    }
    assert {"_val", "_out", "_raw_coord"} <= scope_names
    assert all(entry["name"] != "_raw_coord" for entry in payload["completion_symbols"])
    nested_payload = resolve_sym_type.resolve_text("∀\n    | _nested\n    P(_nested)")
    nested_scope_names = {
        sym["name"]
        for scope in nested_payload["completion_scopes"]
        for sym in scope["bound_syms"]
    }
    assert "_nested" in nested_scope_names

    image_set_payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Wave",
                "f: _waves => _pairs",
                "    _pairs = {",
                "        | _wave ∈ _waves",
                "        | _instr = cur_instr(_wave)",
                "        ",
                "    }",
            ]
        )
    )
    image_set_scopes = [
        scope
        for scope in image_set_payload["completion_scopes"]
        if any(sym["name"] == "_wave" for sym in scope["bound_syms"])
    ]
    assert image_set_scopes
    assert any(scope["start_lineno"] <= 5 <= scope["end_lineno"] for scope in image_set_scopes)


def test_resolve_sym_type_predicate_wins_over_function() -> None:
    payload = resolve_sym_type.resolve_text("Function ~ p\nPredicate ~ p\np(x)")
    assert resolved_symbol(payload, "p")["type"] == "pred"


def test_resolve_sym_type_class_wins_over_callable_evidence() -> None:
    payload = resolve_sym_type.resolve_text("Predicate\nFunction ~ Predicate\nPred = Predicate")
    assert resolved_symbol(payload, "Predicate")["type"] == "class"
    assert resolved_symbol(payload, "Pred")["type"] == "class"


def test_resolve_sym_type_operator_symbols_are_not_colorable() -> None:
    payload = resolve_sym_type.resolve_text("Function ~ []\n_x = [](y)\nz = [:](x, y)")
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
                "f: _x => _y",
                "    _y = f(_x)",
                "Function ~ g",
                "_z = g(_y)",
                "Predicate ~ p",
                "p(_z)",
            ]
        )
    )
    assert "definition" not in occurrence_on_line(payload, "A", 0)
    assert occurrence_on_line(payload, "B", 0)["definition"]["lineno"] == 1
    assert occurrence_on_line(payload, "f", 3)["definition"]["lineno"] == 2
    assert occurrence_on_line(payload, "g", 5)["definition"]["lineno"] == 4
    assert occurrence_on_line(payload, "p", 7)["definition"]["lineno"] == 6
    assert "definition" not in occurrence_on_line(payload, "_x", 3)
    assert "definition" not in occurrence_on_line(payload, "_z", 7)


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
    payload = resolve_sym_type.resolve_text("| _value\nClass\nClass ~ _value\nP(_value)")
    occurrence = occurrence_on_line(payload, "_value", 3)
    assert occurrence["type"] == "pure"
    assert occurrence["definition"]["name"] == "Class"
    assert occurrence["definition"]["lineno"] == 1


def test_resolve_sym_type_untyped_pure_symbol_has_no_definition() -> None:
    payload = resolve_sym_type.resolve_text("| _x\nP(_x)")
    assert "definition" not in occurrence_on_line(payload, "_x", 0)
    assert "definition" not in occurrence_on_line(payload, "_x", 1)


def test_resolve_sym_type_output_uses_generated_signature_class_evidence() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Sym_type",
                "Stmt",
                "Stmt::get_sym_type: (_stmt, _sym) => _sym_type",
                "    _sym_type = _sym_type",
            ]
        )
    )
    occurrence = occurrence_on_line(payload, "_sym_type", 2)
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
    payload = resolve_sym_type.resolve_text("Chip_mem\nf: _chip_mem_class => _out")
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
                "f: _x => _out",
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
    payload = resolve_sym_type.resolve_text("Val\nf: _x => _y\n    | Val ~ _x\n    _y = _y")
    assert "definition" not in occurrence_on_line(payload, "_x", 1)
    assert "definition" not in occurrence_on_line(payload, "_x", 2)


def test_resolve_sym_type_authored_premise_class_fact_is_not_class_navigation_evidence() -> None:
    payload = resolve_sym_type.resolve_text("Id\nf: _x => _y\n    | Id ~ _x\n    _y = _y")
    assert "definition" not in occurrence_on_line(payload, "_x", 1)
    assert "definition" not in occurrence_on_line(payload, "_x", 2)


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
                "Sym_type ~ _class_sym_type",
                "f: _x => _out",
                "    _out = _class_sym_type",
            ]
        )
    )
    assert occurrence_on_line(payload, "_out", 2)["definition"]["name"] == "Sym_type"
    assert occurrence_on_line(payload, "_out", 3)["definition"]["name"] == "Sym_type"


def test_resolve_sym_type_premise_equality_does_not_propagate_class_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Sym_type",
                "Sym_type ~ _class_sym_type",
                "f: _x => _out",
                "    | _out = _class_sym_type",
                "    _out = _out",
            ]
        )
    )
    assert "definition" not in occurrence_on_line(payload, "_out", 2)
    assert "definition" not in occurrence_on_line(payload, "_out", 3)
    assert "definition" not in occurrence_on_line(payload, "_out", 4)


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
                "    ::arg_sym_list: _notsubset_stmt => _list",
                "        _list = [_notsubset_stmt.lhs_sym, _notsubset_stmt.rhs_sym]",
            ]
        )
    )
    for line in [3, 4]:
        occurrence = occurrence_on_line(payload, "_notsubset_stmt", line)
        assert occurrence["type"] == "pure"
        assert occurrence["definition"]["name"] == "Notsubset_stmt"
        assert occurrence["definition"]["lineno"] == 0


def test_resolve_sym_type_qualified_class_owner_receiver_definition() -> None:
    payload = resolve_sym_type.resolve_text("Notsubset_stmt\nNotsubset_stmt::arg_sym_list: _notsubset_stmt => _list\n    _list = _notsubset_stmt")
    for line in [1, 2]:
        occurrence = occurrence_on_line(payload, "_notsubset_stmt", line)
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
                "f: _x => _y",
                "    _y = _x",
                "Predicate ~ p",
                "p: _x => _is_valid",
                "    _is_valid = true",
                "_z = f(_x)",
                "p(_z)",
            ]
        )
    )
    assert occurrence_on_line(payload, "f", 6)["definition"]["lineno"] == 1
    assert occurrence_on_line(payload, "p", 7)["definition"]["lineno"] == 3


def test_resolve_sym_type_member_call_uses_qualified_class_method_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "func: _x => _y",
                "    _y = _x",
                "Class ~ _receiver",
                "Class::func: _receiver => _out",
                "    _out = _receiver",
                "_y = _receiver.func",
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
                "    ::func: _receiver => _out",
                "        _out = _receiver",
                "Class ~ _receiver",
                "_y = _receiver.func",
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
                "Class ~ _receiver",
                "_y = _receiver.field",
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
                "B~_b",
            ]
        )
    )
    symbol = resolved_symbol(payload, "field")
    assert symbol["type"] == "func"
    occurrence = occurrence_on_line(payload, "field", 3)
    assert occurrence["colorable"] is True


def test_resolve_sym_type_class_field_assignment_is_function() -> None:
    payload = resolve_sym_type.resolve_text("Class\n    ::field = value")
    symbol = resolved_symbol(payload, "field")
    assert symbol["type"] == "func"
    occurrence = occurrence_on_line(payload, "field", 1)
    assert occurrence["colorable"] is True


def test_resolve_sym_type_member_call_uses_class_field_assignment_definition() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "    ::field = value",
                "Class ~ _receiver",
                "_y = _receiver.field",
            ]
        )
    )
    definition = occurrence_on_line(payload, "field", 3)["definition"]
    assert definition["lineno"] == 1
    assert definition["col_start_no"] == len("    ::")


def test_resolve_sym_type_member_call_falls_back_to_function_declaration() -> None:
    payload = resolve_sym_type.resolve_text(
        "\n".join(
            [
                "Class",
                "func: _x => _y",
                "    _y = _x",
                "Class ~ _receiver",
                "_y = _receiver.func",
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
        main.write_text("$import imported.lp\nf: _x => _y\n_z = f(_x)\n", encoding="utf-8")
        payload = resolve_sym_type.resolve_file(main)

    definition = occurrence_on_line(payload, "f", 2)["definition"]
    assert definition["file"] == str(main.resolve())
    assert definition["lineno"] == 1


def test_resolve_sym_type_invalid_source_returns_empty_success_payload() -> None:
    payload = resolve_sym_type.resolve_text("∀{| x | x = x")
    assert payload == {"summary": {"symbol_count": 0, "occurrence_count": 0}, "symbols": [], "completion_scopes": [], "occurrences": []}


def test_resolve_sym_type_cli_modes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "resolve_sym_type.py"), "--text", "Function ~ f\ny = f(x)", "--pretty"],
        capture_output=True,
        text=True,
        encoding="utf-8",
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
            [sys.executable, str(SCRIPTS_DIR / "resolve_sym_type.py"), "--file", str(main)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=SKILL_DIR,
            check=False,
        )
        assert file_result.returncode == 0
        file_payload = json.loads(file_result.stdout)
        assert resolved_symbol(file_payload, "p")["type"] == "pred"
        assert {entry["file"] for entry in file_payload["occurrences"]} == {str(main.resolve())}

        stdin_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "resolve_sym_type.py"),
                "--filename",
                str(main),
                "--base-dir",
                str(root),
            ],
            input="$import imported.lp\np(x)\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
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
        "compile_pipeline.source_syntax",
        "compile_pipeline.module_parser",
        "compile_pipeline.front_end_source_loader",
        "compile_pipeline.front_end_desugar",
        "compile_pipeline.back_end_sections",
        "compile_pipeline.back_end_statements",
        "compile_pipeline.back_end_lower_object",
        "syntax_check",
        "semantic_check",
        "module_check",
        "resolve_sym_type",
        "translate_AST_to_source",
        "validate_golden_tests",
    ]
    for module in modules:
        importlib.import_module(module)


def test_inline_mapping_lambda_scope_and_round_trip() -> None:
    text = "| _offset_val\n_result = sum({1, 2}, _value -> _value + _offset_val)"
    ast = compile_text(text, base_dir=SKILL_DIR)
    payload = module_check.check_module(text, "<mapping-test>", SKILL_DIR, is_file=False)
    assert payload["summary"]["error_count"] == 0, payload
    plus = calls(ast, "+")[0]
    assert plus["arg_sym_list"][0]["name"].startswith("^tmplambda_arg")
    assert plus["arg_sym_list"][1]["name"] == "_offset_val"
    assert_source_loc_invariant(ast)
    assert compile_text(translate_ast_to_source(ast), base_dir=SKILL_DIR)


def test_inline_mapping_nested_and_constant() -> None:
    ast = compile_text("_result = sum({1, 2}, _value -> 2)", base_dir=SKILL_DIR)
    assert len(calls(ast, "sum")) == 1
    assert not any(node.get("kind") == "Set_stmt" for node in all_nodes(ast))
    ast = compile_text("_result = sum({1, 2}, _value -> sum({3, 4}, _value -> _value))", base_dir=SKILL_DIR)
    args = [node["name"] for node in all_nodes(ast)
            if node.get("kind") == "Sym" and node.get("name", "").startswith("^tmplambda_arg")]
    assert len(set(args)) == 2
    assert len(calls(ast, "sum")) == 2
    assert_source_loc_invariant(ast)


def test_mapped_set_sum_standard_library() -> None:
    text = "$import standard_library.lp\nmapping_example: () => _mapped_val\n    _mapped_val = sum({1, 2}, _value -> 2)"
    payload = module_check.check_module(text, "<mapping-example>", SKILL_DIR, is_file=False)
    assert payload["summary"] == {"error_count": 0, "warning_count": 3}, payload
    ast = compile_text(text, base_dir=SKILL_DIR, allow_imports=True)
    assert calls(ast, "map")
    assert_source_loc_invariant(ast)


def main() -> int:
    tests = [
        test_inline_mapping_lambda_scope_and_round_trip,
        test_inline_mapping_nested_and_constant,
        test_mapped_set_sum_standard_library,
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
        test_modulo_operator,
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
        test_class_field_assignment_lowers_to_field_declaration_and_axiom,
        test_class_field_assignment_premise_lowers_to_premise_artifacts,
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
        test_stage2_declared_class_symbol_fact_is_deduped,
        test_stage2_does_not_inject_implicit_stdlib_import,
        test_standard_library_supplies_universal_inheritance_axioms,
        test_stage2_generated_sym_does_not_re_desugar,
        test_stage2_authored_generated_sym_gets_no_implicit_facts,
        test_double_underscore_sym_is_ordinary,
        test_stage2_synthesized_infixes_are_spaced,
        test_stage2_attaches_authoritative_desugared_module,
        test_compile_stages_are_ast_only_and_no_render_fallbacks,
        test_stage2_structural_collection_inheritance_module,
        test_stage2_target_only_does_not_infer_bound_sym,
        test_stage2_omits_symbol_when_inheritance_premise_exists,
        test_stage2_permissive_unspaced_infix_still_compiles,
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
        test_semantic_set_premise_warnings,
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
        test_final_ast_source_loc_invariant_and_generated_source_name,
        test_ast_type_inheritance_uses_isinstance,
        test_generated_declaration_fact_uses_declaration_head_loc,
        test_generated_inheritance_fact_uses_inferred_binder_loc,
        test_sibling_nested_modules_are_indented_consistently,
        test_target_literal_assignment_normalized,
        test_generated_literal_assignment_is_closure_stable,
        test_nested_literal_argument_adds_classifier_target,
        test_authored_premise_literal_classifier_keeps_premise_and_adds_target,
        test_authored_target_literal_classifier_dedupes_generated_target,
        test_target_module_assignment_normalized,
        test_multiline_binding_rhs_disassembly_is_indented,
        test_image_set_maps_source_set_members_not_premise_implication,
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
        test_module_check_multiline_module_braces_reject_invalid_opener,
        test_module_check_multiline_module_braces_allow_brace_only_and_inline_forms,
        test_module_check_wrapped_set_target_quantifier_block_is_not_binder_section,
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
        test_module_check_compile_error_fallback_uses_first_source_line,
        test_module_check_compile_error_uses_structured_source_location,
        test_module_check_compile_error_uses_source_fragment_location,
        test_module_check_compile_error_inside_decl_body_uses_body_line,
        test_module_check_final_ast_diagnostics_keep_location_and_code,
        test_compile_rejects_bare_sym_target_final_ast,
        test_compile_allows_proposition_targets,
        test_module_check_final_ast_plain_declaration_conflict_uses_input_location,
        test_module_check_final_ast_class_method_body_conflict_uses_declaration_location,
        test_module_check_text_import_resolves_standard_library_from_skill_dir,
        test_module_check_standard_library_has_only_set_premise_warnings,
        test_module_check_stdin_import_uses_base_dir,
        test_expand_module_cli_text_mode,
        test_expand_module_cli_file_mode,
        test_expand_module_cli_stdin_mode,
        test_expand_module_cli_invalid_input,
        test_resolve_sym_type_class_func_pred_and_alias_evidence,
        test_resolve_sym_type_completion_scopes_include_expanded_bound_syms,
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
        test_resolve_sym_type_class_field_assignment_is_function,
        test_resolve_sym_type_member_call_uses_class_field_assignment_definition,
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
