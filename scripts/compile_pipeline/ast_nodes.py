"""Mutable AST dataclasses shared by the staged compiler pipeline.

The compiler keeps compatibility renderers for older text-based entry points,
but stage handoffs pass these objects instead of treating text as source of
truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


Json = dict[str, Any]


@dataclass
class SourceLoc:
    source: str
    line: int
    column: int
    end_line: int
    end_column: int

    def to_json(self) -> Json:
        return {
            "source": self.source,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass
class SymNode:
    name: str
    source_loc: SourceLoc | Json | None = None
    generated: bool = False

    def to_json(self) -> Json:
        node: Json = {"kind": "sym", "name": self.name}
        if self.source_loc is not None:
            node["source_loc"] = loc_to_json(self.source_loc)
        if self.generated:
            node["generated"] = True
        return node


@dataclass
class ExprNode:
    kind: str
    source_loc: SourceLoc | Json | None = None
    text: str | None = None
    sym: SymNode | None = None
    call_sym: SymNode | None = None
    args: list["ExprNode"] = field(default_factory=list)
    items: list["ExprNode"] = field(default_factory=list)
    value: str | None = None


@dataclass
class SourceStatement:
    text: str
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
    rhs_text: str = ""
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


@dataclass
class SourceModule:
    type: str
    text: str
    source_loc: SourceLoc | Json | None = None
    quantifier: SymNode | None = None
    statements: list[SourceStatement] = field(default_factory=list)
    declarations: list[FunctionDecl] = field(default_factory=list)
    classes: list[ClassDecl] = field(default_factory=list)
    children: list["SourceModule"] = field(default_factory=list)
    lowered_module: Any | None = None


@dataclass
class SourceFileAst:
    text: str
    source: str
    source_loc: SourceLoc
    imports: list[str] = field(default_factory=list)
    modules: list[SourceModule] = field(default_factory=list)

    def render_text(self) -> str:
        return self.text


def loc_to_json(loc: SourceLoc | Json) -> Json:
    if isinstance(loc, SourceLoc):
        return loc.to_json()
    return dict(loc)


def convert_loc_fields(node: Any) -> Any:
    """Rename legacy final-AST loc fields to source_loc in-place."""
    if isinstance(node, dict):
        if "loc" in node and "source_loc" not in node:
            node["source_loc"] = node.pop("loc")
        for value in node.values():
            convert_loc_fields(value)
    elif isinstance(node, list):
        for item in node:
            convert_loc_fields(item)
    return node


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
