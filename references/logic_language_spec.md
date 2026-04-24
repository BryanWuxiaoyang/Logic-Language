# Logic Language Specification

This document is the normative specification for `.lp` logic programs.

The language is organized around four core ideas:
- a program is fundamentally a system of `symbol`s and `condition`s;
- `function`, `class`, `set`, `field`, and `member function` are special ways
  of using symbols;
- `scope` injects implicit premises;
- surface syntax is understood through desugaring into scoped conditions.


# 1. Semantic Model

## 1.1 A Program Is a Constraint System

`.lp` is not primarily an imperative execution language.

Its meaning is:
- some symbols exist;
- these symbols satisfy conditions;
- scopes, inheritance, and module import propagate those conditions.

So the most stable semantic summary is:

> a program is a network of symbols together with conditions that constrain
> those symbols.


## 1.2 The Two Core Semantic Kinds

At the semantic core, a program contains only two kinds of objects:

1. `symbol`
2. `condition`

In this view:
- `function` is a `symbol`;
- `class` is a `symbol`;
- `set` is a `symbol`;
- `cond` is a `symbol`;
- declarations, class bodies, member declarations, branches, and quantifiers
  all reduce to symbol introduction plus condition attachment.


## 1.3 Scope

`scope` is not a third ontological kind. It is a semantic mechanism.

A scope does two things:

1. it introduces local symbols;
2. it injects implicit premise conditions into enclosed conditions.

Examples:
- a function scope implicitly introduces the input symbols, output symbols, and
  the call relation between them;
- a class scope implicitly introduces the premise that the scoped symbol
  inherits that class;
- a branch introduces its branch premise;
- a quantified condition introduces all premise clauses before the target.


## 1.4 Module

An `.lp` file is a module.

A module contains:
- root-scope symbols;
- root-scope conditions;
- root-scope imports;
- non-semantic organization constructs such as comments and headings.

`$import` composes modules at the semantic level. It is not raw textual macro
expansion.


# 2. Core Objects and Intrinsics

## 2.1 Symbol

- `symbol` / `sym` is the base unit of the program.
- `sym(sym)` is named a `call`. It is also a `sym`; it maps one `sym` to
  another `sym`.
- When two written `sym`s have the same name, they are the same `sym`.


## 2.2 Function

- `function` / `func` / `f` is identical to `symbol`.

This is a key modeling rule:
- functions are not a separate runtime object kind;
- function declarations constrain a symbol under a call shape.


## 2.3 Intrinsic Symbols

The language has the following intrinsic symbols:

- `tuple`
- `=`, `≠`, `!`, `&&`
- `null`, `true`, `false`
- `set`, `cond`, `∩`, `∈`
- `~`, `bool`
- `value`
- `∀`, `∃`

Additional intrinsic classes and functions are defined in the standard library
described later in this document.


## 2.4 Tuple

- `tuple` is a `sym`. It represents a function `tuple: id_sym => sym`.
- A literal tuple-like `sym` is written as `(a, b, ...)`.
- `f((a, b))` can be written as `f(a, b)`.
- When a function is written as a binary operator such as `=` or `+`, and is
  used on a 2-element tuple, it can be written as:
  - `op(sym1, sym2) = sym1 op sym2`
- When a function is written as a unary operator such as `*`, and is used on
  one symbol, it can be written as:
  - `op(sym) = opsym`
- For a literal tuple-like `sym` `(sym1, ..., symn)`:
  - `(sym1, ..., symn)(i) = symi` for `i = 1, ..., n`


## 2.5 Equality

- `=(sym1, sym2)` represents whether `sym1` and `sym2` have the same behavior
  in all situations. This is intentionally left ambiguous so the language can
  model different domains.
- `true` and `false` are intrinsic symbols.
- `∀{| sym | sym ≠ null | =(sym, sym) = true }`
- `!true = false`
- `!false = true`
- `≠ = !=`


## 2.6 Set

- `set` is a `sym` / `function`.
- A literal set-like `sym` is written as `{a, b, ...}`.
- For any `sym` shown in `{sym1, ..., symn}`:
  - `{sym1, ..., symn}(sym) = true`
  - otherwise `{sym1, ..., symn}(sym) = false`
- `f({sym1, ..., symn})` can be written as `f{sym1, ..., symn}`.
- `∈` means membership:
  - `sym1 ∈ sym2 = sym2(sym1)`
- `∀{| set1 | set ~ set1 | ∀{| sym | set1(sym) ∈ {true, false} } }`
- `∉` is defined by:
  - `sym1 ∉ sym2 = !(sym1 ∈ sym2)`
- `∩` is defined by:
  - `∩(sym1, sym2)(sym) = sym1(sym) && sym2(sym)`
- `full_set`, `{*} = full_set`
- `empty_set`, `{}` = `empty_set`


## 2.7 Condition

- `cond` is a `sym` / `function`.
- `cond = set`
- The language allows partial or non-classical logical descriptions.
- However, when a condition evaluation depends on itself through a
  non-well-founded cycle and cannot be grounded by finite expansion, the
  program is invalid.

So `condition` should be understood as:
- a predicate-like symbol;
- a condition-set;
- a structured constraint object.


## 2.8 Value

- `value` / `val` / `v` is a `sym`.
- For literal values `0`, `1`, ...:
  - `val ~ 0`
  - `val ~ 1`
  - and so on.


## 2.9 Inheritance `~`

- `~` represents inheritance.
- Written form:
  - `~(sym1, sym2) = sym1 ~ sym2`
- `sym ~ sym`
- For all literal tuple-like symbols `(sym1, ..., symn)`:
  - `tuple ~ (sym1, ..., symn)`
- For all literal set-like symbols `{sym1, ..., symn}`:
  - `set ~ {sym1, ..., symn}`
- `set ~ full_set`
- `set ~ empty_set`
- `bool ~ true`
- `bool ~ false`

Inheritance is the mechanism that propagates conditions from a more general
symbol to a more specific symbol.


# 3. Set Comprehension, Mapped Sets, and Quantified Conditions

## 3.1 Canonical Set-Comprehension Form

The canonical pipe-delimited brace form is:

```text
{| cond1 | cond2 | ... | target }
```

Rules:
- clauses before the final target are premise clauses;
- premises are processed left-to-right;
- if the final target is omitted, use a trailing pipe:
  - `{| cond1 | cond2 | }`

Additional equivalences:

- `{| (sym1, ..., symk) | cond(sym1', ..., symn') | } = cond'`
  - `cond'(sym1, ..., symk) = cond(..., sym1, ..., symk, ...)`
  - the listed symbols are inserted into the corresponding positions in
    `cond`
- `{| cond(sym1, ..., symn) | } = {| (sym1', ..., symk') | cond(sym1, ..., symn) }`
  - `(sym1', ..., symk')` are variables

Operational reading of `{| cond1 | cond2 | ... | target }`:

1. walk through premise clauses from left to right;
2. derive all declared symbols `_syms = (_sym1, _sym2, ...)`;
3. evaluate the final target with those symbols in scope.

Additional syntax rules:
- `,` keeps multiple expressions inside the same clause
  - `{sym1, sym2, sym3} = {| sym1, sym2, sym3 | }`
- multi-line layout is read from top to bottom:

```text
{| cond1 | cond2 | target } =
{
    | cond1
    | cond2
    target
}
```

and

```text
{| cond1 | cond2 | } =
{
    | cond1
    | cond2
}
```

Example:

```text
if integer ~ x, integer ~ y,
{| x = 0 | y > 0 | y < 3 | x, y } = {(0, 1), (0, 2)}
```


## 3.2 Mapped Set

There is an intrinsic mapping operator:

- `apply: (set, f) => set1`

It maps each `sym ∈ set` through `f` into `set1`.

Formal definition:

- `apply(set, f)(sym) = ({| sym' ∈ set | f(sym') = sym } ≠ {})`

Written form:

- `{| cond | f }`

This is a `mapped_set`. It represents a set derived from `{| cond | }`
followed by application of `f`.

Formal definition:

- for any `sym`,
  - `{| cond | f }(sym) = ({| sym' ∈ {| cond | } | sym = f(sym') } ≠ {})`

Validity rule:
- the symbols used in `f` must appear in `conds`, otherwise the mapped set is
  invalid.

Example:

```text
if integer ~ x,
{| x | x > 0 | x < 3 | x + 1 } = {2, 3}
```

Multi-line layout is also read from top to bottom:

```text
{| cond1, cond2 | cond3 | cond4 | f } =
{
    | cond1
    | cond2
    | cond3
    | cond4
    f
}
```


## 3.3 `∀` and `∃`

- `cond ~ ∀`
- `cond ~ ∃`

### `∃`

- `∃: set => bool_sym`
- `∃(set) = (set ≠ {})`
- `set ~ ∃`
- `∃` represents the set of all non-empty sets

Example:

```text
if val ~ x,
∃{| x > 0 | x < 3 | } = ∃{1, 2} = true
```

### `∀`

- `∀: set => bool_sym`
- `∀(set) = (false ∉ set)`
- `set ~ ∀`
- `∀` represents the set of all sets that do not contain `false`

Examples:

```text
if val ~ x,
∀{| x > 1 | x > 0 } = ∀{true} = true
∀{| x > 0 | x < 3 } = ∀{true, false} = false
∀{} = true
```

Canonical written form:

```text
∀{| premise_cond | target_cond } = ∀(set')
set' = {| premise_cond | target_cond }
```


## 3.4 Expanded Quantified Layout

`∀{| premise_cond | target_cond }` may expand to multi-line layout without
explicit braces:

```text
∀{| cond1 | cond2 | target_cond } =
∀
    | cond1
    | cond2
    target_cond
```

Rules:
- each line after `∀` is indented;
- the layout is read from top to bottom.


## 3.5 Target-Clause Decomposition

Inside a quantified condition:

- `,` in `target_cond` means `&&`;
- it can split one set-condition into multiple sub-set-conditions.

Example:

```text
∀{| cond | target_cond1, target_cond2 }
=
∀{| cond | target_cond1 && target_cond2 }
=
∀{| cond | target_cond1 } && ∀{| cond | target_cond2 }
```

Multiple target conditions may also appear alternately between premise clauses.

Example:

```text
∀
    | cond1
    target_cond1, target_cond2
    | cond2
    target_cond3
```

is equivalent to:

```text
∀
    | cond1
    | cond2
    target_cond1
&&
∀
    | cond1
    | cond2
    | target_cond1
    target_cond2
&&
∀
    | cond1
    | cond2
    | target_cond1
    | target_cond2
    target_cond3
```


## 3.6 Branch Decomposition with `|-`

A set-condition expression can be branched with `|-`.
It is identical to multiple split set-conditions, one for each branch.

Example:

```text
∀
    | cond1
        |- branch_cond1
            | cond2
            target_cond1
        |- branch_cond2
            | cond3
            target_cond2
    target_cond3
```

is equivalent to:

```text
∀
    | cond1
    | branch_cond1
    | cond2
    target_cond1
    target_cond3
&&
∀
    | cond1
    | branch_cond2
    | cond3
    target_cond2
    target_cond3
```

and therefore further decomposes to:

```text
∀
    | cond1
    | branch_cond1
    | cond2
    target_cond1
&&
∀
    | cond1
    | branch_cond1
    | cond2
    | target_cond1
    target_cond3
&&
∀
    | cond1
    | branch_cond2
    | cond3
    target_cond2
&&
∀
    | cond1
    | branch_cond2
    | cond3
    | target_cond2
    target_cond3
```

All condition semantics described above can be nested together to generate a
condition.

To fully decompose a nested set-condition:

1. decompose branch conditions first, splitting into sub-set-conditions;
2. for each sub-set-condition, decompose target conditions;
3. gather all resulting sub-conditions as the decomposed result.


# 4. Function Semantics

## 4.1 Function Declaration

A function declaration introduces a symbol together with a call shape.

Example:

```text
add: (v1, v2) => v
```

At the normalized semantic level, the declaration contributes:
- the symbol `add`;
- the local symbols `v1`, `v2`, `v`;
- the implicit call relation `v = add(v1, v2)`.


## 4.2 Conditions Nested in a Function

A `cond` can be nested inside a function.
The function's input arguments and output argument become implicit premise
conditions, and nested conditions use the same expanded layout as ordinary
multi-line conditions.

Example:

```text
add: (v1, v2) => v
    ∀{| v1 = v2 | v = add(v1, v1) }
```

is identical to:

```text
add: (v1, v2) => v

∀
    | v1, v2, v = add(v1, v2)
    ∀{| v1 = v2 | v = add(v1, v1) }
```

So the output argument of a function must satisfy all conditions defined in the
function scope.


## 4.3 Repeated Declarations Merge Conditions

A function may be declared multiple times with the same name in one program.
All declarations contribute conditions to the same function symbol.

Example:

```text
add: (v1, v2) => v
    v = v1 + v2

add: (v1, v2) => v
    ∀{| v1 = v2 | v = add(v1, v1) }
```

is identical to:

```text
add: (v1, v2) => v
    v = v1 + v2
    ∀{| v1 = v2 | v = add(v1, v1) }
```


## 4.4 Prerequisites on Input Arguments

Prerequisites on function input arguments should be written as `| cond`.
This means the declaration only applies under that prerequisite.

Example:

```text
get_mid: (v1, v2) => v
    | v1 < v2
    v = (v1 + v2) / 2

get_mid: (v1, v2) => v
    | v1 > v2
    v = get_mid(v2, v1)
```

If `v1 < v2` and `v1 > v2` were not written as prerequisites, the two bodies
would impose a conflicting condition such as:

```text
∀{| v1, v2, v = get_mid(v1, v2) | v1 > v2, v1 < v2 | false } = false
```

Using prerequisite clauses keeps the two declarations compatible.


## 4.5 Recursive Function Definition

A function condition may contain the function itself.
This is a recursive definition.

The recursive condition is valid if it can be justified through induction.
That is: when the recursive sub-call satisfies all other conditions except the
recursive condition itself, the whole function can still be deduced to satisfy
its specification.

Example:

```text
add: (v1, v2) => v
add: vals => v
    v = sum{| i ∈ [0: vals.size] | vals[i] }

    ∀
        |- vals.size = 1
            v = vals[0]
        |- vals.size > 1
            | v' = add(vals[1:])
            v = vals[0] + v'
```


# 5. Class Semantics

## 5.1 Class

- `class` is the same as `symbol`.
- A class declaration introduces a symbol that is primarily used in
  inheritance conditions.
- A class member function is expanded to a normal function plus an implicit
  class premise.


## 5.2 Primitive Inheritance Rules

There is a primitive inheritance function:

```text
~: (parent_symbol, sub_symbol) => bool
```

Its own implementation is not defined, but it is used to define that the
sub-item satisfies all conditions on the parent-item.

It satisfies:

- `∀{| sym | sym ~ sym }`
- `∀{| sym1, sym2, sym3 | sym1 ~ sym2, sym2 ~ sym3 | sym1 ~ sym3 }`

Example:

```text
val
one
val ~ one
add: (sym1, sym2) => sym3
    | val ~ sym1
    | one ~ sym2
    val ~ sym3
    sym3 = sym1 + 1
```


## 5.3 Cyclic Inheritance on Symbols

When `sym1 ~ sym2` and `sym2 ~ sym1`, we may write:

```text
sym1 ~ sym2 ~ sym1
```

- `∀{| sym1, sym2 | sym1 ~ sym2 ~ sym1 | sym1 = sym2 }`
- `∀{| sym1, sym2, sym3 | sym1 = sym2, sym1 ~ sym3 | sym2 ~ sym3 }`
- `∀{| sym1, sym2, sym3 | sym1 = sym2, sym3 ~ sym1 | sym3 ~ sym2 }`

If multiple symbols are identical by such cyclic inheritance, they form an
`identical-symbol-group`.


## 5.4 Class-Based Naming Convention

In function declarations or condition statements, when a symbol name is written
as `{prefix}{class}` or `{class}{postfix}`, it implicitly contains the
condition that this symbol inherits the class.

Example:

```text
f: (class1, class2) => class3
```

is identical to:

```text
f: (class1, class2) => class3
    | class ~ class1
    | class ~ class2
    class ~ class3
```

If a declared `symbol` or `class` is used as an argument in a function
declaration or condition statement, it refers to a fresh symbol inheriting that
class, rather than the class symbol itself.

Within that function scope, direct occurrences of that name refer to the
argument symbol, not to the original class symbol.

Example:

```text
A
function: A1 => A
    A ~ A1
```

should be understood as:

```text
A
function: sym1 => sym
    | A ~ sym1
    A ~ sym
    sym ~ sym1
```

Therefore, using a class symbol directly as an argument name is recommended
only when the scope does not also need to refer to the class symbol itself.


## 5.5 Class Member Functions

A class can have member functions.

Example:

```text
class::f: (class1, in_arg) => out_arg
```

This is formally defined as a normal function whose first input argument is
constrained by the class premise:

```text
f: (symbol, in_arg) => out_arg
    | class ~ symbol
```

Required equalities:

- `∀{| class1, class2, member_f | class1::member_f = class2::member_f }`

Meaning:
- when two classes both have `member_f`, the two functions are identical;
- the shared function accumulates conditions from all relevant classes.

Consequences:
- because the class symbol is the first argument, the prerequisite is
  `| class ~ symbol`, so it does not conflict with other classes' conditions;
- subclass values can be passed to parent-class methods;
- aspect-style dispatch is also allowed: two unrelated classes may both expose
  a member named `val`, and `sym.val` is valid whenever the symbol satisfies
  the corresponding class premise.

Syntax sugar:

```text
class
    ::f1: (class, in_arg) => out_arg
    ::f2: (class, in_arg) => out_arg
```

is identical to:

```text
class
class::f1: (class, in_arg) => out_arg
class::f2: (class, in_arg) => out_arg
```

When a symbol inherits `class`, `symbol.f` is a function that satisfies:

```text
∀{| sym
    | in_args
    | class ~ sym
    sym.f(in_args) = class::f(sym, in_args)
}
```


## 5.6 Class Member Field

A class can have fields.

Written forms:

- `class::field: class => field`
- or simply `class::field` if the field's class is clear

A field is formally a member function.


## 5.7 Class Inheritance

Because `class` is `symbol`, classes can also inherit each other.

Example:

```text
A
f: A1 => bool
    bool = true
B
A ~ B
∀{| symbol
    | B ~ symbol
    f(symbol) = true
}
```

This is equivalent to:

```text
A
f: symbol => bool
    | A ~ symbol
    bool = true
B
A ~ B
∀{| symbol
    | A ~ symbol
    | B ~ symbol
    f(symbol) = true
}
```

If a subclass declares a member function with the same name and signature as a
parent class, there is an implicit equality:

- `parent_class::f = sub_class::f`

Example:

```text
A ~ B
A::f: (A, v) => v1
    v1 > v
B::f: (B, v) => v1
    v1 = v + 1
```

This is one shared function with merged conditions, equivalent to:

```text
f: (symbol, v) => v1
    ∀
        |- A ~ symbol
            v1 > v
        |- B ~ symbol
            v1 = v + 1
```

Because `A ~ B` and `B ~ symbol`, the `A`-branch also applies to `B`.

Inherited classes can feed into all member functions from parent classes.
Multiple inheritance is allowed; all inherited member declarations and
conditions are merged.

Example:

```text
A::val
    val > 0
B::val
    val < 2
C
A ~ C
B ~ C
```

Then:

- `A::val = B::val = C::val`
- `∀{| C.val > 0, C.val < 2 }`


## 5.8 Cyclic Inheritance on Classes

When `A ~ B ~ A`, the two classes may be used anywhere either class is
required.

Example:

```text
A
    ::val
B
    ::vals
A ~ B
    ::vals = {B.val}
B ~ A
    ::val = *A.vals
```

is identical to:

```text
A
    ::val = *{A.vals}
    ::vals = {A.val}

B
    ::val = *{B.val}
    ::vals = {B.val}
```

Then `A` and `B` are identical because they satisfy the same conditions in all
functions.

If multiple classes are identical by cyclic inheritance, e.g.
`A ~ B`, `B ~ A`, `B ~ C`, `C ~ B`, they form an `identical-class-group`.

Important semantic note:
- because of condition inheritance, class inheritance can only go from a more
  general class to a more specific class.

Example:

```text
val_set::val: v => bool
    bool = ∀{| val = v }
```

This is valid for `val` to represent a `val_set` class.
The inverse direction `val::val_set` is invalid because `val_set` may contain
arbitrarily many values.


## 5.9 Constructor

A class can have a special constructor function:

```text
A
    ::__init__: (in_arg1, in_arg2) => A1
```

So `A1 = A::__init__(in_arg1, in_arg2)` returns an `A` symbol from the
constructor.

Different from normal member functions, the constructor name is
`{class}::__init__` rather than just `__init__`.
This ensures constructors of different classes are not collapsed into one
shared function with unintended merged class premises.


## 5.10 Class Call Function

A class may define a class-call member function:

- `A::__call__: (A, in_arg) => out_arg`
- or inside class scope:

```text
A
    : (A, in_arg) => out_arg
```

This is defined like any other member function.

So:

- `out_arg = A(in_arg)`

uses the function `A::__call__`.


## 5.11 Conditions in a Class Scope

Conditions may appear directly in a class scope.
Such conditions implicitly receive the class as a premise.

Example:

```text
A
    ::val
    ∀{| A.val = 1 }
```

is identical to:

```text
A
    ::val
    ∀{| A | A.val = 1 }
```


## 5.12 Enum Class Pattern

There are no special enum classes in the core language.
Instead, enums are modeled with one class plus a set of subclasses.

Example:

```text
type
type ~ type1
type ~ type2

A
    ::type: A => type

    ::is_type1: A => bool
        bool = (A.type = type1)
```

Here:
- `type` is the general enum class;
- `type1` and `type2` are subclass-like enum values.

For readability, it is recommended to write
`bool = (A.type = type1)` or `bool = ∀{| A.type = type1 }`
instead of a visually ambiguous chained equality.


# 6. Surface Organization, Modules, and Formatting

## 6.1 Comments

Comments are prefixed with `#`.
They do not participate in program semantics.
They are used to describe program parts in a more natural language.


## 6.2 Topic Headings

Topic headings are prefixed with `@`.
They do not participate in program semantics.
They are used only to organize the program for readability.

All content inside a heading is indented by one level.


## 6.3 Module Import

Other `.lp` modules may be imported with:

- `$import module_path`

Both forms import the target module into the current module.

Only `$import` is a valid module directive.
`$include` is not part of the language.

Normative interpretation:
- the imported module contributes its root-scope symbols and root-scope
  conditions to the current module;
- imports are recursive, so the imported module's own imports are also brought
  into scope;
- this should be understood semantically like Python
  `from module import *`, not like C/C++ textual `#include`;
- repeated imports of the same resolved module merge by module identity rather
  than duplicating by raw macro expansion.

Access rules:
- imported items may be used directly when unambiguous;
- they may also be referred to as `{module_name}::{item_name}`.


## 6.4 Chained Comparison

A comparison condition may be chained.

Example:

```text
∀{| x | 0 < x < 3 }
```

is identical to:

```text
∀{| x | 0 < x, x < 3 }
```


## 6.5 Indentation Rules

Required indentation rules:

- all content in a `@topic heading` is indented by one level;
- all conditions in a `function` or `class` declaration are indented by one
  level;
- multi-line expanded conditions are indented by one level;
- branch conditions are indented by one level under the branch parent.

Examples:

```text
∀
    | cond1
    cond
```

and

```text
∀
    | cond1
        |- branch_cond1
            target_cond1
        |- branch_cond2
            target_cond2
```


## 6.6 `else` in Branch Conditions

Inside a branch condition, `|- else` is allowed when the remaining branch
condition is trivial but verbose.

Example:

```text
∀
    | x, y = -x
        |- x > 0
            y < 0
        |- x = 0
            y = 0
        |- else
            y > 0
```

is identical to:

```text
∀
    | x, y = -x
        |- x > 0
            y < 0
        |- x = 0
            y = 0
        |- x < 0
            y > 0
```


# 7. Additional Function Syntax Sugar

## 7.1 Alias Function Name

A function may have an alias name or operator.
The alias is wrapped in parentheses after the full name.

Example:

```text
full_name_function(short_name_f): in_arg => out_arg
```

Then both the full name and the alias may be used to refer to the function.

Operator characters may also be used as function names, overloading an
intrinsic operator.

Example:

```text
A
    ::add(+): (A, A1) => A2
```

This overloads `+`, so `A + A1` may be used to refer to `A.add(A1)`.


## 7.2 Lambda Function

A function may be defined anonymously inline with `->`.

The `->` form declares both the lambda function and the output condition on it.
By contrast, `=>` only declares the function shape.

Example:

```text
in_arg -> f(in_arg)
```

is identical to:

```text
lambda_function: in_arg => out_arg
    out_arg = f(in_arg)
```

When a lambda function is assigned to a named function, the lambda is first
defined and then the named function is constrained to be identical to it.

Example:

```text
function: x => y
function = x -> f(x)
```

is identical to:

```text
function: x => y
    y = f(x)
```

Example with class member:

```text
A
    ::function = (A, x) -> f(A, x)
```

is identical to:

```text
A
    ::function: (A, x) => y
        y = f(A, x)
```

If the member function is a field, the notation may reduce further to
`class::field = val`.

Example:

Given `A::base_val: A => base_val`, the following are identical:

```text
A::val: A => val
    val = A.base_val + 1
```

```text
A::val = A -> A.base_val + 1
```

```text
A::val = A.base_val + 1
```


# 8. Naming Conventions

## 8.1 Symbol Naming Conventions

Symbol names inherently imply inherited classes.

The following conventions are part of the language interpretation:

- `{prefix}{class}`, `{class}{postfix}` represent a symbol inheriting `class`
- `{class}s` is a set or list of symbols inheriting `class`
  - e.g. `vals`
- `{class}_list` is a list of symbols inheriting `class`
- nested naming follows the same conventions recursively
- `{classA}_to_{classB}_map` or `{classA}_to_{classB}_f` is a function mapping
  from `classA` to `classB`
  - e.g. `key_to_value_map`
- `{arbitrary_name}_f` represents a function symbol explicitly declared in the
  scope

These are semantic naming conventions, not merely style suggestions.


# 9. Formal Semantic View

## 9.1 Function as the Only First-Class Kind

- `symbol` is intrinsically function-like.
- `set` is intrinsically a function:
  - `set: symbol => bool`
- a condition function is a function:
  - `condition_function: in_args => bool`
- `∀` / `∃` statements are condition functions.
- `class` is intrinsically a symbol.
- inheritance of `class ~ symbol` is defined through the function `~`.
- class member functions are functions whose first argument inherits the class.
- class inheritance is also defined through `~`.

## 9.2 Standard Library Intrinsics

There are many intrinsic classes and functions defined in:

```text
@/references/standard_library.lp
```

All `.lp` files implicitly import this standard library.


## 9.3 Intrinsic `condition(...)` Function

There is an intrinsic function:

```text
condition({args}, "desc")
```

It describes a semantic condition in natural language `"desc"` involving the
symbols in `{args}`.

Shorthand:

- `condition("desc")`

This implicitly uses all available symbols in the current scope as `{args}`.

Purpose:
- use `condition(...)` when a condition is trivial, complicated, outside the
  current domain knowledge, or inconvenient to write in plain logic syntax;
- unlike comments, `condition(...)` has semantic meaning.

Example:

```text
add: (v1, v2) => v
    # v is the sum of v1 and v2
```

declares `add` but does not constrain it semantically.

Whereas:

```text
add: (v1, v2) => v
    condition("v is the sum of v1 and v2")
```

is semantically equivalent to:

```text
add: (v1, v2) => v
    v = v1 + v2
```


## 9.4 Intrinsic `null`

`null` is an intrinsic value.

When a function's output symbol does not satisfy any conditions, or the output
symbol is explicitly set to `null`, the output is `null`.

Example:

```text
f: v => v1
    |- v > 0
        v1 = v
    |- v = 0
        v1 = null
```

Then:

- `f(-1) = null`
- `f(0) = null`
