# SPEC for `.lp` Logic Program

- This document defines the required syntax and semantics for logic program files with postfix `.lp`.
- LLM outputs that target this format must follow these rules.
- logic program is used to describe natural language concepts for domain-knowledge/algorithm into a more easy-understand, more logical form. 
- It is a high-order-language with non-classical semantics.
  
# Language Summary
- This language is a hybrid logic language for knowledge representation. It uses rules and conditions as its core, and adopts a unified symbol/function/set/cond view to describe concepts, relations, functions, sets, and class inheritance. It supports premise-to-conclusion reasoning in a style similar to first-order logic and logic programming, while also providing more engineering-oriented features such as classes, member functions, set comprehensions, recursive definitions, and localized natural-language conditions. Overall, it is not a single standard textbook logic system, but is better understood as a high-level knowledge modeling language that blends logic programming, description-logic-style ontology modeling, and functional DSL ideas.

# basics
## symbol
- `symbol`/`sym` represents a base unit for program
- `sym(sym)` is named as a `call`. It is also a `sym`, it maps a `sym` to another `sym`
- When 2 written `sym` has same name, they are same `sym`
  
## function
- A `function`/`func`/`f` is identical to `symbol`

## intrinsic symbols
- `tuple`
- `=`, `≠`, `!`, `&&`
- `null`, `true`, `false`
- `set`, `cond`, `∩`, `∈`
- `~`, `bool`
- `value`
- `∀`, `∃`

## tuple
- `tuple` is a `sym`, represents a function `tuple: id_sym => sym`
- A literal tuple-like `sym` is written as `(a, b, ...)`
- `f((a, b))` can be written as `f(a, b)`
- When the `function` is written as an operator such as `=`/`+`, and is used to feed a 2-elem-tuple, it can be written as: `op(sym1, sym2) = sym1 op sym2`
- When the `function` is written as an operator such as `*`, and is used to feed 1 symbol, it can be written as `op(sym) = opsym`

## equality
- `=(sym1, sym2)`: represents whether `sym1` and `sym2` have same behaviors on all situations. This is intentionally left ambiguous to suit for various contexts.
- `true`
- `false`
- `∀{=(sym, sym) = true | sym ≠ null | sym }`
- `!`: `!true = false`, `!false = true`
- `≠ = !=`
- For a literal tuple-like sym `(sym1, ..., symn)`: `(sym1, ..., symn)(i) = symi` for `i = 1, ..., n`

## set
- `set` is a `sym`/`function`
- A literal set-like `sym` is written as `{a, b, ...}`
- For any `sym` shown in `{sym1, ..., symn}`, `{sym1, ..., symn}(sym) = true`; otherwise `{sym1, sym2, ...}(sym) = false`
- `f({sym1,..., symn})` can be written as `f{sym1,..., symn}`
- `∈`: `sym1 ∈ sym2 = sym2(sym1)`
- `∀{ ∀{ set1(sym) ∈ {true, false} | sym } | set~set1 | set1 }`
- `∉`: `sym1 ∉ sym2 = !(sym1 ∈ sym2)`
- `∩`: ` ∩(sym1, sym2)(sym) = sym1(sym) && sym2(sym)`
- `full_set`, `{*} = full_set`
- `empty_set`, `{} = empty_set`

## cond
- `cond` is a `sym`/`function`
- `cond = set`
- The language allows partial or non-classical logical descriptions.
- However, when a condition evaluation depends on itself through a non-well-founded cycle and cannot be grounded by a finite expansion, the program is invalid.

## value
- `value`/`val`/`v` is a `sym`
- For all literal values `0`/`1`/...: 
  - `val~0`, `val~1`, ...

## inheritance(~)
- `~` represents inheritance relationship
- Written form: `~(sym1, sym2) = sym1~sym2`
- `sym~sym`
- For all literal tuple-like syms `(sym1, ..., symn)`: `tuple~(sym1,...,symn)`
- For all literal set-like syms `{sym1, ..., symn}`: `set~{sym1, ..., symn}`
- `set~full_set`, `set~empty_set`
- `bool`: `bool~true`, `bool~false`

## Set comprehension and mapped sets
- `{| cond(sym1',...,symn') | (sym1, ..., symk)} = cond'`. `cond'(sym1, ..., symk) = cond(...,sym1, ..., symk,...)`, it inserts variables into corresponding pos in `cond`
- `{| cond(sym1,..., symn) } = {| cond(sym1, ..., symn) | (sym1', ..., symk')}`. `(sym1',...,symk')` are variables
- `{| f1(sym1,...) | f2(sym1',...) | ...}`
  - First walk through from right-to-left to derive all declared symbols `_syms = (_sym1, _sym2, ...)`.
  - Then split it to join of multiplt sub_sets: `{| f1(sym1,...) | f2(sym1',...) | ...} = {| f1'(_sym1, ...)} ∩ {| f2'(_sym1, ...)} ...`, where `f1'`/`f2'` is `f1` applied on all `_syms` as input-arg.
  - `,` is identical to `|`, but inner-order is reversed. e.g. `{sym1, sym2, sym3} = {| sym3 | sym2 | sym1}`
  -  E.g. `{| sym2 > 0 | sym1 > 0 | sym1, sym2 }` represents:
    -  Expand `,` to: `{sym2 > 0 | sym1 > 0 | sym2 | sym1}`
    -  Derive `in_args` from right-to-left: `(sym1, sym2)`
    -  Derive to 4 sets:
       - `set1 = {| f1(sym1, sym2) }`, `f1(sym1, sym2) = (sym2 > 0)`
       - `set2 = {| f2(sym1, sym2) }`, `f2(sym1, sym2) = (sym1 > 0)`
    - `set' = {| sym2 > 0 | sym1 > 0 | sym1, sym2} = set1 ∩ set2`. i.e. `set'(sym1, sym2) = (sym1 > 0 && sym2 > 0)`
  - E.g. if `integer~x, integer~y`, `{| y < 3 | y > 0 | x = 0 | x, y } = {(0, 1), (0, 2)}`
  - Written form can be expand to multi-lines, read from bottom-up.
    - E.g. `{| cond3 | cond2 | cond1}` = 
      ```text
          {
              | cond3
              | cond2
              | cond1
          }
      ```

- `apply: (set, f) => set1`, it maps every `sym ∈ set` through `f` into `set1`
  - For all `sym`: `apply(set, f)(sym) = ({ | f(sym') = sym | sym' ∈ set } ≠ {})`
- Written form: `{f | cond}` is a `mapped_set`. It represents a `set'` that derives from `{| cond }` applied on `f`.
  - For any `sym`, `{f | cond}(sym) = ({| sym = f(sym') | sym' ∈ {| cond} } ≠ {})`
  - The symbols used in `f` must appear in `conds`. Otherwise it is invalid.
  - E.g. if `integer~x`, `{ x + 1 | x < 3 | x > 0 | x } = {2, 3}`
  - Written form can expand to multi-lines, read from **bottom-up**.
    - E.g. `{f | cond4 | cond3 | cond1, cond2}` = 
        ```text
            { f
                | cond4
                | cond3
                | cond2
                | cond1
            }
        ```

## ∀/∃ cond
- `cond~∀`, `cond~∃`

- `∃: set => bool_sym`. `∃(set) = (set ≠ {})`
  - `set~∃`. `∃` represents a `set` that stores all non-empty sets.
  - E.g. if `integer~x`, `∃{| x < 3 | x > 0} = ∃{1, 2} = true`

- `∀: set => bool_sym`. `∀(set) = (false ∉ set)`
    - `set~∀`, `∀` represents a `set` that doesn't contain `false`.
    - E.g. if `integer~x`, `∀{ x > 0 | x > 1} = ∀{true} = true`, `∀{ x < 3 | x > 0} = ∀{true, false} = false`, `∀{} = true`

- Written form: `∀{target_cond | premise_cond} = ∀(set')`, `set' = {target_cond | premise_cond }`
  
# extension: syntax-sugars and formating-rules
## ∀ cond: `∀{target_cond | premise_cond}`
- Written form: `∀{target_cond | premise_cond}`
  - Given a `∀`-statement, it's identical to expanding it using all syntax-rules below into `∀{target_cond | premise_cond}` form.
  - `∀{target_cond | premise_cond}` can expand to multi-lines without `{}`, read from **top-down**:
  - Each line after `∀` should be indented
    - E.g. 
      ```text
      ∀{ target_cond | cond2 | cond1 } =
      ∀
          | cond1
          | cond2
          target_cond
      ```
  - `,` in `target_cond` is `&&`, it can split a `set_cond` into multiple `sub_set_conds`.
    - E.g. `∀{ target_cond1, target_cond2 | cond } = ∀{ target_cond1 && target_cond2 | cond } = ∀{target_cond1 | cond} && ∀{target_cond2 | cond}`
  - multiple `target_cond` can appear alternately between `premise_cond`:
    - E.g.
        ```text
        ∀
            | cond1
            target_cond1, target_cond2
            | cond2
            target_cond3
        =
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
  - A `set_cond` expression can be branched with `|-`. It is identical to multiple splited `set_conds`, each represent a branch.
    - E.g.
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
        =

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
        =

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
  - All the condition semantics described above can be nested together to generate a condition.

    E.g.
    ```text
    ∀
    | cond1
        |- branch_cond1
            | cond2
            target_cond1
                |- branch_cond1_1
                    target_cond1_1
                |- branch_cond1_2
                    target_cond1_2
        |- branch_cond2
            | cond3
    target_cond2
    ```
    To fully decompose the `set_cond`, first decompose `branch-conds` to split into multiple `sub_set_conds`. Second, for each `sub_set_cond`, decompose `target_cond` to split into `sub_sub_set_conds`. Finally gather all `sub_sub_set_conds` as the decomposed result.

## cond nested in function
- A `cond` can be nested inside a `function`. The `function`'s in_arg and out_arg will be implicit `premise_conds`.
  - E.g.
  ```text
    add: (v1, v2) => v
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to
    ```text
    add: (v1, v2) => v

    ∀ { v = add(v1, v1)
        | v1 = v2
        | v1, v2, v = add(v1, v2)}
    ```
- The `out_arg` of `function` must satisfy all `conds` defined on it.
- The nested `conds` is represented same as expanded-layout condition. 
  - E.g.
    ```text
    add: (v1, v2) => v
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to a function declaration + nested `conds`:
    ```text
    add: (v1, v2) => v

    ∀
        | v1, v2, v = add(v1, v2)
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```

- A function can be declared multiple times with same name in the program. The function should satisfy all the conditions.
  - E.g.
    ```text
    add: (v1, v2) => v
        v = v1 + v2
    add: (v1, v2) => v
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to:
    ```text
    add: (v1, v2) => v
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```

- Function prerequisites on `input_args` should be written as `| cond`. This means the declaration only applies under the current prerequisite. If there is another definition of the same function with a different prerequisite, the two definitions remain compatible.
  - E.g.
    ```
    get_mid: (v1, v2) => v
        | v1 < v2
        v = (v1 + v2) / 2

    get_mid: (v1, v2) => v
        | v1 > v2
        v = get_mid(v2, v1)
    ```
    if `v1 < v2` and `v1 > v2` are not pre-requisite-conds, there will be `cond`:
    ```
    ∀{ v1 > v2, v1 < v2
        | v1, v2, v = get_mid(v1, v2)
    } = false
    ```

## class
- `class` is same as `symbol`
- The `class-member-function` is expanded to normal `function`

### 1.4 Inheritance
There is an primitive inheritance function `~: (parent_symbol, sub_symbol) => bool`
It itself is undefined, but it is used to define conditions that the sub-item satisfies all conditions on parent-item.
It satisfies:
`∀{ sym~sym | sym }`
`∀{ sym1~sym3 | sym1~sym2, sym2~sym3 | sym1, sym2, sym3 }`
`∀{ !∀{sym2~sym1} | sym1~sym2 | sym1, sym2, sym1 ≠ sym2 }`

E.g.
```
val
one
val~one
add: (sym1, sym2) => sym3
    | val~sym1
    | one~sym2
    val~sym3
    sym3 = sym1 + 1
```
It declares 2 symbols `val` and `one`, and `val~one`. And defined `add` function with inheritance conditions.

### 1.4 Cyclic Inheritance
When `sym1~sym2` and `sym2~sym1` we can use `sym1~sym2~sym1`.
It satisfies:
`∀{ sym2~sym3 | sym1~sym3 | sym3 | sym1 = sym2 }` 
`∀{ sym3~sym2 | sym3~sym1 | sym3 | sym1 = sym2 }` 

If multiple symbols are identical, when call it `identical-symbol-group`.

- `∀{ sym1 = sym2 | sym1~sym2~sym1 | sym1, sym2 }`

### Symbol Naming Convention on Class
In function declaration or condition-statements, when the symbol-name is named as `{prefix}{class}`/`{class}{postfix}`, it implicitly contains a condition that symbol inherits this class.

E.g. 
`f: (class1, class2) => class3` is identical to
```text
f: (class1, class2) => class3:
    | class~class1
    | class~class2
    class~class3
```
Which means when the input_args are all inheriting `class`, then output_arg also inherits `class`.

If a declared `symbol`/`class` is used as argument in function-declaration/condition-statement, it is refering to a new `symbol` inheriting this `class`, instead of `class` itself. Then within this function-scope all conditions referencing `class` is indicating this argument instead of `class`.
E.g.
```
A
function: A1 => A
    A~A1
```
is identical to
```
A
function: sym1 => sym
    | A~sym1
    A~sym
    sym~sym1
```
`A~A1 = sym~sym1`, which is not as expected.
Therefore we should use `class` as argument only if within the scope there is no direct use of `class`, e.g. `class~symbol`. Otherwise it will not be interpreted as class-symbol inheritance, instead symbol-symbol inheritance.

### 1.5.2 Class Member Functions

A class can have member functions.
E.g.
`class::f: (class1, in_arg) => out_arg`

Member functions are formally defined as a function with its first input_arg as  `class1`. So it implicitly contain the premise-condition that first symbol inherits `class`.
E.g.
`class::f: (class1, in_arg) => out_arg`
is identical to:
```text
f: (symbol, in_arg) => out_arg
    | class~symbol
```

`∀{ class1::member_f = class2::member_f | class1, class2, member_f }`, when 2 `class` both have `member_f`, the 2 `functions` are identical, so they share same conditions.

- Because the `class-symbol` is first-arg, it's prerequisite is `| class~symbol`, so it doesn't conflict with other classes' conditions.
- By defining so, sub-class can be put as first-argument in paren-class's methods. Dynamic dispatching on inheritance is achieved.
- Also, aspect-based dynamic dispatching is also allowed. I.e. For 2 unrelated class-symbol, if they both have member-function `val`, then `sym.val` is valid for argument from both class

Syntax-sugar: Member-function can be declared in class-scope:
E.g.
```text
class
    ::f1: (class, in_arg) => out_arg
    ::f2: (class, in_arg) => out_arg
=
class
class::f1: (class, in_arg) => out_arg
class::f2: (class, in_arg) => out_arg
```

When a symbol inherits `class`, `symbol.f` is a function that:
```text
    ∀{ sym.f(in_args) = class::f(sym, in_args)
        | in_args
        | class~sym
        | sym
    }
```

### 1.5.3 Class Member Field
A class can have fields
`class::field: class => field`
or simply
`class::field` if the field's class is clear

field is formally defined as a member function.

### 1.5.4 Class Inheritance

Because `class` is `symbol`, classes can also inherits each other.

E.g.
```text
A
f: A1 => bool
    bool = true
A~B
∀{ f(symbol) = true
    | B~symbol
    | symbol }
```
can be expanded to identical form:
```text
A
f: symbol => bool
    | A~symbol
    bool = true
B
A~B
∀{ f(symbol) = true
    A~symbol
    | B~symbol
    | symbol }
```

If sub-class declares a member-function with the same name and signature as parent-class, there is an implicit equality that: `parent_class::f = sub_class::f`
E.g.
```text
A~B
A::f: (A, v) => v1
    v1 > v
B::f: (B, v) => v1
    v1 = v + 1
```
`A::f` and `B::f` are the same function, becuase they both have same name 'f', 2 in_args, and 1 out_arg. The conditions applied on 2 member-functions are merged in this single funciton. It is identical to
```text
f: (symbol, v) => v1
    ∀
        |- A~symbol
            v1 > v
        |- B~symbol
            v1 = v + 1
```
Because `A~B` and `B~symbol`, it can further expand to:
```text
f: (symbol, v) => v1
    ∀
        |- A~symbol
            v1 > v
        |- B~symbol
            v1 > v
            v1 = v + 1
```

Deduced from formal definition, the inherited class implicitly can feed into all member-functions from parent-class.
E.g.
```text
A
    ::val
    ::f: (A, A1) => v
        v = A.val + A1.val
A~B
    ::val
        val = 1
∀{ v = B1.val + B2.val = 2
    | v = B1.f(B2)
    | B1, B2 }
```
is identical to
```text
∀{ v = 1 + 1 = 2
    B::val(B1) = 1, B::val(B2) = 1
    v = B::val(B1) + B::val(B2)
    A::val = B::val
    v = A::val(B1) + A::val(B2)
    A~B1, A~B2
    v = B::f(B1, B2) = A::f(B1, B2)
    | v = B1.f(B2)
    | B1, B2}
```
Because `A::f = B::f` and `A::val = B::val`, we are able to formally deduce that `B1.f(B2) = B1.val + B2.val`.

- In semantics it implements OOP language features: if `A~B`, then `B` inherits all member-functions and conditions from `A`.

- A class can inherit from multiple parent-classes, inheriting all the function declarations and conditions from the parent-classes.
E.g.
```text
A::val
    val > 0
B::val
    val < 2
C
A~C
B~C
```
Then `A::val = B::val = C::val`, `∀{C.val > 0, C.val < 2}`.

#### 1.5.5 Cyclic Inheritance
Same as cyclic inheritance on symbols, when `A~B~A`, then `A` and `B` are identical classes.

E.g.
```
A
    ::val
B
    ::vals
A~B
    ::vals = {B.val}
B~A
    ::val = *A.vals
```
is identical to
```
A
    ::val = *{A.vals}
    ::vals = {A.val}

B
    ::val = *{B.val}
    ::vals = {B.val}
```
Then we say `A` and `B` are identical because they will have exactly same conditions in any functions.

- Note that because of condition inheritance rule, class-inheritance can only go from general-class to specific-class. E.g. `B::vals` can only hold 1 value, instead of arbitrary size.
E.g. 
```
val_set::val: v => bool
        bool = ∀{val = v}
```
is valid for `val` to represent a `val_set` class.
But inversely `val::val_set` is invalid because `val_set` can have arbitrary vals.

If multiple classes are identical, e.g. `A~B`, `B~A`, `B~C`, `C~B`, we say there is a identical-class-group `{A,B,C}`.

#### 1.5.6 Class Constructor
A class can have a special constructor function declared in it:
```text
A
    ::__init__: (in_arg1, in_arg2) => A1
```
So statement `A1 = A::__init(in_arg1, in_arg2)` is returning `A` symbol from `A::__init__` function.

Different from normal member-functions, the constructor's function-name is `{class}::__init__` instead of `__init__`, therefore classes' constructors are different from each other.
Otherwise, it would be identical to:
```
A::__init__: in_arg => A
B::__init__: in_arg => B

__init__: in_arg => out_arg
    A::out_arg
    B::out_arg
```
This `__init__` function will have condition that out_arg inherits both classes, which is definited not as expected.

#### 1.5.7 Class Call Function
A class can have a class-call-function as member function:

`A::__call__: (A, in_arg) => out_arg`
or
```text
A
    : (A, in_arg) => out_arg
```
It's defined same as other member-functions.

So statement `out_arg = A(in_arg)` is using function `A::__call__`.

#### 1.5.8 Condition in Class
In the class scope there can be conditions. The conditions will have this class as implicit premise_cond.
E.g.
```text
A
    ::val
    ∀{A.val = 1}
```
is identical to
```text
A
    ::val
    ∀{ A.val = 1 | A}
```

#### Enum Class
There is no real-enum-classes. Instead we can declare a `class` and a set of `sub-classes` to represent enums.

E.g.
```text
type
type~type1
type~type2

A
    ::type: A => type

    ::is_type1: A => bool
        bool = ∀{A.type = type1}
```
It first declared a class named 'type'. Then declared 2 sub-classes `type1` and `type2`.

- in `bool = ∀{A.type = type1}`, Although `bool = A.type = type1` is valid. For readability, it's recommended to write as `bool = (A.type = type1)`(here `()` defines operator precedence, not `tuple`) or `bool = ∀{A.type = type1}`

## Comments
Comments are prefixed with '#'. It doesn't participate in the program semantic, just use a more natural way to describe the program parts.

### Topic Headings
Topic headings are prefixed with '@'. It doesn't participate in the program semantic. It's used to organize the program for better readability. All contents inside the heading should be indented by 1 level.

### Module Import
Other `.lp` modules can be imported by `$import {module_path}`. It's copies in all content from `{module_path}`. It will recursively introduce all classes and functions defined in `module_path`.

When accessing items in the `module_path`, we can either directly use item-name if it doesn't cause ambiguity, or use `{module_name}::{item-name}`.

### Chained Comparison
A comparison condition can be chained.
E.g. `∀{ 0 < x < 3 | x}` is identical to `∀{0 < x, x < 3 | x}`

### Recursive Function Definition
A function condition may contain function-itself. This is a recursive definition. The condition is valid if it can be proved through induction. I.e. when sub-function satisfies all other conditions except this recursive condition, the function can be deduced to satisfy those conditions as well.

E.g.
```text
add: (v1, v2) => v
add: vals => v
    v = sum{ vals[i] | i ∈ [0: vals.size]}

    ∀
        |- vals.size = 1
            v = vals[0]
        |- vals.size > 1
            | v' = add(vals[1:])
            v = vals[0] + v'
```
In this example, `add(vals)` has a condition that is recursively defining `add`. We can deduce that when `add(vals[1:]) = sum{ vals[i] | i ∈ [0: vals.size]}`, then `add(vals)= sum{ vals[i] | i ∈ [0: vals.size]}` satisfies.

### Indentation Rules
- All contents in a `@topic heading` is indented by 1 level.
- All conditions in a `function` or `class` declaration is indented by 1 level.
- Multi-line expanded condition is indented by 1 level.
E.g.
```text
∀
    | cond1
    cond
```
- branch condition is indented by 1 level
E.g.
```text
∀
    | cond1
        |- branch_cond1
            target_cond1
        |- branch_cond2
            target_cond2
```

### Alias Function Name
A function can have alias name or operator. The alias name is wrapped in brackets after the full name.
E.g.
```text
full_name_function(short_name_f): in_arg => out_arg
```
Then we can use both full-name or short-name to refer to this function

The operator chars can also be used as function name, and it will overload intrinsic operator.
E.g.
```text
A
    ::add(+): (A, A1) => A2
```
This function overrload '+' operator. We can use `A + A1` to refer to `A.add(A1)`.

### Lambda Function
A function can be anonymously define inline with `->`.

The function's declaration and the condition constraining the output_arg can be defined with `->` statement.
E.g. `in_arg -> f(in_arg)` is identical to 
```text
lambda_function: in_arg => out_arg
    out_arg = f(in_arg)
```

- When A lambda function is assigned to a function, it first defines the lambda function, the define a condtion indicating this `function` is identical to lambda funciton.
E.g.
```text
function: x => y
function = x -> f(x)
```
is identical to
```text
function: x => y
    y = f(x)
```

E.g.
```text
A
    ::function = (A, x) -> f(A, x)
```
is identical to
```text
A
    ::function: (A, x) => y
        y = f(A, x)
```

- Note that `->` declares a lambda function + an output condition on it, and `=>` only declares the function.

- If member-function is a field, we can further reduce to `class::field = val`.
E.g. 
Given `A::base_val: A => base_val`, then
```text
A::val: A => val
    val = A.base_val + 1
```
is identical to
`A::val = A -> A.base_val + 1`
is identical to
`A::val = A.base_val + 1`

### Symbol naming conventions
The symbol-name inherently imply its inherited class.
- `{prefix}{class}`, `{class}{postfix}` represent a symbol inheriting `class`.
- `{class}s` is a set/list of symbols inheriting `class`. E.g. `vals`. It can be either set or list, depending on the context.
- `{class}_list` is a list of symbols inheriting `class`
- nested naming from above rules.
- `{classA}_to_{classB}_map` or `{classA}_to_{classB}_f` is a function-mapping from classA to classB. E.g. `key_to_value_map`
- `{arbitrary_name}_f` represents a function symbol which is declared in the scope explicitly.

### `else` condition in branch-condition
When in branch-condition `|-`, `|- else` is allowed when the remaining condition is trivial and verbose.

E.g.
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
is identical to
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

### Function as the only first-class member
In formal semantics, all items are intrinsically `functions`.
- `symbol` is intrinsically `functions`
- `set` is intrinsically `function`: `set: symbol => bool`
- `condition-functions` is a `function`: `condition-function: in_args => bool`
- `∀`/`∃` statements are `condition-functions`
- `class` is intrinsically `symbol`
- inheritance of `class~symbol` is defined upon function `~`.
- `class-member-function` is intrinsically `function`, with first-arg inheriting `class`.
- class inheritance is defined upon function `~`

### Intrinsics
There are many intrinsic classes/functions defined in `@/references/standard_library.lp`. All `*.lp` files will implicitly import it.

### intrinsic `condition` Function
There is a intrinsic `condition({args}, "desc")` function. It describes a condition with natural language in `"desc"` that includes symbols in `{args}`.

`condition("desc")` describes a condition with `"desc"`, All available symbols in current scope are in `{args}` implicitly.

`condition` function is used to replace condition statements when condition is trivial or complicated or out-of-doman-knowledge-scope or difficult-to-write-in-plain-logic.

It's different from Comments. It has semantic meaning on the program.

E.g.
```text
add: (v1, v2) => v
    # v is the sum of v1 and v2
```
declares a function `add` but doesn't add condition constraint on it. So output `v` has no relation with inputs.

```text
add: (v1, v2) => v
    condition("v is the sum of v1 and v2")
```
is identical to
```text
add: (v1, v2) => v
    v = v1 + v2
```

### Intrinsic symbols
- `null` value
When a function's output-args doesn't satisfy any conditions, or the output-arg is explicitly set to `null`, the output-arg is `null`.
E.g.
```
f: v => v1
    |- v > 0
        v1 = v
    |- v = 0
        v1 = null
```
Then `f(-1) = null`, `f(0) = null`.

# Example References
- `@/references/LC-730 palindrome.lp` and `@/references/LC-730 palindrome.py` are the logic program and the translated python program.
- `@/references/SegTree.lp` and `@/references/SegTree.py` are the logic program and the translated python program.
- `@/references/DataFlowAnalysis.lp` is a program describing compiler-domain-knowledge about data-flow-framework.
