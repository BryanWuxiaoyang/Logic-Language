#!/usr/bin/env python3
"""Schema-backed semantic AST dataclasses for logic-language.

The compiler uses these classes as its AST dispatch surface.  JSON
``kind`` strings are emitted for interchange/debugging only; compiler logic
should use ``isinstance(node, Some_stmt)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


Json = dict[str, Any]


@dataclass
class Source_loc:
    file_path: str
    line: int
    column: int
    end_line: int
    end_column: int

    @classmethod
    def from_json(cls, value: Json | None) -> "Source_loc":
        if not isinstance(value, dict):
            return cls("__generated__", 1, 1, 1, 1)
        return cls(
            file_path=str(value.get("file_path", value.get("source", "__generated__"))),
            line=_positive_int(value.get("line", value.get("start_line_id")), 1),
            column=_positive_int(value.get("column", value.get("start_col_id")), 1),
            end_line=_positive_int(value.get("end_line", value.get("end_line_id")), _positive_int(value.get("line", value.get("start_line_id")), 1)),
            end_column=_positive_int(value.get("end_column", value.get("end_col_id")), _positive_int(value.get("column", value.get("start_col_id")), 1)),
        )

    def to_json(self) -> Json:
        return {
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


class SourceLoc(Source_loc):
    """Parser-facing alias for source locations.

    Existing parser code historically used ``source`` instead of
    ``file_path``.  Keep that constructor/property here so parser internals
    still share the single AST.py type source.
    """

    def __init__(self, source: str, line: int, column: int, end_line: int, end_column: int) -> None:
        super().__init__(source, line, column, end_line, end_column)

    @property
    def source(self) -> str:
        return self.file_path

    def to_json(self) -> Json:
        return {
            "source": self.file_path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass
class AST_node:
    source_loc: Source_loc = field(default_factory=lambda: default_loc())
    generated: bool = False

    @property
    def kind(self) -> str:
        return type(self).__name__

    def base_json(self) -> Json:
        node: Json = {"kind": self.kind, "loc": (self.source_loc).to_json(), "source_loc": self.source_loc.to_json()}
        if self.generated:
            node["generated"] = True
        return node

    def to_json(self) -> Json:
        return self.base_json()


@dataclass
class Sym(AST_node):
    name: str = ""
    source_name: str | None = None

    def to_json(self) -> Json:
        node = self.base_json()
        node["name"] = self.name
        if self.generated:
            node["generated"] = True
            node["source_name"] = self.source_name or generated_source_name(self.name)
        elif self.source_name is not None:
            node["source_name"] = self.source_name
        return node


@dataclass
class SymNode:
    name: str
    source_loc: SourceLoc | Json | None = None
    generated: bool = False
    source_name: str | None = None

    def to_json(self) -> Json:
        node: Json = {"kind": "sym", "name": self.name}
        if self.source_loc is not None:
            node["source_loc"] = loc_to_json(self.source_loc)
        if self.generated:
            node["generated"] = True
            if self.source_name is not None:
                node["source_name"] = self.source_name
        return node


@dataclass(init=False)
class ExprNode:
    """Base class for frontend expression nodes.

    ``kind`` is retained as a read-only debug/compatibility property. Compiler
    logic should dispatch with ``isinstance`` on the concrete subclasses below.
    """

    expr_kind = "expr"

    source_loc: SourceLoc | Json | None
    sym: SymNode | None
    call_sym: SymNode | None
    args: list["ExprNode"]
    items: list["ExprNode"]
    value: str | None

    def __init__(
        self,
        source_loc: SourceLoc | Json | None = None,
        *,
        sym: SymNode | None = None,
        call_sym: SymNode | None = None,
        args: list["ExprNode"] | None = None,
        items: list["ExprNode"] | None = None,
        value: str | None = None,
    ) -> None:
        self.source_loc = source_loc
        self.sym = sym
        self.call_sym = call_sym
        self.args = args or []
        self.items = items or []
        self.value = value

    @property
    def kind(self) -> str:
        return self.expr_kind


class Empty_expr(ExprNode):
    expr_kind = "empty"


class Raw_expr(ExprNode):
    expr_kind = "raw"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, value: str = "") -> None:
        super().__init__(source_loc, value=value)


class Lambda_expr(ExprNode):
    expr_kind = "lambda"

    def __init__(self, source_loc=None, *, sym: SymNode, body: ExprNode) -> None:
        super().__init__(source_loc, sym=sym, args=[body])


class Module_ref_expr(ExprNode):
    expr_kind = "module_ref"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, value: str = "0") -> None:
        super().__init__(source_loc, value=value)


class Sym_expr(ExprNode):
    expr_kind = "sym"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, sym: SymNode) -> None:
        super().__init__(source_loc, sym=sym)


class Call_expr(ExprNode):
    expr_kind = "call"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, call_sym: SymNode, args: list[ExprNode]) -> None:
        super().__init__(source_loc, call_sym=call_sym, args=args)


class Tuple_expr(ExprNode):
    expr_kind = "tuple"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, items: list[ExprNode]) -> None:
        super().__init__(source_loc, items=items)


class Set_expr(ExprNode):
    expr_kind = "set"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, items: list[ExprNode]) -> None:
        super().__init__(source_loc, items=items)


class Literal_expr(ExprNode):
    literal_kind = ""

    @property
    def kind(self) -> str:
        return f"{self.literal_kind}_literal"

    def __init__(self, source_loc: SourceLoc | Json | None = None, *, value: str = "") -> None:
        super().__init__(source_loc, value=value)


class Value_literal_expr(Literal_expr):
    literal_kind = "value"


class Char_literal_expr(Literal_expr):
    literal_kind = "char"


class String_literal_expr(Literal_expr):
    literal_kind = "string"


@dataclass
class SourceStatement:
    source_loc: SourceLoc | Json | None = None
    expr: ExprNode | None = None
    sub_modules: list["SourceModule"] = field(default_factory=list)


@dataclass
class FunctionDecl:
    name: SymNode
    inputs: list[SymNode]
    outputs: list[SymNode]
    owner: SymNode | None = None
    body: list[SourceStatement] = field(default_factory=list)
    premise_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    target_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    body_premise_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    body_target_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    body_module: Any | None = None
    source_loc: SourceLoc | Json | None = None
    premise: bool = False


@dataclass
class ClassFieldDecl:
    name: SymNode
    owner: SymNode | None = None
    source_loc: SourceLoc | Json | None = None


@dataclass
class ClassFieldAssign:
    name: SymNode
    owner: SymNode | None = None
    rhs: ExprNode | SourceStatement | None = None
    source_loc: SourceLoc | Json | None = None
    premise: bool = False


@dataclass
class ClassMethodDecl:
    decl: FunctionDecl
    source_loc: SourceLoc | Json | None = None


ClassMember = ClassMethodDecl | ClassFieldDecl | ClassFieldAssign


@dataclass
class ClassDecl:
    name: SymNode
    members: list[ClassMember] = field(default_factory=list)
    source_loc: SourceLoc | Json | None = None


INFER_OPERATORS = ("=", ">", "<", ">=", "<=", "≤", "≥", "∈", "∉", "⊂", "⊄", "⊆", "⊈", "≠")
GENERATED_SYM_PREFIX = "^"
SPECIAL_IDENTIFIER_SYMS = {"[:]", "[]"}
FRESH_PREFIX = "^logic_language_out"
DECL_OUTPUT_MARKER = "__compiler_function_outputs"
DECL_BODY_OUTPUT_MARKER = "__compiler_function_body_outputs"
BRANCH_MODULE_MARKER = "__compiler_branch_module"
CLASS_DECL_MARKER = "__compiler_class_decl"
INDENT_WIDTH = 4
INDENTATION_BODY_OWNER_ERROR = "indentation body is only allowed after quantifier, branch, declaration, or class declaration"
INDENTATION_LEVEL_ERROR = "indentation can only increase by one level"
PREMISE_QUANTIFIER_HEADERS = {
    "| ∀": "∀",
    "|∀": "∀",
    "| ∃": "∃",
    "|∃": "∃",
}


@dataclass
class Statement:
    sub_modules: list["Module"] = field(default_factory=list)
    source_loc: Json | None = None
    sym_locs: dict[str, Json] = field(default_factory=dict)
    source_name: str | None = None
    expr: Any | None = None
    marker: str | None = None
    marker_syms: list[str] = field(default_factory=list)


@dataclass
class Module:
    type: str
    syms: list[str]
    predicate_statements: list[Statement]
    target_statements: list[Statement]
    quantifier: str | None = None
    source_loc: Json | None = None
    declared_classes: list[str] = field(default_factory=list)
    declaration_syms: list[str] = field(default_factory=list)
    suppress_inferred_syms: bool = False
    bound_sym_locs: list[Json | None] = field(default_factory=list)
    bound_sym_source_names: list[str | None] = field(default_factory=list)
    declaration_sym_locs: dict[str, Json] = field(default_factory=dict)
    declared_class_locs: dict[str, Json] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassFieldAssignment:
    class_name: str
    field_name: str
    rhs: str
    premise: bool = False


UNDECLARED_CLASS_MEMBER_OWNER_CODE = "undeclared_class_member_owner"
def undeclared_class_member_owner_reason(class_name: str) -> str:
    return f"class member declaration requires explicit class declaration: {class_name}"


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


@dataclass
class SourceModule:
    type: str
    source_loc: SourceLoc | Json | None = None
    quantifier: SymNode | None = None
    bound_syms: list[SymNode] = field(default_factory=list)
    premise_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    target_proposition_stmts: list[SourceStatement] = field(default_factory=list)
    statements: list[SourceStatement] = field(default_factory=list)
    declarations: list[FunctionDecl] = field(default_factory=list)
    classes: list[ClassDecl] = field(default_factory=list)
    children: list["SourceModule"] = field(default_factory=list)
    suppress_inferred_syms: bool = False
    lowered_module: Any | None = None


@dataclass
class SourceFileAst:
    source: str
    source_loc: SourceLoc
    imports: list[str] = field(default_factory=list)
    import_count: int = 0
    line_count: int = 0
    modules: list[SourceModule] = field(default_factory=list)

    def summary(self) -> str:
        return "\n".join(
            [
                "stage: stage1_front_end",
                f"source: {self.source}",
                f"imports: {self.import_count}",
                f"lines: {self.line_count}",
                "ast: parsed",
            ]
        )


class Stmt(AST_node):
    pass


class Proposition_stmt(Stmt):
    pass


@dataclass
class Binding_stmt(Stmt):
    dst_sym: Sym = field(default_factory=lambda: Sym(default_loc(), name=""))
    src_stmt: Stmt = field(default_factory=lambda: Sym(default_loc(), name=""))

    def to_json(self) -> Json:
        node = self.base_json()
        node["dst_sym"] = self.dst_sym.to_json()
        node["src_stmt"] = self.src_stmt.to_json()
        return node


class Literal_stmt(Stmt):
    pass


@dataclass
class Char_literal_stmt(Literal_stmt):
    value: str = ""

    def to_json(self) -> Json:
        node = self.base_json()
        node["value"] = self.value
        return node


@dataclass
class Str_literal_stmt(Literal_stmt):
    value: str = ""

    def to_json(self) -> Json:
        node = self.base_json()
        node["value"] = self.value
        return node


@dataclass
class Value_literal_stmt(Literal_stmt):
    value: str = ""

    def to_json(self) -> Json:
        node = self.base_json()
        node["value"] = self.value
        return node


@dataclass
class Tuple_literal_stmt(Literal_stmt):
    item_stmts: list[Stmt] = field(default_factory=list)

    def to_json(self) -> Json:
        node = self.base_json()
        node["item_stmts"] = [item.to_json() for item in self.item_stmts]
        return node


@dataclass
class Set_literal_stmt(Literal_stmt):
    item_stmts: list[Stmt] = field(default_factory=list)

    def to_json(self) -> Json:
        node = self.base_json()
        node["item_stmts"] = [item.to_json() for item in self.item_stmts]
        return node


@dataclass
class Func_stmt(Stmt):
    call_sym: Sym = field(default_factory=lambda: Sym(default_loc(), name=""))
    arg_sym_list: list[Sym] = field(default_factory=list)

    def to_json(self) -> Json:
        node = self.base_json()
        node["call_sym"] = self.call_sym.to_json()
        node["arg_sym_list"] = [arg.to_json() for arg in self.arg_sym_list]
        return node


class Pred_stmt(Func_stmt, Proposition_stmt):
    pass


@dataclass(init=False)
class Eq_stmt(Pred_stmt):
    dst_sym: Sym
    src_sym: Sym

    def __init__(self, source_loc: Source_loc, dst_sym: Sym, src_sym: Sym, generated: bool = False) -> None:
        super().__init__(source_loc=source_loc, generated=generated, call_sym=Sym(source_loc, name="="), arg_sym_list=[dst_sym, src_sym])
        self.dst_sym = dst_sym
        self.src_sym = src_sym

    def to_json(self) -> Json:
        node = super().to_json()
        node["dst_sym"] = self.dst_sym.to_json()
        node["src_sym"] = self.src_sym.to_json()
        return node


@dataclass(init=False)
class Inherit_stmt(Pred_stmt):
    class_sym: Sym
    src_sym: Sym

    def __init__(self, source_loc: Source_loc, class_sym: Sym, src_sym: Sym, generated: bool = False) -> None:
        super().__init__(source_loc=source_loc, generated=generated, call_sym=Sym(source_loc, name="~"), arg_sym_list=[class_sym, src_sym])
        self.class_sym = class_sym
        self.src_sym = src_sym

    def to_json(self) -> Json:
        node = super().to_json()
        node["class_sym"] = self.class_sym.to_json()
        node["src_sym"] = self.src_sym.to_json()
        return node


class And_stmt(Pred_stmt):
    pass


class Or_stmt(Pred_stmt):
    pass


class Not_stmt(Pred_stmt):
    pass


class Implies_stmt(Pred_stmt):
    pass


class Ne_stmt(Pred_stmt):
    pass


class Gt_stmt(Pred_stmt):
    pass


class Lt_stmt(Pred_stmt):
    pass


class Ge_stmt(Pred_stmt):
    pass


class Le_stmt(Pred_stmt):
    pass


class In_stmt(Pred_stmt):
    pass


class Notin_stmt(Pred_stmt):
    pass


class Subset_stmt(Pred_stmt):
    pass


class Notsubset_stmt(Pred_stmt):
    pass


class Includedin_stmt(Pred_stmt):
    pass


class Notincludedin_stmt(Pred_stmt):
    pass


@dataclass
class Module_stmt(Stmt):
    bound_syms: list[Sym] = field(default_factory=list)
    premise_binding_stmts: list[Binding_stmt] = field(default_factory=list)
    premise_proposition_stmts: list[Stmt] = field(default_factory=list)
    target_proposition_stmts: list[Stmt] = field(default_factory=list)

    def to_json(self) -> Json:
        node = self.base_json()
        node["bound_syms"] = [sym.to_json() for sym in self.bound_syms]
        node["premise_binding_stmts"] = [stmt.to_json() for stmt in self.premise_binding_stmts]
        node["premise_proposition_stmts"] = [stmt.to_json() for stmt in self.premise_proposition_stmts]
        node["target_proposition_stmts"] = [stmt.to_json() for stmt in self.target_proposition_stmts]
        return node


class Set_stmt(Module_stmt):
    pass


@dataclass
class Quantified_stmt(Module_stmt, Proposition_stmt):
    quantifier_sym: Sym = field(default_factory=lambda: Sym(default_loc(), name="∀"))

    def to_json(self) -> Json:
        node = super().to_json()
        node["quantifier_sym"] = self.quantifier_sym.to_json()
        return node


@dataclass
class Typed_sym(AST_node):
    sym: Sym = field(default_factory=lambda: Sym(default_loc(), name=""))

    def to_json(self) -> Json:
        node = self.base_json()
        node["sym"] = self.sym.to_json()
        return node


@dataclass
class Func_decl_stmt(Quantified_stmt):
    func_sym: Sym = field(default_factory=lambda: Sym(default_loc(), name=""))
    input_sym_list: list[Typed_sym] = field(default_factory=list)
    output_sym_list: list[Typed_sym] = field(default_factory=list)
    body_bound_syms: list[Sym] = field(default_factory=list)

    def to_json(self) -> Json:
        node = super().to_json()
        node["func_sym"] = self.func_sym.to_json()
        node["input_sym_list"] = [sym.to_json() for sym in self.input_sym_list]
        node["output_sym_list"] = [sym.to_json() for sym in self.output_sym_list]
        node["body_bound_syms"] = [sym.to_json() for sym in self.body_bound_syms]
        return node


@dataclass
class Class_decl_stmt(Stmt):
    class_sym: Sym = field(default_factory=lambda: Sym(default_loc(), name=""))
    func_decl_stmts: list[Func_decl_stmt] = field(default_factory=list)

    def to_json(self) -> Json:
        node = self.base_json()
        node["class_sym"] = self.class_sym.to_json()
        node["func_decl_stmts"] = [stmt.to_json() for stmt in self.func_decl_stmts]
        return node


PREDICATE_CLASS_BY_CALL = {
    "=": Eq_stmt,
    "~": Inherit_stmt,
    "!=": Ne_stmt,
    "≠": Ne_stmt,
    ">": Gt_stmt,
    "<": Lt_stmt,
    ">=": Ge_stmt,
    "≥": Ge_stmt,
    "<=": Le_stmt,
    "≤": Le_stmt,
    "∈": In_stmt,
    "∉": Notin_stmt,
    "⊂": Subset_stmt,
    "⊄": Notsubset_stmt,
    "⊆": Includedin_stmt,
    "⊈": Notincludedin_stmt,
    "&&": And_stmt,
    "||": Or_stmt,
    "!": Not_stmt,
}


def loc_to_json(loc: SourceLoc | Source_loc | Json) -> Json:
    if isinstance(loc, SourceLoc):
        return loc.to_json()
    if isinstance(loc, Source_loc):
        return loc.to_json()
    return dict(loc)


def iter_sym_nodes(expr: ExprNode | None) -> Iterable[SymNode]:
    if expr is None:
        return []
    output: list[SymNode] = []
    if expr.sym is not None:
        output.append(expr.sym)
    if expr.call_sym is not None:
        output.append(expr.call_sym)
    for child in [*expr.args, *expr.items]:
        output.extend(iter_sym_nodes(child))
    return output


def default_loc() -> Source_loc:
    return Source_loc("__generated__", 1, 1, 1, 1)


def generated_source_name(name: str) -> str:
    return name[1:] if name.startswith("^") else name


def _positive_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and value > 0 else default


def loc_from_json(node: Json | None) -> Source_loc:
    if isinstance(node, dict):
        return Source_loc.from_json(node.get("source_loc") or node.get("loc"))
    return default_loc()


def sym_from_json(node: Json) -> Sym:
    loc = loc_from_json(node)
    name = str(node.get("name", ""))
    generated = bool(node.get("generated")) or name.startswith("^")
    source_name = node.get("source_name")
    return Sym(loc, generated=generated, name=name, source_name=str(source_name) if source_name is not None else None)


def stmt_from_json(node: Json) -> Stmt:
    kind = node.get("kind")
    loc = loc_from_json(node)
    generated = bool(node.get("generated"))
    if kind == "Sym":
        return sym_from_json(node)
    if kind == "Binding_stmt":
        return Binding_stmt(
            source_loc=loc,
            generated=generated,
            dst_sym=sym_from_json(_require_dict(node.get("dst_sym"), "dst_sym")),
            src_stmt=stmt_from_json(_require_dict(node.get("src_stmt"), "src_stmt")),
        )
    if kind == "Char_literal_stmt":
        return Char_literal_stmt(loc, generated=generated, value=str(node.get("value", "")))
    if kind == "Str_literal_stmt":
        return Str_literal_stmt(loc, generated=generated, value=str(node.get("value", "")))
    if kind == "Value_literal_stmt":
        return Value_literal_stmt(loc, generated=generated, value=str(node.get("value", "")))
    if kind == "Tuple_literal_stmt":
        return Tuple_literal_stmt(loc, generated=generated, item_stmts=[stmt_from_json(_require_dict(item, "item_stmts item")) for item in _list(node.get("item_stmts"))])
    if kind == "Set_literal_stmt":
        return Set_literal_stmt(loc, generated=generated, item_stmts=[stmt_from_json(_require_dict(item, "item_stmts item")) for item in _list(node.get("item_stmts"))])
    if kind == "Quantified_stmt":
        return Quantified_stmt(
            source_loc=loc,
            generated=generated,
            bound_syms=[sym_from_json(_require_dict(sym, "bound_syms item")) for sym in _list(node.get("bound_syms"))],
            premise_binding_stmts=[_as_binding(stmt_from_json(_require_dict(stmt, "premise_binding_stmts item"))) for stmt in _list(node.get("premise_binding_stmts"))],
            premise_proposition_stmts=[_as_proposition(stmt_from_json(_require_dict(stmt, "premise_proposition_stmts item"))) for stmt in _list(node.get("premise_proposition_stmts"))],
            target_proposition_stmts=[_as_proposition(stmt_from_json(_require_dict(stmt, "target_proposition_stmts item"))) for stmt in _list(node.get("target_proposition_stmts"))],
            quantifier_sym=sym_from_json(_require_dict(node.get("quantifier_sym", {"kind": "Sym", "name": "∀", "source_loc": loc.to_json()}), "quantifier_sym")),
        )
    if kind == "Set_stmt":
        return Set_stmt(
            source_loc=loc,
            generated=generated,
            bound_syms=[sym_from_json(_require_dict(sym, "bound_syms item")) for sym in _list(node.get("bound_syms"))],
            premise_binding_stmts=[_as_binding(stmt_from_json(_require_dict(stmt, "premise_binding_stmts item"))) for stmt in _list(node.get("premise_binding_stmts"))],
            premise_proposition_stmts=[_as_proposition(stmt_from_json(_require_dict(stmt, "premise_proposition_stmts item"))) for stmt in _list(node.get("premise_proposition_stmts"))],
            target_proposition_stmts=[_as_proposition(stmt_from_json(_require_dict(stmt, "target_proposition_stmts item"))) for stmt in _list(node.get("target_proposition_stmts"))],
        )
    if kind == "Func_stmt" or isinstance(node.get("call_sym"), dict):
        call_sym = sym_from_json(_require_dict(node.get("call_sym"), "call_sym"))
        args = [sym_from_json(_require_dict(arg, "arg_sym_list item")) for arg in _list(node.get("arg_sym_list"))]
        return pred_or_func_from_parts(call_sym, args, loc, generated)
    if isinstance(kind, str) and kind.endswith("_stmt"):
        call_sym = sym_from_json(_require_dict(node.get("call_sym"), "call_sym"))
        args = [sym_from_json(_require_dict(arg, "arg_sym_list item")) for arg in _list(node.get("arg_sym_list"))]
        return pred_or_func_from_parts(call_sym, args, loc, generated, forced_kind=kind)
    raise ValueError(f"unsupported AST JSON kind: {kind!r}")


def pred_or_func_from_parts(call_sym: Sym, args: list[Sym], loc: Source_loc, generated: bool, forced_kind: str | None = None) -> Func_stmt:
    if (forced_kind == "Eq_stmt" or call_sym.name == "=") and len(args) == 2:
        return Eq_stmt(loc, args[0], args[1], generated=generated)
    if (forced_kind == "Inherit_stmt" or call_sym.name == "~") and len(args) == 2:
        return Inherit_stmt(loc, args[0], args[1], generated=generated)
    cls = _forced_or_call_class(forced_kind, call_sym.name)
    return cls(source_loc=loc, generated=generated, call_sym=call_sym, arg_sym_list=args)


def _forced_or_call_class(forced_kind: str | None, call_name: str) -> type[Func_stmt]:
    by_kind = {
        "And_stmt": And_stmt,
        "Or_stmt": Or_stmt,
        "Not_stmt": Not_stmt,
        "Implies_stmt": Implies_stmt,
        "Ne_stmt": Ne_stmt,
        "Gt_stmt": Gt_stmt,
        "Lt_stmt": Lt_stmt,
        "Ge_stmt": Ge_stmt,
        "Le_stmt": Le_stmt,
        "In_stmt": In_stmt,
        "Notin_stmt": Notin_stmt,
        "Subset_stmt": Subset_stmt,
        "Notsubset_stmt": Notsubset_stmt,
        "Includedin_stmt": Includedin_stmt,
        "Notincludedin_stmt": Notincludedin_stmt,
    }
    if forced_kind in by_kind:
        return by_kind[forced_kind]
    return PREDICATE_CLASS_BY_CALL.get(call_name, Func_stmt)


def object_ast_to_json(node: Stmt) -> Json:
    return node.to_json()


def object_ast_from_json(node: Json) -> Stmt:
    reject_legacy_json(node)
    return stmt_from_json(node)


def reject_legacy_json(node: object) -> None:
    if isinstance(node, dict):
        if "premise_PSs" in node or "target_PSs" in node:
            raise ValueError("legacy AST JSON fields premise_PSs/target_PSs are not accepted")
        kind = node.get("kind")
        if isinstance(kind, str) and kind and kind[0].islower():
            raise ValueError(f"legacy AST JSON kind is not accepted: {kind}")
        for value in node.values():
            reject_legacy_json(value)
    elif isinstance(node, list):
        for item in node:
            reject_legacy_json(item)


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _require_dict(value: object, label: str) -> Json:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _as_binding(stmt: Stmt) -> Binding_stmt:
    if not isinstance(stmt, Binding_stmt):
        raise ValueError("premise_binding_stmts item must be Binding_stmt")
    return stmt


def _as_proposition(stmt: Stmt) -> Stmt:
    if isinstance(stmt, Proposition_stmt):
        return stmt
    if isinstance(stmt, Func_stmt):
        return stmt
    return stmt
